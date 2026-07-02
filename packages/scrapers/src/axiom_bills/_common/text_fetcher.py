"""Download bill_versions and store text for citation extraction.

Format handling:
  * html / xml → strip tags via selectolax, retain text
  * txt        → keep verbatim
  * pdf        → extracted via pypdf. Layout-derived text is noisier
                 than HTML, but for PDF-only sources (several states,
                 the occasional federal version) noisy text beats no
                 text: citations and amendment headers still parse.

We keep one row per (bill, version_label). Re-fetching updates the row
in place when the SHA changes.
"""
from __future__ import annotations

import hashlib
import io
import uuid

from selectolax.parser import HTMLParser

from .db import connect, DEFAULT_DB
from .http import RateLimitedClient
from .version_rank import stage_rank


def _to_text(format_: str, body: bytes) -> str | None:
    fmt = format_.lower()
    if fmt in ("html", "xml"):
        try:
            tree = HTMLParser(body.decode("utf-8", errors="replace"))
        except Exception:
            return None
        text = tree.text(separator=" ").strip()
        return text or None
    if fmt == "txt":
        return body.decode("utf-8", errors="replace")
    if fmt == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception:
            # Encrypted/corrupt/scanned-image PDFs — nothing to extract.
            return None
        text = "\n".join(pages).strip()
        return text or None
    return None


def fetch_for_jurisdiction(
    jurisdiction: str,
    *,
    limit: int | None = None,
    prefer_format: tuple[str, ...] = ("html", "xml", "txt", "pdf"),
    db_path: str = DEFAULT_DB,
) -> dict[str, int]:
    counts = {"bills_seen": 0, "versions_seen": 0, "fetched": 0, "skipped": 0}
    http = RateLimitedClient(min_interval_per_host=0.3)

    try:
        with connect(db_path) as conn:
            # Pick one preferred version per bill so we don't pull all 8
            # textVersions × 4 formats per bill on first pass.
            bills = conn.execute(
                "SELECT id FROM bills WHERE jurisdiction = ?",
                (jurisdiction,),
            ).fetchall()

            for bill in bills:
                if limit is not None and counts["fetched"] >= limit:
                    break
                counts["bills_seen"] += 1
                bill_id = bill["id"]
                versions = conn.execute(
                    """
                    SELECT label, source_url, format
                      FROM bill_versions
                     WHERE bill_id = ?
                    """,
                    (bill_id,),
                ).fetchall()
                if not versions:
                    continue
                counts["versions_seen"] += len(versions)

                # Pick the LATEST legislative stage that has a fetchable
                # format. Iterating "ORDER BY label" picked a version
                # alphabetically — which text the whole diff/variant
                # pipeline ran on was label-spelling luck.
                fmt_pref = {fmt: i for i, fmt in enumerate(prefer_format)}
                fetchable = [
                    v for v in versions
                    if v["format"].lower() in fmt_pref
                ]
                if not fetchable:
                    counts["skipped"] += 1
                    continue
                chosen = min(
                    fetchable,
                    key=lambda v: (-stage_rank(v["label"]),
                                   fmt_pref[v["format"].lower()]),
                )

                try:
                    response = http.get(chosen["source_url"])
                except Exception:
                    counts["skipped"] += 1
                    continue
                if response.status_code != 200:
                    counts["skipped"] += 1
                    continue

                text = _to_text(chosen["format"], response.content)
                if not text:
                    counts["skipped"] += 1
                    continue

                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                existing = conn.execute(
                    "SELECT id, text_sha256 FROM bill_texts WHERE bill_id = ? AND version_label = ?",
                    (bill_id, chosen["label"]),
                ).fetchone()
                if existing:
                    if existing["text_sha256"] != sha:
                        conn.execute(
                            """
                            UPDATE bill_texts
                               SET source_url = ?, format = ?, text = ?,
                                   text_sha256 = ?, fetched_at = datetime('now')
                             WHERE id = ?
                            """,
                            (
                                chosen["source_url"], chosen["format"],
                                text, sha, existing["id"],
                            ),
                        )
                else:
                    conn.execute(
                        """
                        INSERT INTO bill_texts
                          (id, bill_id, version_label, source_url, format,
                           text, text_sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uuid.uuid4().hex, bill_id, chosen["label"],
                            chosen["source_url"], chosen["format"], text, sha,
                        ),
                    )
                counts["fetched"] += 1
    finally:
        http.close()

    return counts
