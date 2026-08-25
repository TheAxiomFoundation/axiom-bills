"""Applier tests — verifies that AmendmentBlock ops correctly transform a
synthetic corpus body. Real-bill end-to-end tests live in the API.
"""
from __future__ import annotations

from axiom_bills._common.amendment_blocks import (
    apply_block,
    parse_bill_amendments,
)
from axiom_bills._common.amendments import slice_subsection


SECTION_213 = (
    "(a) Allowance of deduction There shall be allowed as a deduction "
    "the expenses paid during the taxable year, to the extent such "
    "expenses exceed 7.5 percent of adjusted gross income.\n\n"
    "(b) Limitation with respect to medicine and drugs An amount paid "
    "during the taxable year for medicine or a drug shall be taken into "
    "account under subsection (a) only if such medicine or drug is a "
    "prescribed drug or is insulin.\n\n"
    "(c) Special rule for decedents (1) Treatment of expenses paid "
    "after death For purposes of subsection (a). (2) Limitation "
    "Paragraph (1) shall not apply if the amount paid is allowable.\n\n"
    "(d) Definitions (1) The term \"medical care\" means amounts paid.\n\n"
    "(e) Exclusion of amounts allowed for care of certain dependents."
)


def _slice(body, citation):
    return slice_subsection(body, citation)


def test_apply_strike_insert_to_subsection():
    bill = (
        "Section 213 of the Internal Revenue Code (26 U.S.C. 213) is amended "
        "by striking ``7.5 percent'' and inserting ``5 percent''.\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_213, _slice)
    assert len(result.applied) == 1
    assert not result.unapplied
    assert "5 percent" in result.after_text
    assert "7.5 percent" not in result.after_text


def test_apply_lizard_pattern_scope_narrowed():
    bill = (
        "Section 213(c) of the Internal Revenue Code (26 U.S.C. 213(c)) "
        "is amended--\n"
        "    (1) in paragraph (1), by striking ``Treatment of expenses paid "
        "after death'' and inserting ``Estate medical expenses''; and\n"
        "    (2) by adding at the end the following: "
        "``(3) Extra rule for medical estates.''.\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_213, _slice)
    assert len(result.applied) == 2
    assert "Estate medical expenses" in result.after_text
    assert "Treatment of expenses paid after death" not in result.after_text
    assert "(3) Extra rule for medical estates" in result.after_text


def test_apply_repeal_subsection():
    bill = (
        "Section 213 of such Code (26 U.S.C. 213) is amended by repealing "
        "subsection (b)."
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_213, _slice)
    assert len(result.applied) == 1
    # The (b) subsection text should be replaced
    assert "(b) Limitation with respect to medicine" not in result.after_text


def test_apply_insert_after():
    bill = (
        "Section 213 of such Code (26 U.S.C. 213) is amended by inserting "
        "after ``insulin'' the following: ``or eligible long-term care premiums''."
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_213, _slice)
    assert len(result.applied) == 1
    assert "insulin or eligible long-term care premiums" in result.after_text


def test_apply_unparsed_op_records_note():
    """Redesignate is recognized by the parser but not yet auto-applied —
    should land in `unapplied` with a clear note, not silently drop."""
    bill = (
        "Section 213 of such Code (26 U.S.C. 213) is amended by redesignating "
        "subsection (b) as subsection (f)."
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_213, _slice)
    assert result.applied == []
    assert len(result.unapplied) == 1
    _, note = result.unapplied[0]
    assert "redesignate" in note


# ────────────────────────────────────────────────────────────────────
#  H.R.5366 regression — "the stard deduction"
#
#  The bill said "by striking ``and'' at the end of paragraph (6)".
#  The scope qualifier trails the operand instead of leading it, so the
#  op kept the whole-subsection target, and an unbounded substring
#  replace struck the first "and" in the section — the one inside
#  "standard deduction".
# ────────────────────────────────────────────────────────────────────

SECTION_63B = (
    "(b) Individuals who do not itemize their deductions.—In the case of "
    "an individual who does not elect to itemize his deductions for the "
    "taxable year, for purposes of this subtitle, the term “taxable "
    "income” means adjusted gross income, minus— (1) the standard "
    "deduction, (2) the deduction for personal exemptions provided in "
    "section 151, (3) the deduction provided in section 199A, (6) the "
    "deduction for seniors, and (7) the deduction for tips."
)

_HR5366 = (
    "Section 63(b) of the Internal Revenue Code of 1986 (26 U.S.C. 63(b)) "
    "is amended--\n"
    "            (1) by striking ``and'' at the end of paragraph (6);\n"
)


def test_trailing_scope_qualifier_narrows_the_op_target():
    block = parse_bill_amendments(_HR5366)[0]
    op = block.operations[0]
    assert op.target == "26 USC 63(b)(6)"
    assert op.at_end is True


def test_striking_and_does_not_corrupt_standard_deduction():
    block = parse_bill_amendments(_HR5366)[0]
    result = apply_block(block, SECTION_63B, _slice)
    assert "stard" not in result.after_text
    assert "the standard deduction" in result.after_text
    # The conjunction closing paragraph (6) is the one that goes.
    assert "for seniors, and" not in result.after_text
    assert "(7) the deduction for tips" in result.after_text


def test_leading_and_trailing_scope_forms_agree():
    leading = (
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended--\n"
        "            (1) in paragraph (6), by striking ``and'' at the end;\n"
    )
    a = apply_block(parse_bill_amendments(_HR5366)[0], SECTION_63B, _slice)
    b = apply_block(parse_bill_amendments(leading)[0], SECTION_63B, _slice)
    assert a.after_text == b.after_text


def test_bare_word_needle_never_matches_inside_a_word():
    """Even with no scope at all, "and" must not hit "standard"."""
    bill = (
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``and''.\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_63B, _slice)
    assert "stard" not in (result.after_text or "")


def test_ambiguous_unscoped_needle_is_declined_not_guessed():
    """"deduction" appears many times; striking it unscoped is a coin
    flip, so the op is reported unapplied with a reason."""
    bill = (
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``deduction''.\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_63B, _slice)
    assert not result.applied
    assert len(result.unapplied) == 1
    assert "ambiguous" in result.unapplied[0][1]
    assert result.after_text == SECTION_63B


def test_specific_needle_still_applies_unscoped():
    """The guard is for short function words — a distinctive phrase
    still applies on its first match, as before."""
    bill = (
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``the deduction for "
        "seniors'' and inserting ``the senior allowance''.\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(block, SECTION_63B, _slice)
    assert len(result.applied) == 1
    assert "the senior allowance" in result.after_text
    assert "the deduction for seniors" not in result.after_text


# ────────────────────────────────────────────────────────────────────
#  Corpus-first scope resolution
#
#  axiom-corpus stores subsections and paragraphs as addressable rows
#  (us/statute/26/63/b/6), so an op's scope is a lookup rather than a
#  structure to re-derive from prose. Marker heuristics stay as the
#  fallback for subparagraph and deeper, tagged so nothing downstream
#  mistakes a heuristic scope for a verified one.
# ────────────────────────────────────────────────────────────────────

# The real corpus text of 26 USC 63(b) and its paragraph (6).
CORPUS_63B_ROW = (
    "In the case of an individual who does not elect to itemize his "
    "deductions for the taxable year, for purposes of this subtitle, the "
    "term “taxable income” means adjusted gross income, minus— the "
    "standard deduction, the deduction for personal exemptions provided "
    "in section 151, any deduction provided in section 199A, the "
    "deduction provided in section 225 and, so much of the deduction "
    "allowed by section 163(a) as does not exceed the amount."
)
CORPUS_63B6_ROW = "the deduction provided in section 225 and"


def _corpus(rows):
    return lambda citation: rows.get(citation)


def test_scope_comes_from_the_corpus_row_when_one_exists():
    bill = (
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``and'' at the end of "
        "paragraph (6).\n"
    )
    block = parse_bill_amendments(bill)[0]
    result = apply_block(
        block, CORPUS_63B_ROW, _slice,
        resolve_scope=_corpus({"26 USC 63(b)(6)": CORPUS_63B6_ROW}),
    )
    assert len(result.applied) == 1
    assert result.applied[0].scope_source == "corpus"
    assert "the standard deduction" in result.after_text
    assert "section 225 and," not in result.after_text


def test_corpus_scope_beats_the_marker_heuristics():
    """Paragraph (6) is invisible to the slicer here — the markers were
    dropped when corpus flattened the subsection to one line — but the
    corpus row addresses it directly."""
    block = parse_bill_amendments(
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``and'' at the end of "
        "paragraph (6).\n"
    )[0]
    assert slice_subsection(CORPUS_63B_ROW, "26 USC 63(b)(6)")[0] is None
    result = apply_block(
        block, CORPUS_63B_ROW, _slice,
        resolve_scope=_corpus({"26 USC 63(b)(6)": CORPUS_63B6_ROW}),
    )
    assert [o.scope_source for o in result.applied] == ["corpus"]


def test_ambiguous_corpus_text_is_not_used_as_a_scope():
    """If the corpus row's text appears twice in the parent we cannot say
    which copy the amendment means."""
    doubled = CORPUS_63B6_ROW + " and also " + CORPUS_63B6_ROW
    block = parse_bill_amendments(
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``225'' at the end of "
        "paragraph (6).\n"
    )[0]
    result = apply_block(
        block, doubled, _slice,
        resolve_scope=_corpus({"26 USC 63(b)(6)": CORPUS_63B6_ROW}),
    )
    # Falls through to the unscoped rule, which declines: two matches.
    assert not result.applied
    assert result.unapplied


def test_deep_target_falls_back_to_slicing_and_is_flagged():
    """Corpus has no row at subparagraph depth, so the marker heuristics
    still run — but the op records that its scope was heuristic."""
    block = parse_bill_amendments(
        "Section 213(c) of the Internal Revenue Code (26 U.S.C. 213(c)) "
        "is amended--\n"
        "    (1) in paragraph (2), by striking ``allowable'' and "
        "inserting ``deductible''.\n"
    )[0]
    result = apply_block(block, SECTION_213, _slice, resolve_scope=_corpus({}))
    assert len(result.applied) == 1
    assert result.applied[0].scope_source == "sliced"
    assert "the amount paid is deductible" in result.after_text


def test_undelimitable_ancestor_scope_is_declined():
    """Corpus fell back to the enclosing section and the block's own text
    can't be found in it. The needle occurs exactly once — but in a
    sibling subsection the bill never named, so we must not apply it."""
    enclosing = (
        "(a) General rule. The taxpayer shall reduce the standard "
        "deduction by such amount, as described in section 151, "
        "(b) Special rule. No reduction applies."
    )
    block = parse_bill_amendments(
        "Section 63(b) of the Internal Revenue Code of 1986 "
        "(26 U.S.C. 63(b)) is amended by striking ``the standard "
        "deduction'' and inserting ``the basic allowance''.\n"
    )[0]
    result = apply_block(block, enclosing, _slice, body_is_exact=False)
    assert not result.applied
    assert "cannot delimit" in result.unapplied[0][1]
    assert result.after_text == enclosing
