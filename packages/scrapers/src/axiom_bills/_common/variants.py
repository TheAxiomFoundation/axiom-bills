"""Compute rule_variants for every bill — Pipeline B's batch step.

For each bill, walk its applied amendment ops. For each op whose target
section is encoded in rulespec-*, fetch the on-disk YAML, fetch its
atoms from `encoded_rule_atoms`, hand both to the reencoder, and write
the resulting variant row.

Storage is SQLite; the `sync-supabase` step pushes the new rows up. The
function is idempotent: re-running over the same bill just upserts the
variant row.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .db import DEFAULT_DB
from .reencoder import Atom, Op, Tier, reencode_rule_file


# Where the rulespec-us checkout lives on disk. The frontend will hit
# Supabase for the variant; the writer needs the baseline file. Override
# via env when running in a different layout (e.g. CI).
RULESPEC_ROOT = Path(
    os.environ.get("RULESPEC_US_ROOT", str(Path.home() / "rulespec-us"))
)


def _load_atoms(conn: sqlite3.Connection, encoding_id: str) -> list[Atom]:
    rows = conn.execute(
        """
        SELECT r.rule_name, a.atom_path, a.atom_kind, a.text
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


def compute_for_bill(conn: sqlite3.Connection, bill_id: str) -> dict[str, int]:
    """Compute and persist rule_variants for one bill. Idempotent."""
    counts = {"variants": 0, "substitution": 0, "list": 0,
              "structural": 0, "no_op": 0}

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
    eff_from = _effective_from_for_bill(bill_row)

    # Group all bill ops by their target encoded file. A single rule
    # YAML may encode multiple sections; we want every op against any of
    # those sections fed to the reencoder in one call so it can
    # cross-reference atoms.
    ops_by_encoding_id: dict[str, list[Op]] = {}
    encoding_by_id: dict[str, sqlite3.Row] = {}
    for section in payload.get("sections", []):
        if not section.get("applied_ops"):
            continue
        target_citation = section["citation"]
        for enc in _encodings_for_section(conn, target_citation):
            encoding_by_id[enc["id"]] = enc
            for raw_op in section["applied_ops"]:
                ops_by_encoding_id.setdefault(enc["id"], []).append(Op(
                    kind=raw_op["kind"],
                    target=raw_op.get("target", target_citation),
                    needle=raw_op.get("needle", ""),
                    payload=raw_op.get("payload", ""),
                ))

    for encoding_id, ops in ops_by_encoding_id.items():
        enc = encoding_by_id[encoding_id]
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
            _upsert_variant(
                conn, bill_id, encoding_id, file_path,
                tier=Tier.NO_OP, patched_rule_names=[],
                baseline_yaml=None, patched_yaml=None,
                diff_summary=None,
                note=f"Baseline YAML not on disk at {baseline_path}",
                effective_from=eff_from,
            )
            counts["no_op"] += 1
            continue
        baseline_yaml = baseline_path.read_text()
        atoms = _load_atoms(conn, encoding_id)
        result = reencode_rule_file(
            baseline_yaml, ops, atoms, effective_from=eff_from,
        )
        _upsert_variant(
            conn, bill_id, encoding_id, file_path,
            tier=result.tier, patched_rule_names=result.patched_rules,
            baseline_yaml=baseline_yaml if result.tier == Tier.SUBSTITUTION else None,
            patched_yaml=result.patched_yaml if result.tier == Tier.SUBSTITUTION else None,
            diff_summary=result.diff_summary or None,
            note=result.note or None,
            effective_from=eff_from,
        )
        counts["variants"] += 1
        counts[result.tier.value] = counts.get(result.tier.value, 0) + 1

    return counts


def _upsert_variant(conn: sqlite3.Connection, bill_id: str, encoding_id: str,
                    file_path: str, *, tier: Tier,
                    patched_rule_names: list[str],
                    baseline_yaml: str | None, patched_yaml: str | None,
                    diff_summary: str | None, note: str | None,
                    effective_from: date) -> None:
    row = conn.execute(
        "SELECT id FROM rule_variants WHERE bill_id=? AND file_path=?",
        (bill_id, file_path),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE rule_variants
               SET encoding_id=?, tier=?, patched_rule_names=?,
                   baseline_yaml=?, patched_yaml=?, diff_summary=?, note=?,
                   effective_from=?, computed_at=datetime('now')
             WHERE id=?
            """,
            (encoding_id, tier.value, json.dumps(patched_rule_names),
             baseline_yaml, patched_yaml, diff_summary, note,
             effective_from.isoformat(), row["id"]),
        )
        return
    conn.execute(
        """
        INSERT INTO rule_variants
            (id, bill_id, encoding_id, file_path, tier, patched_rule_names,
             baseline_yaml, patched_yaml, diff_summary, note, effective_from)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, bill_id, encoding_id, file_path,
         tier.value, json.dumps(patched_rule_names),
         baseline_yaml, patched_yaml, diff_summary, note,
         effective_from.isoformat()),
    )


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
