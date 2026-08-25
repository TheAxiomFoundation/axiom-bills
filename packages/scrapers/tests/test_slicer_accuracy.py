"""Accuracy test for ``slice_subsection`` against axiom-corpus ground truth.

The other slicer tests assert behaviour on hand-written examples. This one
scores it against reality: corpus stores every provision as its own row,
so for a section body and a descendant citation the correct slice is a
recorded fact. The fixture pairs each section with its descendants'
actual text.

Why this exists as a test rather than a one-off script: while fixing the
cross-reference shield, a change that was correct on every synthetic
example regressed four real sections. Nothing in the hand-written suite
noticed. The thresholds below are the tripwire.

Three outcome classes, and they are not equally bad:

  correct — the slice contains the descendant's real text
  MISS    — returns None. Honest: callers fall back and say so.
  WRONG   — returns a slice of the wrong provision. This is the
            dangerous one. An amendment applied inside a wrong slice
            edits a provision the bill never named, and the payload
            still reports it cleanly applied.

So WRONG carries a hard ceiling, while `correct` carries a floor. Both
are deliberately set at the measured values with a little slack: a real
improvement should fail this test and prompt you to raise the floor.

Regenerate the fixture with:
    python packages/scrapers/tests/fixtures/refresh_slicer_cases.py
"""
from __future__ import annotations

import gzip
import json
import pathlib
import re

import pytest

from axiom_bills._common.amendments import slice_subsection

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "slicer_cases.json.gz"

# The fixture is deliberately failure-enriched: refresh_slicer_cases.py
# kept every sampled section that had at least one failing case when it
# was generated, so the sections that were hard are over-represented on
# purpose. That made the rates pessimistic; now that nearly all of them
# resolve, the sample is close to the population.
#
# Measured at the time of writing (1816 cases):
#   overall     99.78% correct, 0.11% wrong, 0.11% miss
#   subsection  99.81% correct
#   paragraph   99.77% correct
#
# The four residual failures are believed irreducible by lexical rules:
# three are comma-joined chains whose label classes match, so nothing in
# the text distinguishes "another reference" from "the next structural
# marker" ("...under paragraph (1), and (3) in any other case"); the
# fourth is a section that genuinely carries two subsections designated
# (e), as an editorial note in the statute itself points out.
#
# Floors sit just under those. Update them when a change legitimately
# moves the numbers — and say which change, in the commit message.
MIN_CORRECT_OVERALL = 0.99
MAX_WRONG_OVERALL = 0.002
MIN_CORRECT_SUBSECTION = 0.99
MIN_CORRECT_PARAGRAPH = 0.99

# Sections a specific bug turned on. The fixture must never lose them,
# whatever a future refresh samples.
SENTINELS = ("us/statute/26/63", "us/statute/26/170")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


@pytest.fixture(scope="module")
def corpus_cases_full():
    if not FIXTURE.exists():           # pragma: no cover - fixture is committed
        pytest.skip(f"missing fixture: {FIXTURE}")
    return json.loads(gzip.decompress(FIXTURE.read_bytes()).decode())


@pytest.fixture(scope="module")
def corpus_cases(corpus_cases_full):
    return corpus_cases_full["sections"], corpus_cases_full["cases"]


def _score(sections, cases):
    correct = wrong = miss = 0
    failures = []
    for c in cases:
        body = sections[c["s"]]
        got, offsets = slice_subsection(body, c["cit"])
        if got is None:
            miss += 1
            failures.append(("MISS", c["cit"]))
        elif c["want"][:60] in _norm(got):
            correct += 1
        else:
            wrong += 1
            failures.append(("WRONG", c["cit"]))
    return correct, wrong, miss, failures


def test_no_case_that_worked_stops_working(corpus_cases):
    """The precise tripwire.

    Aggregate thresholds cannot see a small regression — during the
    reference-shield work a change broke four real sections while every
    rate stayed inside its floor. Each case carries the outcome it had
    when the fixture was generated; anything recorded ``ok`` must stay
    ok, however the totals move.

    Improvements are allowed silently: a case pinned ``miss`` that starts
    resolving is a win, and regenerating the fixture (which needs corpus
    access) then tightens the pin.
    """
    sections, cases = corpus_cases
    broke = []
    for c in cases:
        if c.get("expect") != "ok":
            continue
        got, _ = slice_subsection(sections[c["s"]], c["cit"])
        if got is None:
            broke.append(f"{c['cit']} ok -> MISS")
        elif c["want"][:60] not in _norm(got):
            broke.append(f"{c['cit']} ok -> WRONG")
    assert not broke, (
        f"{len(broke)} slices that used to be correct no longer are:\n  "
        + "\n  ".join(broke[:25])
    )


def test_no_new_silently_misscoped_slices(corpus_cases):
    """A case turning WRONG is worse than one turning MISS: the applier
    edits inside the wrong provision and still reports success. The set
    of wrong citations must not grow."""
    sections, cases = corpus_cases
    known = {c["cit"] for c in cases if c.get("expect") == "wrong"}
    new_wrong = []
    for c in cases:
        got, _ = slice_subsection(sections[c["s"]], c["cit"])
        if got is None or c["want"][:60] in _norm(got):
            continue
        if c["cit"] not in known:
            new_wrong.append(c["cit"])
    assert not new_wrong, (
        "new silently mis-scoped slices — these edit provisions the bill "
        f"never named:\n  " + "\n  ".join(new_wrong[:25])
    )


def test_fixture_is_usable(corpus_cases):
    sections, cases = corpus_cases
    assert len(sections) >= 40, "fixture shrank — regenerate it"
    assert len(cases) >= 300, "fixture shrank — regenerate it"
    assert {c["tier"] for c in cases} == {"subsection", "paragraph"}
    for c in cases:
        assert c["want"], c["cit"]
        assert 0 <= c["s"] < len(sections)
        assert c.get("expect") in {"ok", "miss", "wrong"}, c["cit"]


def test_sentinel_sections_are_present(corpus_cases_full):
    """26 USC 63 carries the over-shield case (paragraph markers abutting
    citations) and 26 USC 170 the prose-parenthetical one. Both are large
    enough that a size-based refresh would drop them, and dropping either
    silently removes the coverage that caught a real regression."""
    paths = set(corpus_cases_full.get("section_paths") or [])
    missing = [s for s in SENTINELS if s not in paths]
    assert not missing, (
        f"sentinel sections missing from the fixture: {missing} — "
        "refresh_slicer_cases.py should always keep them"
    )


def test_overall_accuracy_against_corpus(corpus_cases):
    sections, cases = corpus_cases
    correct, wrong, miss, failures = _score(sections, cases)
    total = len(cases)
    report = (
        f"\n  cases   {total}"
        f"\n  correct {correct} ({correct / total:.2%})"
        f"\n  WRONG   {wrong} ({wrong / total:.2%})"
        f"\n  MISS    {miss} ({miss / total:.2%})"
    )
    assert correct / total >= MIN_CORRECT_OVERALL, (
        f"slicer accuracy dropped below {MIN_CORRECT_OVERALL:.0%}{report}"
    )
    assert wrong / total <= MAX_WRONG_OVERALL, (
        f"silently mis-scoped slices rose above {MAX_WRONG_OVERALL:.1%}"
        f" — these edit provisions the bill never named{report}"
    )


@pytest.mark.parametrize("tier,floor", [
    ("subsection", MIN_CORRECT_SUBSECTION),
    ("paragraph", MIN_CORRECT_PARAGRAPH),
])
def test_accuracy_per_depth(corpus_cases, tier, floor):
    """Paragraph targets are the harder tier and the one amendments most
    often name, so it gets its own floor rather than hiding inside the
    overall average."""
    sections, cases = corpus_cases
    tier_cases = [c for c in cases if c["tier"] == tier]
    assert tier_cases, tier
    correct, wrong, miss, _ = _score(sections, tier_cases)
    ratio = correct / len(tier_cases)
    assert ratio >= floor, (
        f"{tier} accuracy {ratio:.2%} below {floor:.0%} "
        f"({correct} correct / {wrong} wrong / {miss} miss "
        f"of {len(tier_cases)})"
    )


def test_a_correct_slice_reports_usable_offsets(corpus_cases):
    """Callers stitch amended text back with the returned offsets, so a
    slice that reports the wrong span corrupts the section even when the
    text it returned was right."""
    sections, cases = corpus_cases
    checked = 0
    for c in cases:
        body = sections[c["s"]]
        got, offsets = slice_subsection(body, c["cit"])
        if got is None or c["want"][:60] not in _norm(got):
            continue
        assert offsets is not None, c["cit"]
        start, end = offsets
        assert 0 <= start < end <= len(body), (c["cit"], offsets)
        assert body[start:end] == got, c["cit"]
        checked += 1
    assert checked >= 1000, f"only {checked} correct slices to check"
