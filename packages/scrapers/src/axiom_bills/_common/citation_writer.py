"""Citation extraction pass over existing bills.

Called by `axiom-bills extract-citations`. Reads bills.summary and
bill_texts.text, runs the per-jurisdiction extractor, and upserts into
bill_citations. Sources are recorded so we can later see what fraction
of citations came from summaries vs full text.
"""
from __future__ import annotations

import uuid
from typing import Callable

from .db import connect, DEFAULT_DB


def extract_for_jurisdiction(
    jurisdiction: str,
    extractor: Callable[[str], list[tuple[str, str]]],
    db_path: str = DEFAULT_DB,
) -> dict[str, int]:
    counts = {"bills": 0, "summary_hits": 0, "text_hits": 0, "rows_written": 0}
    with connect(db_path) as conn:
        bills = conn.execute(
            "SELECT id, title, summary FROM bills WHERE jurisdiction = ?",
            (jurisdiction,),
        ).fetchall()

        for bill in bills:
            counts["bills"] += 1
            bill_id = bill["id"]
            extracted: list[tuple[str, str, str]] = []  # (raw, citation, source)

            for raw, citation in extractor(bill["title"] or ""):
                extracted.append((raw, citation, "title"))
            for raw, citation in extractor(bill["summary"] or ""):
                extracted.append((raw, citation, "summary"))
            counts["summary_hits"] += sum(
                1 for x in extracted if x[2] in ("title", "summary")
            )

            texts = conn.execute(
                "SELECT text FROM bill_texts WHERE bill_id = ?",
                (bill_id,),
            ).fetchall()
            for row in texts:
                for raw, citation in extractor(row["text"]):
                    extracted.append((raw, citation, "text"))
                    counts["text_hits"] += 1

            # Replace this bill's citations atomically.
            conn.execute("DELETE FROM bill_citations WHERE bill_id = ?", (bill_id,))
            seen: set[tuple[str, str]] = set()
            for raw, citation, source in extracted:
                key = (citation, source)
                if key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    """
                    INSERT INTO bill_citations (id, bill_id, raw, citation, source)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, bill_id, raw, citation, source),
                )
                counts["rows_written"] += 1
    return counts
