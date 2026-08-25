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


# ────────────────────────────────────────────────────────────────────
#  Cross-reference shield boundaries
#
#  The shield stops a cross-reference ("subsection (a)") from reading as
#  a structural break. Over-reach costs the opposite: corpus renders a
#  subsection as one flowing line, so a genuine paragraph marker often
#  sits right after a citation — "…provided in section 199A, (4) the
#  deduction…". Swallowing that "(4)" hid the paragraph from the
#  structure scan entirely.
# ────────────────────────────────────────────────────────────────────

from axiom_bills._common.amendments import _PROTECTED_REF_RE  # noqa: E402


def _shielded(text):
    return [m.group(0) for m in _PROTECTED_REF_RE.finditer(text)]


def test_bare_number_does_not_chain_into_a_structural_marker():
    assert _shielded(
        "any deduction provided in section 199A, (4) the deduction"
    ) == ["section 199A"]


def test_attached_paren_does_not_comma_chain_into_a_marker():
    """"section 170(p), (5)" is a reference followed by paragraph (5) —
    only and/or joins a genuine multi-subsection reference."""
    assert _shielded("the deduction provided in section 170(p), (5) the") \
        == ["section 170(p)"]


def test_conjunction_still_chains_after_a_section_number():
    assert _shielded("as described in section 151(b) and (c) of such Code") \
        == ["section 151(b) and (c)"]


def test_paren_headed_lists_shield_whole_including_oxford_tail():
    assert _shielded("subsections (b)(1), (b)(2), and (d)(1)(B) thereof") \
        == ["subsections (b)(1), (b)(2), and (d)(1)(B)"]
    assert _shielded("by striking clauses (i), (iii), and (iv)") \
        == ["clauses (i), (iii), and (iv)"]


def test_prose_parenthetical_is_not_read_as_an_attached_reference():
    """A reference label is a short token. Treating "(determined without
    regard to subsections (b)" as §152's subsection hid the real list
    behind it and exposed its members as false structural markers."""
    got = _shielded(
        "a dependent, as defined in section 152 (determined without "
        "regard to subsections (b)(1), (b)(2), and (d)(1)(B) thereof)"
    )
    assert got == ["section 152", "subsections (b)(1), (b)(2), and (d)(1)(B)"]


def test_simple_reference_shapes_are_unchanged():
    for text, want in [
        ("under subsection (a)", ["subsection (a)"]),
        ("under section 152", ["section 152"]),
        ("under section 152(e)", ["section 152(e)"]),
        ("under section 7702B(b)", ["section 7702B(b)"]),
        ("in subparagraph (A)(ii)", ["subparagraph (A)(ii)"]),
        ("in paragraphs (3) and (4)", ["paragraphs (3) and (4)"]),
    ]:
        assert _shielded(text) == want, text


def test_flattened_subsection_yields_every_paragraph_marker():
    """The 26 USC 63(b) shape: each paragraph ends in a citation, so the
    next paragraph's marker directly follows one. All seven must be
    reachable — four of them were not."""
    body = (
        "(b) Individuals who do not itemize their deductions In the case "
        "of an individual, the term “taxable income” means adjusted gross "
        "income, minus— (1) the standard deduction, (2) the deduction for "
        "personal exemptions provided in section 151, (3) any deduction "
        "provided in section 199A, (4) the deduction provided in section "
        "170(p), (5) the deduction provided in section 224, (6) the "
        "deduction provided in section 225 and 1 1 So in original. "
        "Probably should be preceded by a comma. (7) so much of the "
        "deduction allowed by section 163(a) as does not exceed."
    )
    for n in range(1, 8):
        got, _ = slice_subsection(body, f"26 USC 63(b)({n})")
        assert got is not None, f"paragraph ({n}) not found"
        assert got.lstrip().startswith(f"({n})"), (n, got[:40])
