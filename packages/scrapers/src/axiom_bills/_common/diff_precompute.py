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

from .corpus_client import fetch as fetch_corpus
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


def _op_dict(op) -> dict:
    return {
        "kind":   getattr(op, "kind", ""),
        "target": getattr(op, "target", ""),
        "needle": getattr(op, "needle", ""),
        "payload": getattr(op, "payload", ""),
        "anchor": getattr(op, "anchor", ""),
        "redesignate_to": getattr(op, "redesignate_to", ""),
        "raw":    getattr(op, "raw", ""),
    }


def _encoding_for(conn: sqlite3.Connection, citation: str) -> dict | None:
    row = conn.execute(
        """
        SELECT jurisdiction, repo, kind, citation, file_path
        FROM axiom_encodings
        WHERE citation = ?
           OR ? LIKE citation || '(%'
           OR ? LIKE citation || '.%'
           OR citation LIKE ? || '(%'
           OR citation LIKE ? || '.%'
        ORDER BY length(citation) DESC
        LIMIT 1
        """,
        (citation, citation, citation, citation, citation),
    ).fetchone()
    if not row:
        return None
    return {
        "repo": row["repo"],
        "kind": row["kind"],
        "citation": row["citation"],
        "file_path": row["file_path"],
        "github_url": f"https://github.com/TheAxiomFoundation/{row['repo']}/blob/main/{row['file_path']}",
    }


def compute_one_bill(conn: sqlite3.Connection, bill_id: str,
                     db_path: str = DEFAULT_DB) -> dict:
    """Compute the same JSON shape the API returned for /bills/{id}/diffs."""
    text_row = conn.execute(
        "SELECT text, text_sha256 FROM bill_texts WHERE bill_id = ?"
        " ORDER BY fetched_at DESC LIMIT 1",
        (bill_id,),
    ).fetchone()
    bill_text = text_row["text"] if text_row else ""
    text_sha = text_row["text_sha256"] if text_row else None

    blocks = parse_bill_amendments(bill_text)

    sections: list[dict] = []

    for block in blocks:
        target = block.target
        encoding = _encoding_for(conn, target)
        prov = fetch_corpus(target, db_path=db_path)
        if prov is None or not prov.body:
            sections.append(_unmatched(target, encoding,
                                       parse_warnings=block.parse_warnings,
                                       operations=block.operations))
            continue

        applied_result = apply_block(block, prov.body, slice_subsection)

        if not prov.is_exact_match:
            slice_text, _offs = slice_subsection(prov.body, target)
            if slice_text:
                # Slice exists; if any op applied, diff slice-vs-applied;
                # otherwise show the subsection as context.
                if applied_result.applied:
                    after = applied_result.after_text or slice_text
                    sections.append(_section_payload(
                        target, encoding, prov,
                        before=slice_text, after=after,
                        applied=applied_result.applied,
                        unapplied=applied_result.unapplied,
                        block_warnings=block.parse_warnings,
                        block_raw=block.raw,
                        sliced=True,
                    ))
                    continue
                sections.append(_section_payload(
                    target, encoding, prov,
                    before=slice_text, after=slice_text,
                    applied=[], unapplied=applied_result.unapplied,
                    block_warnings=block.parse_warnings,
                    block_raw=block.raw,
                    sliced=True,
                ))
                continue
            # Slice not found — show parent body.
            sections.append(_section_payload(
                target, encoding, prov,
                before=prov.body, after=prov.body,
                applied=[], unapplied=applied_result.unapplied,
                block_warnings=block.parse_warnings,
                block_raw=block.raw,
                sliced=False,
            ))
            continue

        # Exact match: corpus body IS the target.
        after = applied_result.after_text or prov.body
        sections.append(_section_payload(
            target, encoding, prov,
            before=prov.body, after=after,
            applied=applied_result.applied,
            unapplied=applied_result.unapplied,
            block_warnings=block.parse_warnings,
            block_raw=block.raw,
            sliced=False,
            exact_match=True,
        ))

    # NOTE: we used to render encoded-citation-only sections here as
    # "context" for every encoding the bill cited (without amending). But
    # a mere cross-reference doesn't force a re-encode, so surfacing it
    # produced false 'touches rulespec' signals (cf. H.R.1865 → §26 USC
    # 152). The strict policy: only emit sections where the parser
    # actually targeted the citation with an amendment block.

    return {"sections": sections, "source_text_sha256": text_sha}


def _section_payload(target: str, encoding: dict | None, prov, *,
                     before: str, after: str,
                     applied: list, unapplied: list,
                     block_warnings: list, block_raw: str,
                     sliced: bool, exact_match: bool = False) -> dict:
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
        "axiom_url": f"{AXIOM_APP_URL}/{prov.citation_path}",
        "source_url": prov.source_url,
    }


def _unmatched(citation: str, encoding: dict | None, *,
               parse_warnings: list | None = None,
               operations: list | None = None) -> dict:
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
        # bill_list_summary view: a match needs >=1 APPLIED op.
        touches_rulespec = any(
            s["encoding"] and s["applied_ops"] for s in payload["sections"]
        )
        touches_corpus = any(
            s["in_corpus"] and s.get("citation_path") and s["applied_ops"]
            for s in payload["sections"]
        )
        conn.execute(
            "UPDATE bills SET diffs = ?, touches_corpus = ?,"
            " touches_rulespec = ? WHERE id = ?",
            (json.dumps(payload), int(touches_corpus),
             int(touches_rulespec), bill_id),
        )
    conn.close()
    return counts
