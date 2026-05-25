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
