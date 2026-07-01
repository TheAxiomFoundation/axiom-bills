"""Compute rule_variants for every bill — Pipeline B's batch step.

For each bill, walk its applied amendment ops. For each op whose target
section is encoded in rulespec-*, fetch the on-disk YAML, fetch its
atoms from `encoded_rule_atoms`, hand both to the reencoder, and write
the resulting variant row.

Storage is SQLite; the `sync-supabase` step pushes the new rows up. The
function is idempotent — and *incremental*: each variant row records a
fingerprint of the inputs it was computed from (the ops plus the
baseline YAML). Re-running with unchanged inputs leaves the row alone,
which is what keeps LLM-proposed patches alive across recomputes. When
a newer bill text changes the ops (or the baseline moves), the row is
recomputed and any prior LLM proposal is cleared so
`propose-llm-variants` re-proposes against the new inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from .citation_scope import op_affects_encoding
from .db import DEFAULT_DB
from .reencoder import Atom, Op, Tier, _classify_op, reencode_rule_file


def _needs_review_tier(ops: list[Op]) -> Tier:
    """Tier for a variant driven by unapplied instructions.

    Never SUBSTITUTION/NO_OP — nothing was verified against corpus
    text, so a human (or the LLM pass) has to look regardless.
    """
    tiers = {_classify_op(op) for op in ops}
    if Tier.STRUCTURAL in tiers:
        return Tier.STRUCTURAL
    if Tier.LIST in tiers:
        return Tier.LIST
    return Tier.STRUCTURAL


# Where the rulespec-us checkout lives on disk. The frontend will hit
# Supabase for the variant; the writer needs the baseline file. Override
# via env when running in a different layout (e.g. CI).
RULESPEC_ROOT = Path(
    os.environ.get("RULESPEC_US_ROOT", str(Path.home() / "rulespec-us"))
)


def _load_atoms(conn: sqlite3.Connection, encoding_id: str) -> list[Atom]:
    rows = conn.execute(
        """
        SELECT r.rule_name, r.rule_source, a.atom_path, a.atom_kind, a.text
          FROM encoded_rules r
          JOIN encoded_rule_atoms a ON a.rule_id = r.id
         WHERE r.encoding_id = ?
        """,
        (encoding_id,),
    ).fetchall()
    out: list[Atom] = []
    for row in rows:
        out.append(Atom(
            rule_name=row["rule_name"],
            path=row["atom_path"] or "",
            kind=row["atom_kind"] or "",
            text=row["text"] or "",
            rule_source=row["rule_source"] or "",
        ))
    return out


def _encodings_for_section(conn: sqlite3.Connection, citation: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, repo, file_path, citation
          FROM axiom_encodings
         WHERE citation = ?
            OR ? LIKE citation || '(%'
            OR ? LIKE citation || '.%'
            OR citation LIKE ? || '(%'
            OR citation LIKE ? || '.%'
        """,
        (citation, citation, citation, citation, citation),
    ).fetchall()


def _effective_from_for_bill(row: sqlite3.Row) -> date:
    """Pick the effective date the variant should claim.

    If the bill has a `current_status_at` we use that — it's the most
    recent status change. Otherwise fall back to today; rulespec just
    needs *some* date and this is a proposed variant, not law yet.
    """
    raw = row["current_status_at"] if "current_status_at" in row.keys() else None
    if not raw:
        return date.today()
    try:
        return datetime.fromisoformat(raw.split(" ")[0]).date()
    except ValueError:
        return date.today()


def _ops_fingerprint(ops: list[tuple[Op, bool]],
                     baseline_yaml: str | None) -> str:
    """Stable hash of everything the variant's output depends on.

    `ops` pairs each op with its applied flag — an op moving between
    applied and unapplied (corpus drift) changes what the variant means,
    so it must invalidate.
    """
    doc = {
        "ops": [
            {"kind": o.kind, "target": o.target,
             "needle": o.needle, "payload": o.payload, "applied": applied}
            for o, applied in ops
        ],
        "baseline_sha256": (
            hashlib.sha256(baseline_yaml.encode()).hexdigest()
            if baseline_yaml is not None else None
        ),
    }
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def compute_for_bill(conn: sqlite3.Connection, bill_id: str) -> dict[str, int]:
    """Compute and persist rule_variants for one bill. Idempotent."""
    counts = {"variants": 0, "substitution": 0, "list": 0,
              "structural": 0, "no_op": 0, "unchanged": 0}

    bill_row = conn.execute(
        "SELECT id, current_status_at, diffs FROM bills WHERE id=?",
        (bill_id,),
    ).fetchone()
    if not bill_row:
        return counts
    diffs = bill_row["diffs"]
    if not diffs:
        return counts
    payload = json.loads(diffs) if isinstance(diffs, str) else diffs
    text_sha = payload.get("source_text_sha256")
    eff_from = _effective_from_for_bill(bill_row)

    # Group all bill ops by their target encoded file. A single rule
    # YAML may encode multiple sections; we want every op against any of
    # those sections fed to the reencoder in one call so it can
    # cross-reference atoms. Unapplied ops (parsed instructions that
    # couldn't be applied to corpus text — including every redesignate)
    # are tracked too: they can't be auto-patched, but silently dropping
    # them meant a bill could amend an encoded rule with no variant and
    # no flag at all.
    applied_by_enc: dict[str, list[Op]] = {}
    unapplied_by_enc: dict[str, list[Op]] = {}
    encoding_by_id: dict[str, sqlite3.Row] = {}
    for section in payload.get("sections", []):
        section_ops = (
            [(raw, True) for raw in section.get("applied_ops") or []]
            + [(raw, False) for raw in section.get("unapplied_ops") or []]
        )
        if not section_ops:
            continue
        target_citation = section["citation"]
        for enc in _encodings_for_section(conn, target_citation):
            for raw_op, was_applied in section_ops:
                op_kind = raw_op["kind"]
                op_target = raw_op.get("target") or target_citation
                # Prefix matching finds every *related* file; only keep
                # ops that can actually *affect* this one (an add-end
                # against §2015 can't change what
                # statutes/7/2015/d/2/B.yaml encodes).
                if not op_affects_encoding(enc["citation"], op_target, op_kind):
                    continue
                encoding_by_id[enc["id"]] = enc
                bucket = applied_by_enc if was_applied else unapplied_by_enc
                bucket.setdefault(enc["id"], []).append(Op(
                    kind=op_kind,
                    target=op_target,
                    needle=raw_op.get("needle", ""),
                    payload=raw_op.get("payload", ""),
                ))

    for encoding_id in encoding_by_id:
        enc = encoding_by_id[encoding_id]
        applied_ops = applied_by_enc.get(encoding_id, [])
        unapplied_ops = unapplied_by_enc.get(encoding_id, [])
        fingerprint_ops = (
            [(o, True) for o in applied_ops]
            + [(o, False) for o in unapplied_ops]
        )
        file_path = enc["file_path"]
        repo = enc["repo"]
        repo_root = (Path(os.environ.get(
            f"{repo.upper().replace('-', '_')}_ROOT",
            str(Path.home() / repo),
        )))
        baseline_path = repo_root / file_path
        if not baseline_path.exists():
            # Repo not checked out; record a no-op variant so the bill
            # page can show "no baseline available" rather than silently
            # dropping it.
            outcome = _upsert_variant(
                conn, bill_id, encoding_id, file_path,
                tier=Tier.NO_OP, patched_rule_names=[],
                baseline_yaml=None, patched_yaml=None,
                diff_summary=None,
                note=f"Baseline YAML not on disk at {baseline_path}",
                effective_from=eff_from,
                ops_fingerprint=_ops_fingerprint(fingerprint_ops, None),
                text_sha256=text_sha,
                proposed_by=None,
            )
            counts["unchanged" if outcome == "unchanged" else "no_op"] += 1
            continue
        baseline_yaml = baseline_path.read_text()
        fingerprint = _ops_fingerprint(fingerprint_ops, baseline_yaml)

        if applied_ops:
            atoms = _load_atoms(conn, encoding_id)
            result = reencode_rule_file(
                baseline_yaml, applied_ops, atoms, effective_from=eff_from,
            )
            tier = result.tier
            patched_rules = result.patched_rules
            patched_yaml = result.patched_yaml if tier == Tier.SUBSTITUTION else None
            diff_summary = result.diff_summary or None
            note = result.note or None
            if unapplied_ops:
                extra = (f"{len(unapplied_ops)} additional instruction(s) "
                         "could not be auto-applied to corpus text — "
                         "needs review.")
                note = f"{note} {extra}" if note else extra
                # A partially-understood amendment isn't a clean no-op.
                if tier == Tier.NO_OP:
                    tier = _needs_review_tier(unapplied_ops)
        else:
            # Unapplied-only: the bill's parsed instructions target this
            # encoded file but couldn't be applied mechanically. Record
            # a needs-review variant so Pipeline B (and the LLM pass)
            # still sees it.
            tier = _needs_review_tier(unapplied_ops)
            patched_rules = []
            patched_yaml = None
            diff_summary = None
            note = (f"{len(unapplied_ops)} amendment instruction(s) parsed "
                    "but could not be auto-applied to corpus text — "
                    "needs review.")

        outcome = _upsert_variant(
            conn, bill_id, encoding_id, file_path,
            tier=tier, patched_rule_names=patched_rules,
            # Always store the baseline — the bill page wants to render a
            # "current" tab for every variant, not just auto-patchable ones.
            baseline_yaml=baseline_yaml,
            patched_yaml=patched_yaml,
            diff_summary=diff_summary,
            note=note,
            effective_from=eff_from,
            ops_fingerprint=fingerprint,
            text_sha256=text_sha,
            proposed_by="auto" if patched_yaml else None,
        )
        if outcome == "unchanged":
            counts["unchanged"] += 1
        else:
            counts["variants"] += 1
            counts[tier.value] = counts.get(tier.value, 0) + 1

    # Drop variants for files this bill's current diffs no longer touch
    # (e.g. an engrossed text dropped a section) — otherwise they'd claim
    # the bill still patches a rule it no longer amends.
    current_files = {
        encoding_by_id[eid]["file_path"] for eid in encoding_by_id
    }
    for row in conn.execute(
        "SELECT id, file_path FROM rule_variants WHERE bill_id=?",
        (bill_id,),
    ).fetchall():
        if row["file_path"] not in current_files:
            conn.execute("DELETE FROM rule_variants WHERE id=?", (row["id"],))
            counts["removed_stale"] = counts.get("removed_stale", 0) + 1

    return counts


def _upsert_variant(conn: sqlite3.Connection, bill_id: str, encoding_id: str,
                    file_path: str, *, tier: Tier,
                    patched_rule_names: list[str],
                    baseline_yaml: str | None, patched_yaml: str | None,
                    diff_summary: str | None, note: str | None,
                    effective_from: date,
                    ops_fingerprint: str,
                    text_sha256: str | None,
                    proposed_by: str | None) -> str:
    """Insert/update one variant row. Returns 'inserted' | 'updated' |
    'unchanged'.

    Unchanged inputs (same ops fingerprint) leave the row untouched:
    this is what preserves an LLM-proposed patched_yaml — and stops
    effective_from drifting with every status action — across
    recomputes. Changed inputs replace the row wholesale; a stale LLM
    proposal is cleared so propose-llm-variants re-proposes against the
    new bill text.
    """
    row = conn.execute(
        """
        SELECT id, source_ops_fingerprint, proposed_by, proposed_model
          FROM rule_variants WHERE bill_id=? AND file_path=?
        """,
        (bill_id, file_path),
    ).fetchone()
    if row:
        if row["source_ops_fingerprint"] == ops_fingerprint:
            return "unchanged"
        superseded_llm = row["proposed_by"] == "llm"
        if superseded_llm:
            stale = (f"Superseded {row['proposed_model'] or 'LLM'} proposal: "
                     "bill amendments or baseline changed since it was drafted.")
            note = f"{note}; {stale}" if note else stale
        conn.execute(
            """
            UPDATE rule_variants
               SET encoding_id=?, tier=?, patched_rule_names=?,
                   baseline_yaml=?, patched_yaml=?, diff_summary=?, note=?,
                   effective_from=?, source_ops_fingerprint=?,
                   source_text_sha256=?, proposed_by=?, proposed_model=NULL,
                   computed_at=datetime('now')
             WHERE id=?
            """,
            (encoding_id, tier.value, json.dumps(patched_rule_names),
             baseline_yaml, patched_yaml, diff_summary, note,
             effective_from.isoformat(), ops_fingerprint, text_sha256,
             proposed_by, row["id"]),
        )
        return "updated"
    conn.execute(
        """
        INSERT INTO rule_variants
            (id, bill_id, encoding_id, file_path, tier, patched_rule_names,
             baseline_yaml, patched_yaml, diff_summary, note, effective_from,
             source_ops_fingerprint, source_text_sha256, proposed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bill_id, file_path) DO UPDATE SET
            encoding_id=excluded.encoding_id, tier=excluded.tier,
            patched_rule_names=excluded.patched_rule_names,
            baseline_yaml=excluded.baseline_yaml,
            patched_yaml=excluded.patched_yaml,
            diff_summary=excluded.diff_summary, note=excluded.note,
            effective_from=excluded.effective_from,
            source_ops_fingerprint=excluded.source_ops_fingerprint,
            source_text_sha256=excluded.source_text_sha256,
            proposed_by=excluded.proposed_by, proposed_model=NULL,
            computed_at=datetime('now')
        """,
        (uuid.uuid4().hex, bill_id, encoding_id, file_path,
         tier.value, json.dumps(patched_rule_names),
         baseline_yaml, patched_yaml, diff_summary, note,
         effective_from.isoformat(), ops_fingerprint, text_sha256,
         proposed_by),
    )
    return "inserted"


def compute_all(db_path: str = DEFAULT_DB,
                jurisdiction: str | None = None) -> dict[str, int]:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    where = ""
    params: tuple = ()
    if jurisdiction:
        where = "WHERE jurisdiction = ?"
        params = (jurisdiction,)
    bill_ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM bills {where}", params,
    ).fetchall()]

    totals: dict[str, int] = {}
    for bill_id in bill_ids:
        counts = compute_for_bill(conn, bill_id)
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
    conn.close()
    return totals
