"""Precompute per-bill diffs into a JSONB column.

The frontend reads `bills.bills.diffs` directly and renders everything
client-side — no Python API at runtime. This module duplicates the
shape the FastAPI ``/bills/{id}/diffs`` endpoint produces so the
frontend's existing types continue to work.

Called from the CLI as ``axiom-bills precompute-diffs`` and writes back
to local SQLite (so the next ``sync-supabase`` pushes it). Keeping the
write path local-first means we can recompute without round-tripping
Supabase, which is friendlier when iterating on parser changes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any

from .citation_scope import is_ancestor, op_affects_encoding
from .corpus_client import fetch as fetch_corpus
from .effective_date import extract_effective_date
from .version_rank import stage_rank
from .amendments import (
    normalize_legal_text,
    slice_subsection,
    unified_diff,
)
from .amendment_blocks import apply_block, parse_bill_amendments
from .db import DEFAULT_DB


AXIOM_APP_URL = os.environ.get(
    "AXIOM_APP_URL", "https://app.axiom-foundation.org"
)


def _exact_corpus_body(db_path: str):
    """Build a `citation -> exact corpus body` lookup for the applier.

    Only an exact hit counts. `fetch_corpus` falls back to ancestors,
    which is right for choosing what to display but wrong for scoping an
    edit: an ancestor's body is a wider span than the citation names.
    """
    def resolve(citation: str) -> str | None:
        prov = fetch_corpus(citation, db_path=db_path)
        if prov is None or not prov.is_exact_match:
            return None
        return prov.body
    return resolve


def _op_dict(op) -> dict:
    return {
        "kind":   getattr(op, "kind", ""),
        "target": getattr(op, "target", ""),
        "needle": getattr(op, "needle", ""),
        "payload": getattr(op, "payload", ""),
        "anchor": getattr(op, "anchor", ""),
        "redesignate_to": getattr(op, "redesignate_to", ""),
        "scope_source": getattr(op, "scope_source", ""),
        "raw":    getattr(op, "raw", ""),
    }


def _encoding_for(conn: sqlite3.Connection, citation: str,
                  ops: list | None = None) -> dict | None:
    """Pick the encoded file that represents this section, if any.

    Candidates are found by bidirectional prefix match; the pick is
    op-aware: a file is only eligible if at least one of the section's
    ops can affect it (an add-end against §2015 can't touch a nested
    statutes/7/2015/d/2/B.yaml). Preference order: exact citation, then
    nearest ancestor (the file that *contains* the target), then the
    deepest affected descendant.
    """
    rows = conn.execute(
        """
        SELECT jurisdiction, repo, kind, citation, file_path
        FROM axiom_encodings
        WHERE citation = ?
           OR ? LIKE citation || '(%'
           OR ? LIKE citation || '.%'
           OR citation LIKE ? || '(%'
           OR citation LIKE ? || '.%'
        """,
        (citation, citation, citation, citation, citation),
    ).fetchall()
    if not rows:
        return None

    op_list = [
        (getattr(op, "target", "") or citation, getattr(op, "kind", ""))
        for op in (ops or [])
    ]

    def eligible(row) -> bool:
        if not op_list:
            # No parsed ops: only exact/ancestor files may represent the
            # section — a child file can't stand in for its parent.
            return row["citation"] == citation or \
                is_ancestor(row["citation"], citation)
        return any(
            op_affects_encoding(row["citation"], target, kind)
            for target, kind in op_list
        )

    exact = [r for r in rows if r["citation"] == citation]
    ancestors = sorted(
        (r for r in rows if is_ancestor(r["citation"], citation)),
        key=lambda r: -len(r["citation"]),
    )
    descendants = sorted(
        (r for r in rows if is_ancestor(citation, r["citation"])),
        key=lambda r: -len(r["citation"]),
    )
    for pool in (exact, ancestors, descendants):
        for row in pool:
            if eligible(row):
                return {
                    "repo": row["repo"],
                    "kind": row["kind"],
                    "citation": row["citation"],
                    "file_path": row["file_path"],
                    "github_url": f"https://github.com/TheAxiomFoundation/{row['repo']}/blob/main/{row['file_path']}",
                }
    return None


def _related_encodings_exist(conn: sqlite3.Connection, citation: str) -> bool:
    """Any encoded file related to this citation by nesting?

    Used when a section gets NO affected encoding: if related files
    exist, the bill is adding provisions inside an encoded program area
    — an encoder-backlog signal, distinct from 'unencoded territory'.
    """
    return conn.execute(
        """
        SELECT 1 FROM axiom_encodings
        WHERE citation = ?
           OR ? LIKE citation || '(%'
           OR ? LIKE citation || '.%'
           OR citation LIKE ? || '(%'
           OR citation LIKE ? || '.%'
        LIMIT 1
        """,
        (citation, citation, citation, citation, citation),
    ).fetchone() is not None


def compute_one_bill(conn: sqlite3.Connection, bill_id: str,
                     db_path: str = DEFAULT_DB) -> dict:
    """Compute the same JSON shape the API returned for /bills/{id}/diffs."""
    # Highest legislative stage wins; fetched_at only breaks ties.
    # Ordering by fetched_at alone let an older-stage text shadow an
    # enrolled one whenever their fetch times interleaved.
    text_rows = conn.execute(
        "SELECT version_label, text, text_sha256, fetched_at"
        "  FROM bill_texts WHERE bill_id = ?",
        (bill_id,),
    ).fetchall()
    text_row = max(
        text_rows,
        key=lambda r: (stage_rank(r["version_label"]), r["fetched_at"] or ""),
        default=None,
    )
    bill_text = text_row["text"] if text_row else ""
    text_sha = text_row["text_sha256"] if text_row else None

    blocks = parse_bill_amendments(bill_text)

    sections: list[dict] = []

    for block in blocks:
        target = block.target
        encoding = _encoding_for(conn, target, block.operations)
        encoding_backlog = (
            encoding is None
            and bool(block.operations)
            and _related_encodings_exist(conn, target)
        )
        prov = fetch_corpus(target, db_path=db_path)
        if prov is None or not prov.body:
            sections.append(_unmatched(target, encoding,
                                       encoding_backlog=encoding_backlog,
                                       parse_warnings=block.parse_warnings,
                                       operations=block.operations))
            continue

        applied_result = apply_block(
            block, prov.body, slice_subsection,
            resolve_scope=_exact_corpus_body(db_path),
            body_is_exact=prov.is_exact_match,
        )

        # apply_block has already narrowed to the block's own scope —
        # via the exact corpus row where one exists, else the marker
        # heuristics, else the enclosing section under the unique-match
        # rule. Re-slicing here would duplicate that logic and could
        # disagree with the text the ops were actually applied to.
        before = applied_result.before_text or prov.body
        after = applied_result.after_text or before
        sections.append(_section_payload(
            target, encoding, prov,
            encoding_backlog=encoding_backlog,
            before=before, after=after,
            applied=applied_result.applied,
            unapplied=applied_result.unapplied,
            block_warnings=block.parse_warnings + applied_result.notes,
            block_raw=block.raw,
            sliced=not prov.is_exact_match,
            exact_match=prov.is_exact_match,
        ))

    # NOTE: we used to render encoded-citation-only sections here as
    # "context" for every encoding the bill cited (without amending). But
    # a mere cross-reference doesn't force a re-encode, so surfacing it
    # produced false 'touches rulespec' signals (cf. H.R.1865 → §26 USC
    # 152). The strict policy: only emit sections where the parser
    # actually targeted the citation with an amendment block.

    statutory_date = extract_effective_date(bill_text)
    return {
        "sections": sections,
        "source_text_sha256": text_sha,
        "statutory_effective_from": (
            statutory_date.isoformat() if statutory_date else None
        ),
    }


def _section_payload(target: str, encoding: dict | None, prov, *,
                     before: str, after: str,
                     applied: list, unapplied: list,
                     block_warnings: list, block_raw: str,
                     sliced: bool, exact_match: bool = False,
                     encoding_backlog: bool = False) -> dict:
    before_norm = normalize_legal_text(before)
    after_norm = normalize_legal_text(after)
    diff = unified_diff(before_norm, after_norm) if applied else []
    return {
        "citation": target,
        "in_corpus": True,
        "exact_corpus_match": exact_match,
        "sliced_subsection": sliced,
        "matched_corpus_path": prov.citation_path,
        "heading": prov.heading,
        "citation_path": prov.citation_path,
        "current_text": before_norm,
        "applied_text": after_norm,
        "diff": diff,
        "applied_ops": [_op_dict(o) for o in applied],
        "unapplied_ops": [
            {**_op_dict(o), "note": note} for o, note in unapplied
        ],
        "parse_warnings": block_warnings,
        "block_raw": block_raw[:1200] if block_warnings else None,
        "has_rulespec": bool(encoding),
        "encoding": encoding,
        "encoding_backlog": encoding_backlog,
        "axiom_url": f"{AXIOM_APP_URL}/{prov.citation_path}",
        "source_url": prov.source_url,
    }


def _unmatched(citation: str, encoding: dict | None, *,
               parse_warnings: list | None = None,
               operations: list | None = None,
               encoding_backlog: bool = False) -> dict:
    return {
        "citation": citation,
        "in_corpus": False,
        "exact_corpus_match": False,
        "sliced_subsection": False,
        "matched_corpus_path": None,
        "heading": None,
        "citation_path": None,
        "current_text": None,
        "applied_text": None,
        "diff": [],
        "applied_ops": [],
        "unapplied_ops": [_op_dict(o) for o in (operations or [])],
        "parse_warnings": parse_warnings or [],
        "block_raw": None,
        "has_rulespec": bool(encoding),
        "encoding": encoding,
        "encoding_backlog": encoding_backlog,
        "axiom_url": None,
        "source_url": None,
    }


def precompute_all(db_path: str = DEFAULT_DB,
                   jurisdiction: str | None = None) -> dict[str, int]:
    """Walk every bill, compute its diffs, store as JSON in `bills.diffs`."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(bills)")]
    if "diffs" not in cols:
        conn.execute("ALTER TABLE bills ADD COLUMN diffs TEXT")
    if "touches_rulespec" not in cols:
        conn.execute(
            "ALTER TABLE bills ADD COLUMN touches_corpus INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "ALTER TABLE bills ADD COLUMN touches_rulespec INTEGER NOT NULL DEFAULT 0")
    if "needs_new_encoding" not in cols:
        conn.execute(
            "ALTER TABLE bills ADD COLUMN needs_new_encoding INTEGER NOT NULL DEFAULT 0")

    n_encodings = conn.execute(
        "SELECT count(*) AS n FROM axiom_encodings"
    ).fetchone()["n"]
    if n_encodings == 0:
        # Recomputing diffs without an indexed rulespec sets
        # encoding: null on every section — and a later sync-supabase
        # would overwrite good remote matches with those nulls. Run
        # `index-encodings --repo <rulespec clone>` first.
        print(
            "WARNING: axiom_encodings is empty — diffs will carry no "
            "rulespec matches. Run index-encodings before precompute-diffs.",
            file=sys.stderr,
        )

    where = ""
    params: tuple = ()
    if jurisdiction:
        where = "WHERE jurisdiction = ?"
        params = (jurisdiction,)
    bill_ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM bills {where}", params
    ).fetchall()]

    counts = {"bills": 0, "with_sections": 0, "with_ops": 0}
    for bill_id in bill_ids:
        payload = compute_one_bill(conn, bill_id, db_path=db_path)
        counts["bills"] += 1
        if payload["sections"]:
            counts["with_sections"] += 1
        if any(s["applied_ops"] for s in payload["sections"]):
            counts["with_ops"] += 1
        # Materialized relevance flags — same predicate as the
        # bill_list_summary view: a match needs >=1 parsed amendment op.
        # Unapplied ops count: they're real amendment instructions the
        # applier couldn't verify against corpus text (drift, every
        # redesignate) — excluding them made such bills silently invisible
        # to the re-encode trigger.
        touches_rulespec = any(
            s["encoding"] and (s["applied_ops"] or s["unapplied_ops"])
            for s in payload["sections"]
        )
        touches_corpus = any(
            s["in_corpus"] and s.get("citation_path")
            and (s["applied_ops"] or s["unapplied_ops"])
            for s in payload["sections"]
        )
        # Amends inside an encoded program area but no existing rule file
        # is affected → new provision → encoder backlog.
        needs_new_encoding = any(
            s.get("encoding_backlog") for s in payload["sections"]
        )
        conn.execute(
            "UPDATE bills SET diffs = ?, touches_corpus = ?,"
            " touches_rulespec = ?, needs_new_encoding = ? WHERE id = ?",
            (json.dumps(payload), int(touches_corpus),
             int(touches_rulespec), int(needs_new_encoding), bill_id),
        )
    conn.close()
    return counts
