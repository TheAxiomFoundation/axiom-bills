"""Drive LLM-assisted re-encoding across structural variants.

Reads existing `rule_variants` rows whose `tier ∈ {list, structural}`
and `patched_yaml IS NULL`. For each, gathers the baseline YAML, the
bill's amendment text for the relevant section, and calls
`reencoder_llm.propose_via_anthropic`. Successful proposals are
written to `patched_yaml` with `proposed_by='llm'` so the bill page's
"If enacted" tab can render them like Tier 1 substitutions.

Rejected proposals leave the variant untouched (still "needs human
review") but stamp a note so retries can be selective.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date, datetime
from typing import Any

from .citation_scope import op_affects_encoding
from .db import DEFAULT_DB
from .reencoder_llm import (
    LLMProposal,
    ProposalRejected,
    propose_via_anthropic,
)


def _eff_from(row: sqlite3.Row) -> date:
    raw = row["effective_from"]
    if not raw:
        return date.today()
    try:
        return datetime.fromisoformat(raw.split(" ")[0]).date()
    except ValueError:
        return date.today()


def _bill_op_text_for_section(conn: sqlite3.Connection, bill_id: str,
                              section_citation: str) -> str:
    """Compose a focused excerpt for the LLM: the parsed op text plus
    a small slice of surrounding bill text. We don't dump the whole
    bill because most bills are long and only one section matters."""
    row = conn.execute(
        "SELECT diffs FROM bills WHERE id = ?", (bill_id,),
    ).fetchone()
    if not row or not row["diffs"]:
        return ""
    diffs = json.loads(row["diffs"]) if isinstance(row["diffs"], str) else row["diffs"]
    chunks: list[str] = []
    for section in diffs.get("sections", []):
        if section.get("citation") != section_citation:
            continue
        if section.get("block_raw"):
            chunks.append(section["block_raw"])
        for op in (section.get("applied_ops") or []) + (section.get("unapplied_ops") or []):
            raw = op.get("raw") or ""
            if raw and raw not in chunks:
                chunks.append(raw)
    return "\n---\n".join(chunks)


REJECTED_NOTE_PREFIX = "LLM proposal rejected:"


def propose_for_bill(conn: sqlite3.Connection, bill_id: str, *,
                     limit: int | None = None, dry_run: bool = False,
                     retry_rejected: bool = False) -> dict[str, int]:
    counts = {"considered": 0, "proposed": 0, "rejected": 0, "skipped": 0}
    variant_rows = conn.execute(
        """
        SELECT v.id, v.encoding_id, v.file_path, v.tier, v.baseline_yaml,
               v.effective_from, v.patched_yaml, v.note,
               e.citation AS encoding_citation
          FROM rule_variants v
          LEFT JOIN axiom_encodings e ON e.id = v.encoding_id
         WHERE v.bill_id = ?
           AND v.tier IN ('list', 'structural')
           AND v.baseline_yaml IS NOT NULL
        """, (bill_id,),
    ).fetchall()
    bill_row = conn.execute(
        "SELECT number FROM bills WHERE id = ?", (bill_id,),
    ).fetchone()
    bill_number = bill_row["number"] if bill_row else "unknown"

    # Find which section citation drove each variant by joining via
    # the diffs JSON. A variant can correspond to >1 section (the bill
    # amends multiple subsections of the same file); pick the first
    # one with applied/unapplied ops.
    diffs_row = conn.execute(
        "SELECT diffs FROM bills WHERE id = ?", (bill_id,),
    ).fetchone()
    diffs = json.loads(diffs_row["diffs"]) if diffs_row and diffs_row["diffs"] else None
    if diffs is None:
        return counts

    for v in variant_rows:
        if v["patched_yaml"]:
            counts["skipped"] += 1
            continue
        # A prior run's validator rejected this variant; the inputs
        # haven't changed (precompute-variants clears the note when they
        # do), so re-calling the LLM just re-spends tokens on the same
        # answer. Opt back in with --retry-rejected.
        if (not retry_rejected and v["note"]
                and REJECTED_NOTE_PREFIX in v["note"]):
            counts["skipped"] += 1
            continue
        counts["considered"] += 1

        # Find the diff section that drove this variant. Match on the
        # scope rule (an op in the section affects this variant's
        # encoding citation) — the old exact file_path == rail-encoding
        # comparison permanently stranded variants for ancestor files,
        # because the rail only ever shows one encoding per section.
        target_section = None
        for s in diffs.get("sections", []):
            ops = (s.get("applied_ops") or []) + (s.get("unapplied_ops") or [])
            if not ops:
                continue
            enc = s.get("encoding")
            if enc and enc.get("file_path") == v["file_path"]:
                target_section = s
                break
            if v["encoding_citation"] and any(
                op_affects_encoding(
                    v["encoding_citation"],
                    op.get("target") or s.get("citation", ""),
                    op.get("kind", ""),
                )
                for op in ops
            ):
                target_section = s
                break
        if target_section is None:
            counts["skipped"] += 1
            continue

        bill_op_text = _bill_op_text_for_section(
            conn, bill_id, target_section["citation"],
        )
        if not bill_op_text.strip():
            counts["skipped"] += 1
            continue

        print(f"  → {bill_number}  {v['file_path']}  @  {target_section['citation']}",
              file=sys.stderr, flush=True)
        try:
            proposal = propose_via_anthropic(
                baseline_yaml=v["baseline_yaml"],
                citation=target_section["citation"],
                bill_number=bill_number,
                bill_op_text=bill_op_text,
                effective_from=_eff_from(v),
            )
        except ProposalRejected as exc:
            print(f"     rejected: {exc}", file=sys.stderr, flush=True)
            counts["rejected"] += 1
            if not dry_run:
                conn.execute(
                    "UPDATE rule_variants SET note = ? WHERE id = ?",
                    (f"{REJECTED_NOTE_PREFIX} {exc}", v["id"]),
                )
            continue
        except Exception as exc:  # network / auth / parse errors
            # Transient — note it (distinguishable from a validator
            # rejection) but leave the variant eligible for the next run.
            print(f"     ERROR: {exc}", file=sys.stderr, flush=True)
            counts["rejected"] += 1
            if not dry_run:
                conn.execute(
                    "UPDATE rule_variants SET note = ? WHERE id = ?",
                    (f"LLM proposal error (retriable): {exc}", v["id"]),
                )
            continue

        counts["proposed"] += 1
        if not dry_run:
            conn.execute(
                """
                UPDATE rule_variants
                   SET patched_yaml = ?, proposed_by = 'llm',
                       proposed_model = ?, note = NULL,
                       computed_at = datetime('now')
                 WHERE id = ?
                """,
                (proposal.patched_yaml, proposal.model, v["id"]),
            )
        if limit is not None and counts["proposed"] >= limit:
            return counts

    return counts


def propose_all(db_path: str = DEFAULT_DB, *,
                jurisdiction: str | None = None,
                limit: int | None = None,
                dry_run: bool = False,
                retry_rejected: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    where = "WHERE 1=1"
    params: tuple = ()
    if jurisdiction:
        where += " AND b.jurisdiction = ?"
        params = (jurisdiction,)
    bill_ids = [r["bill_id"] for r in conn.execute(
        f"""
        SELECT DISTINCT v.bill_id
          FROM rule_variants v
          JOIN bills b ON b.id = v.bill_id
          {where}
           AND v.tier IN ('list', 'structural')
           AND v.patched_yaml IS NULL
        """, params,
    ).fetchall()]

    totals: dict[str, int] = {}
    remaining = limit
    for bill_id in bill_ids:
        per_bill_limit = remaining
        counts = propose_for_bill(conn, bill_id, limit=per_bill_limit,
                                  dry_run=dry_run,
                                  retry_rejected=retry_rejected)
        for k, val in counts.items():
            totals[k] = totals.get(k, 0) + val
        if limit is not None:
            remaining = max(0, limit - totals.get("proposed", 0))
            if remaining == 0:
                break
    conn.close()
    return totals
