#!/usr/bin/env python3
"""Regenerate the slicer accuracy fixture from axiom-corpus.

axiom-corpus stores every provision as its own row, so for a section
body and a descendant citation the correct slice is a recorded fact
rather than a judgement call. That makes it possible to score
``slice_subsection`` against ground truth instead of against hand-written
examples, which is what caught a mid-review regression that looked fine
on synthetic input.

Run this when corpus ships a release that changes the sampled sections,
or to widen coverage:

    python packages/scrapers/tests/fixtures/refresh_slicer_cases.py

Then re-run ``test_slicer_accuracy.py`` and update the thresholds it
asserts if the numbers legitimately moved.

Selection: we keep sections that earn their bytes — ones exercising the
reference-shield edge cases, ones with at least one current failure
(regression sentinels), and a fill of small sections so the accuracy
denominator stays representative. The very large sections are dropped:
they add hundreds of KB without adding failure modes.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import re
import sys
import time

import httpx

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from axiom_bills._common.corpus_client import (  # noqa: E402
    SUPABASE_KEY,
    SUPABASE_URL,
)

OUT = HERE / "slicer_cases.json.gz"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Accept-Profile": "corpus",
}

# Sections to sample before curation. Corpus paging (offset / Range) is
# unreliable on this view, so we take one ordered page.
SECTION_SAMPLE = 260

# A section body larger than this is dropped: the giants cost hundreds of
# KB and repeat failure modes the smaller ones already cover.
MAX_SECTION_KB = 14
SMALL_SECTION_KB = 4
SMALL_SECTION_FILL = 70

# Sections kept no matter their size, because a specific bug turned on
# them and the test should never lose that coverage:
#   26 USC 63  — paragraph markers abutting citations ("section 199A, (4)"),
#                the over-shield case; 3 of 7 paragraphs resolved before.
#   26 USC 170 — "section 152 (determined without regard to subsections
#                (b)(1), ...)", the prose-parenthetical case.
SENTINEL_PATHS = ("us/statute/26/63", "us/statute/26/170")

# "section 199A, (4)" / "section 170(p), (5)" — a citation immediately
# followed by a structural marker, the shape the reference shield used to
# swallow. Sections containing it are always kept.
TRICKY_RE = re.compile(
    r"\b(?:section|sections)\s+\d+[A-Za-z]?\s*(?:\([0-9A-Za-z]{1,4}\))?\s*,\s*\("
)


def _get(**params) -> list[dict]:
    for attempt in range(4):
        try:
            r = httpx.get(
                f"{SUPABASE_URL}/rest/v1/current_provisions",
                params=params, headers=HEADERS, timeout=60.0,
            )
            if r.status_code == 200:
                return r.json()
        except httpx.RequestError:
            pass
        time.sleep(1.5 * (attempt + 1))
    return []


def _citation(path: str) -> str | None:
    """'us/statute/26/63/b/6' -> '26 USC 63(b)(6)'."""
    seg = path.split("/")
    if len(seg) < 4 or seg[1] != "statute":
        return None
    title, section, *subs = seg[2:]
    return f"{title} USC {section}" + "".join(f"({s})" for s in subs)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def collect() -> tuple[list[str], list[dict]]:
    sections = [
        s for s in _get(
            level="eq.1", doc_type="eq.statute", jurisdiction="eq.us",
            select="id,citation_path,body", order="citation_path",
            limit=str(SECTION_SAMPLE),
        )
        if s.get("body")
    ]
    print(f"fetched {len(sections)} sections", flush=True)

    bodies: list[str] = []
    paths: list[str] = []
    index: dict[str, int] = {}
    cases: list[dict] = []

    have = {s["citation_path"] for s in sections}
    for want in SENTINEL_PATHS:
        if want not in have:
            extra = _get(citation_path=f"eq.{want}",
                         select="id,citation_path,body")
            if extra and extra[0].get("body"):
                sections.append(extra[0])
                print(f"  + sentinel {want}", flush=True)

    for n, sec in enumerate(sections):
        flat_parent = _norm(sec["body"])
        subs = _get(parent_id=f"eq.{sec['id']}",
                    select="id,citation_path,body", order="ordinal")
        # Grandchildren for all subsections in one request.
        grand: list[dict] = []
        if subs:
            ids = ",".join(s["id"] for s in subs)
            grand = _get(parent_id=f"in.({ids})",
                         select="citation_path,body", order="ordinal")

        for tier, rows in (("subsection", subs), ("paragraph", grand)):
            for row in rows:
                cit = _citation(row["citation_path"])
                want = _norm(row.get("body"))
                if not cit or not want:
                    continue
                # Only meaningful when the descendant's text is actually
                # inside the section body — otherwise the section isn't a
                # flowing render and there is nothing to slice.
                if want[:40] not in flat_parent:
                    continue
                if sec["body"] not in index:
                    index[sec["body"]] = len(bodies)
                    bodies.append(sec["body"])
                    paths.append(sec["citation_path"])
                cases.append({
                    "s": index[sec["body"]],
                    "cit": cit,
                    "want": want[:80],
                    "tier": tier,
                })
        if n % 25 == 0:
            print(f"  {n}/{len(sections)} -> {len(cases)} cases", flush=True)

    return bodies, paths, cases


def curate(bodies: list[str], paths: list[str],
           cases: list[dict]) -> tuple[list[str], list[str], list[dict]]:
    """Keep the sections that carry signal per byte."""
    from axiom_bills._common.amendments import slice_subsection

    per_section: dict[int, list[dict]] = {}
    for c in cases:
        per_section.setdefault(c["s"], []).append(c)

    keep: set[int] = set()
    fill: list[tuple[int, int]] = []
    for i, body in enumerate(bodies):
        kb = len(body) / 1024
        if paths[i] in SENTINEL_PATHS:
            keep.add(i)
            continue
        if kb > MAX_SECTION_KB:
            continue
        mine = per_section.get(i, [])
        fails = 0
        for c in mine:
            got, _ = slice_subsection(body, c["cit"])
            # Pin the outcome as of generation. The test asserts that no
            # case recorded "ok" ever stops being ok — an aggregate
            # threshold cannot see a three-case regression, and a
            # three-case regression is exactly what slipped through once.
            if got is None:
                c["expect"] = "miss"
            elif c["want"][:60] in _norm(got):
                c["expect"] = "ok"
            else:
                c["expect"] = "wrong"
            if c["expect"] != "ok":
                fails += 1
        if fails or TRICKY_RE.search(body):
            keep.add(i)
        elif kb <= SMALL_SECTION_KB and len(mine) >= 3:
            fill.append((i, len(mine)))

    for i, _ in sorted(fill, key=lambda x: -x[1])[:SMALL_SECTION_FILL]:
        keep.add(i)

    # Sentinels skip the failure scan above, so pin their cases here.
    for i in keep:
        if paths[i] not in SENTINEL_PATHS:
            continue
        for c in per_section.get(i, []):
            got, _ = slice_subsection(bodies[i], c["cit"])
            c["expect"] = ("miss" if got is None
                           else "ok" if c["want"][:60] in _norm(got)
                           else "wrong")

    remap = {old: new for new, old in enumerate(sorted(keep))}
    out_bodies = [bodies[old] for old in sorted(keep)]
    out_paths = [paths[old] for old in sorted(keep)]
    out_cases = [{**c, "s": remap[c["s"]]} for c in cases if c["s"] in remap]
    return out_bodies, out_paths, out_cases


def main() -> None:
    bodies, paths, cases = collect()
    bodies, paths, cases = curate(bodies, paths, cases)
    fixture = {
        "description": (
            "Slicer accuracy cases derived from axiom-corpus. Corpus stores "
            "each provision as its own row, so for a section body and a "
            "descendant citation the correct slice is a recorded fact. "
            "'want' is the first 80 normalized characters of the "
            "descendant's own corpus body; a slice is correct when it "
            "contains that text. 'expect' pins the outcome at generation "
            "time so per-case regressions are caught, not just aggregate "
            "drift."
        ),
        "source": "corpus.current_provisions — us statutes, level 1 "
                  "sections with their level 2 and 3 descendants",
        "regenerate": "python packages/scrapers/tests/fixtures/"
                      "refresh_slicer_cases.py",
        "sections": bodies,
        "section_paths": paths,
        "cases": cases,
    }
    raw = json.dumps(fixture, indent=1)
    OUT.write_bytes(gzip.compress(raw.encode(), mtime=0))
    kb = OUT.stat().st_size / 1024
    tiers = {}
    for c in cases:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    print(f"\nwrote {OUT.relative_to(HERE.parents[3])}")
    print(f"  sections {len(bodies)}, cases {len(cases)} {tiers}")
    print(f"  {len(raw)/1024:.0f} KB raw -> {kb:.0f} KB gzipped")


if __name__ == "__main__":
    main()
