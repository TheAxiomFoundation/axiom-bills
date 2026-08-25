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
#   overall     99.72% correct, 0.11% wrong, 0.17% miss
#   of the correct slices, 4.91% are over-long
#
# "Correct" here means the slice contains the provision's real text.
# That is not the same as being the right span, which is why over-long
# is tracked separately and has its own ceiling — an earlier version of
# this file scored 99.78% while 14% of its slices ran past their sibling
# boundary, and nothing in the numbers showed it.
#
# The residual failures are believed irreducible by lexical rules.
# Comma-joined chains whose label classes match give the text no way to
# distinguish "another reference" from "the next structural marker"
# ("...under paragraph (1), and (3) in any other case"). Two are
# sections that carry two subsections under the same letter, as
# editorial notes in the statutes themselves point out.
#
# Floors sit just under the measurements. Update them when a change
# legitimately moves the numbers — and say which change, in the commit.
MIN_CORRECT_OVERALL = 0.99
MAX_WRONG_OVERALL = 0.002
MIN_CORRECT_SUBSECTION = 0.99
MIN_CORRECT_PARAGRAPH = 0.99
MAX_OVER_LONG = 0.06

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


def _by_section(cases):
    grouped = {}
    for c in cases:
        grouped.setdefault(c["s"], []).append(c)
    return grouped


def _outcome(sections, case, siblings):
    """One of ok / over / wrong / miss.

    "over" is a slice that contains the right text but runs past its
    sibling boundary. It has to be its own class: a containment check
    scores it correct, which is how 14% of slices came to over-run while
    the headline accuracy went up.
    """
    got, _ = slice_subsection(sections[case["s"]], case["cit"])
    if got is None:
        return "miss"
    flat = _norm(got)
    if case["want"][:60] not in flat:
        return "wrong"
    for other in siblings:
        if (other["cit"] != case["cit"]
                and other["tier"] == case["tier"]
                and other["want"][:60] in flat):
            return "over"
    return "ok"


def _score(sections, cases):
    grouped = _by_section(cases)
    tally = {"ok": 0, "over": 0, "wrong": 0, "miss": 0}
    for c in cases:
        tally[_outcome(sections, c, grouped[c["s"]])] += 1
    return tally


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
    grouped = _by_section(cases)
    # A case pinned tight must stay tight; one pinned over-long may
    # tighten but must not degrade further.
    allowed = {"ok": {"ok"}, "over": {"ok", "over"}}
    broke = []
    for c in cases:
        permitted = allowed.get(c.get("expect"))
        if permitted is None:
            continue
        now = _outcome(sections, c, grouped[c["s"]])
        if now not in permitted:
            broke.append(f"{c['cit']} {c['expect']} -> {now.upper()}")
    assert not broke, (
        f"{len(broke)} slices that used to be correct no longer are:\n  "
        + "\n  ".join(broke[:25])
    )


def test_no_new_silently_misscoped_slices(corpus_cases):
    """A case turning WRONG is worse than one turning MISS: the applier
    edits inside the wrong provision and still reports success. The set
    of wrong citations must not grow."""
    sections, cases = corpus_cases
    grouped = _by_section(cases)
    known = {c["cit"] for c in cases if c.get("expect") == "wrong"}
    new_wrong = [
        c["cit"] for c in cases
        if _outcome(sections, c, grouped[c["s"]]) == "wrong"
        and c["cit"] not in known
    ]
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
        assert c.get("expect") in {"ok", "over", "miss", "wrong"}, c["cit"]


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


def test_slices_are_tight_not_merely_containing(corpus_cases):
    """A slice that runs past its sibling boundary is a real defect: an
    amendment applied inside it can edit the swallowed sibling. Because
    containment scores it correct, it needs its own ceiling."""
    sections, cases = corpus_cases
    tally = _score(sections, cases)
    found = tally["ok"] + tally["over"]
    ratio = tally["over"] / found
    assert ratio <= MAX_OVER_LONG, (
        f"over-long slices rose to {ratio:.2%} (ceiling {MAX_OVER_LONG:.0%}) "
        f"— {tally['over']} of {found} contain a sibling's text"
    )


def test_overall_accuracy_against_corpus(corpus_cases):
    sections, cases = corpus_cases
    tally = _score(sections, cases)
    total = len(cases)
    correct = tally["ok"] + tally["over"]
    wrong, miss = tally["wrong"], tally["miss"]
    report = (
        f"\n  cases   {total}"
        f"\n  correct {correct} ({correct / total:.2%})"
        f"\n    of which over-long {tally['over']}"
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
    tally = _score(sections, tier_cases)
    correct = tally["ok"] + tally["over"]
    ratio = correct / len(tier_cases)
    assert ratio >= floor, (
        f"{tier} accuracy {ratio:.2%} below {floor:.0%} "
        f"({correct} correct / {tally['wrong']} wrong / "
        f"{tally['miss']} miss of {len(tier_cases)})"
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
