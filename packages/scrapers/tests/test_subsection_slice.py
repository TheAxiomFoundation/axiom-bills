"""Subsection slicer — the trickiest piece of the diff pipeline.

If this breaks subtly, all subsection diffs go wrong. So we test the
patterns the user actually sees on real federal bills (§63(b), §68(c),
§213(a)).
"""
from __future__ import annotations

from axiom_bills._common.amendments import slice_subsection, stitch_subsection


CORPUS_213 = (
    "(a) Allowance of deduction There shall be allowed as a deduction "
    "the expenses paid during the taxable year, not compensated for by "
    "insurance or otherwise, for medical care of the taxpayer, his "
    "spouse, or a dependent (as defined in section 152, determined "
    "without regard to subsections (b)(1), (b)(2), and (d)(1)(B) thereof).\n\n"
    "(b) Limitation with respect to medicine and drugs An amount paid "
    "during the taxable year for medicine or a drug shall be taken into "
    "account under subsection (a) only if such medicine or drug is a "
    "prescribed drug.\n\n"
    "(c) Special rule for decedents (1) Treatment of expenses paid "
    "after death For purposes of subsection (a), expenses for the medical "
    "care of the taxpayer which are paid out of his estate.\n\n"
    "(d) Definitions (1) The term \"medical care\" means amounts paid (A) "
    "for diagnosis, (B) for transportation. (2) Amounts paid for lodging "
    "shall not exceed $50 for each night. (3) Prescribed drug means a "
    "drug requiring a prescription.\n\n"
    "(e) Exclusion of amounts allowed for care of certain dependents Any "
    "expense allowed as a credit under section 21 shall not be treated "
    "as medical care."
)


def test_slice_simple_subsection():
    slice_text, offsets = slice_subsection(CORPUS_213, "26 USC 213(a)")
    assert slice_text is not None
    assert offsets is not None
    assert slice_text.startswith("(a) Allowance of deduction")
    # Should NOT include (b) or later
    assert "(b) Limitation" not in slice_text


def test_slice_doesnt_grab_cross_ref():
    # subsections (b)(1) inside (a)'s prose is a cross-ref, not a slice boundary
    slice_text, _ = slice_subsection(CORPUS_213, "26 USC 213(a)")
    # (a) contains a cross-ref to (b)(1) — should remain inside (a)
    assert "subsections (b)(1)" in slice_text


def test_slice_subsection_with_paragraph():
    slice_text, offsets = slice_subsection(CORPUS_213, "26 USC 213(d)(2)")
    assert slice_text is not None
    assert "lodging" in slice_text
    assert "$50 for each night" in slice_text
    # Should NOT cross into (d)(3)
    assert "Prescribed drug means" not in slice_text


def test_slice_missing_returns_none():
    slice_text, offsets = slice_subsection(CORPUS_213, "26 USC 213(z)")
    assert slice_text is None
    assert offsets is None


def test_stitch_roundtrip():
    slice_text, offsets = slice_subsection(CORPUS_213, "26 USC 213(b)")
    assert slice_text is not None and offsets is not None
    rebuilt = stitch_subsection(CORPUS_213, offsets, slice_text)
    assert rebuilt == CORPUS_213


def test_stitch_with_modification():
    slice_text, offsets = slice_subsection(CORPUS_213, "26 USC 213(b)")
    modified = slice_text.replace("prescribed drug", "regulated medication")
    rebuilt = stitch_subsection(CORPUS_213, offsets, modified)
    assert "regulated medication" in rebuilt
    # other subsections untouched
    assert "(a) Allowance of deduction" in rebuilt
    assert "(c) Special rule for decedents" in rebuilt
