"""Read axiom-corpus current_provisions from Supabase.

Anon access is granted via the `corpus` schema profile. We expose:

* `citation_to_path('26 USC 213(a)')` → 'us/statute/26/213(a)'
* `fetch('26 USC 213')` → CorpusProvision dataclass, hits Supabase if not
  already cached locally, caches the result.

Caching matters: every bill detail view hits this for every cited
section, and the data only changes when axiom-corpus does a new release.
A `--force` knob (and a CLI command to clear) is wired through.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass

import httpx

from .db import connect, DEFAULT_DB


SUPABASE_URL = os.environ.get(
    "AXIOM_CORPUS_SUPABASE_URL",
    "https://swocpijqqahhuwtuahwc.supabase.co",
)
SUPABASE_KEY = os.environ.get(
    "AXIOM_CORPUS_SUPABASE_KEY",
    # Same anon key used by axiom-foundation.org. Read-only via the corpus
    # schema profile; safe to commit. Override via env if needed.
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN3b2NwaWpxcWFoaHV3dHVhaHdjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzczMzU3NzcsImV4cCI6MjA5MjkxMTc3N30.spiF6Z6LLJmETL8eI0z_QbwgXce7J5CIqHTiXZ6K9Zk",
)


@dataclass
class CorpusProvision:
    citation_path: str
    citation: str
    jurisdiction: str
    doc_type: str
    heading: str | None
    body: str | None
    effective_date: str | None
    source_url: str | None
    has_rulespec: bool
    # True when this is the exact citation_path the bill targets; False
    # when we fell back to an ancestor (corpus didn't have the subsection).
    is_exact_match: bool = True


# 'us/statute/26/213(a)(1)' is the canonical Axiom citation_path. Our
# extracted citation is '26 USC 213(a)(1)'. Map back and forth.
USC_CITATION_RE = re.compile(
    # Section identifier allows lowercase or uppercase letters (up to 3)
    # and an optional hyphenated suffix — corpus stores rows for
    # `2 USC 168a`, `42 USC 300hh-14`, etc. The amendment-block
    # parser produces these forms; the path normalizer must match.
    r"^(?P<title>\d+)\s+USC\s+"
    r"(?P<section>\d+[a-zA-Z]{0,3}(?:-\d+[a-zA-Z]{0,3})?)"
    r"(?P<sub>(?:\([^)]+\))*)$"
)
CFR_CITATION_RE = re.compile(
    r"^(?P<title>\d+)\s+CFR\s+(?P<part>\d+)\.(?P<section>\d+[a-zA-Z]{0,3})"
    r"(?P<sub>(?:\([^)]+\))*)$"
)


def citation_to_path(citation: str) -> str | None:
    """Normalized citation → Axiom citation_path. Returns None if unmappable.

    Axiom corpus stores nested levels as separate path segments — each
    `(X)` in the citation becomes `/X` in the path. So
        '26 USC 213'         → 'us/statute/26/213'
        '26 USC 213(a)'      → 'us/statute/26/213/a'
        '26 USC 213(a)(1)'   → 'us/statute/26/213/a/1'
        '7 CFR 273.3(b)(2)'  → 'us/regulation/7/273.3/b/2'
    Earlier versions kept the parens inline, which never matched corpus.
    """
    m = USC_CITATION_RE.match(citation)
    if m:
        title = m.group("title")
        section = m.group("section")
        subs = re.findall(r"\(([^)]+)\)", m.group("sub") or "")
        parts = [title, section, *subs]
        return "us/statute/" + "/".join(parts)
    m = CFR_CITATION_RE.match(citation)
    if m:
        title = m.group("title")
        part = m.group("part")
        section = m.group("section")
        subs = re.findall(r"\(([^)]+)\)", m.group("sub") or "")
        head = f"us/regulation/{title}/{part}.{section}"
        return head + ("/" + "/".join(subs) if subs else "")
    return None


def _row_to_provision(row: sqlite3.Row | dict) -> CorpusProvision:
    return CorpusProvision(
        citation_path=row["citation_path"],
        citation=row["citation"] if "citation" in row.keys() else "",
        jurisdiction=row["jurisdiction"],
        doc_type=row["doc_type"],
        heading=row["heading"],
        body=row["body"],
        effective_date=row["effective_date"],
        source_url=row["source_url"],
        has_rulespec=bool(row["has_rulespec"]),
    )


def _cached(citation_path: str, db_path: str = DEFAULT_DB) -> CorpusProvision | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM corpus_provisions WHERE citation_path = ?",
            (citation_path,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_provision(row)


def _fetch_supabase(citation_path: str) -> CorpusProvision | None:
    """Hit the `current_provisions` view in the corpus schema."""
    url = f"{SUPABASE_URL}/rest/v1/current_provisions"
    params = {
        "citation_path": f"eq.{citation_path}",
        "select": "citation_path,jurisdiction,doc_type,heading,body,effective_date,source_url,has_rulespec",
    }
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept-Profile": "corpus",
    }
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=10.0)
    except httpx.RequestError:
        return None
    if response.status_code != 200:
        return None
    rows = response.json()
    if not rows:
        return None
    row = rows[0]
    return CorpusProvision(
        citation_path=row["citation_path"],
        citation="",   # filled in by caller before caching
        jurisdiction=row["jurisdiction"],
        doc_type=row["doc_type"],
        heading=row.get("heading"),
        body=row.get("body"),
        effective_date=row.get("effective_date"),
        source_url=row.get("source_url"),
        has_rulespec=bool(row.get("has_rulespec")),
    )


def _parent_paths(path: str) -> list[str]:
    """Generate ancestor citation_paths to fall back to.

    `us/statute/26/3121/a/1` → ['us/statute/26/3121/a', 'us/statute/26/3121'].
    The corpus often stores text at the section level only; a bill citing
    a deeper sub-element still wants the surrounding section's body.
    """
    # us/<doc_type>/<title>/<section>[/...sub] — first 4 segments are fixed.
    segments = path.split("/")
    if len(segments) <= 4:
        return []
    out: list[str] = []
    for i in range(len(segments) - 1, 3, -1):
        out.append("/".join(segments[:i]))
    return out


def fetch(citation: str, *, force: bool = False,
          db_path: str = DEFAULT_DB) -> CorpusProvision | None:
    """Fetch a corpus provision for a normalized citation; cache on hit.

    Falls back to ancestor citation_paths when the exact one isn't in
    corpus — corpus often stores body text at section granularity even
    when our bill cites a subsection.
    """
    path = citation_to_path(citation)
    if path is None:
        return None

    candidates = [path, *_parent_paths(path)]
    for try_path in candidates:
        is_exact = try_path == path
        if not force:
            cached = _cached(try_path, db_path=db_path)
            if cached is not None:
                cached.is_exact_match = is_exact
                return cached
        fresh = _fetch_supabase(try_path)
        if fresh is None:
            continue
        fresh.citation = citation
        fresh.is_exact_match = is_exact
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO corpus_provisions
                  (citation_path, citation, jurisdiction, doc_type, heading,
                   body, effective_date, source_url, has_rulespec, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    fresh.citation_path,
                    fresh.citation,
                    fresh.jurisdiction,
                    fresh.doc_type,
                    fresh.heading,
                    fresh.body,
                    fresh.effective_date,
                    fresh.source_url,
                    1 if fresh.has_rulespec else 0,
                ),
            )
        return fresh
    return None


def fetch_for_bill_citations(bill_id: str, db_path: str = DEFAULT_DB) -> list[CorpusProvision]:
    """Fetch all corpus provisions for a bill's citations."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT citation FROM bill_citations WHERE bill_id = ?",
            (bill_id,),
        ).fetchall()
    finally:
        conn.close()
    out: list[CorpusProvision] = []
    for row in rows:
        prov = fetch(row["citation"], db_path=db_path)
        if prov is not None:
            out.append(prov)
    return out
