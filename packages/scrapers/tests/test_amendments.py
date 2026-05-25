"""Federal amendment-parsing tests.

These are the canonical patterns the parser needs to handle. When we
expand the grammar coverage, add the new pattern here first so the
regression is obvious.
"""
from __future__ import annotations

from axiom_bills._common.amendments import (
    apply_ops,
    parse_amendments_for_citation,
    unified_diff,
)


CORPUS_213 = (
    "(a) Allowance of deduction\n"
    "There shall be allowed as a deduction the expenses paid during the taxable "
    "year, not compensated for by insurance or otherwise, for medical care of "
    "the taxpayer, his spouse, or a dependent, to the extent that such expenses "
    "exceed 7.5 percent of adjusted gross income."
)


def test_single_strike_insert():
    bill = (
        "SECTION 1. AMENDMENT.\n"
        "Section 213 of the Internal Revenue Code of 1986 is amended by striking "
        "\"7.5 percent\" and inserting \"10 percent\".\n"
    )
    ops = parse_amendments_for_citation(bill, "26 USC 213")
    assert len(ops) == 1
    assert ops[0].kind == "strike-insert"
    assert ops[0].needle == "7.5 percent"
    assert ops[0].payload == "10 percent"

    applied_text, applied, unapplied = apply_ops(CORPUS_213, ops)
    assert "10 percent" in applied_text
    assert "7.5 percent" not in applied_text
    assert len(applied) == 1 and not unapplied


def test_add_at_end():
    bill = (
        "Section 213 of the Internal Revenue Code is amended by adding at the end "
        "the following new subsection: \"(g) Special rule for elective surgery: "
        "see regulations.\".\n"
    )
    ops = parse_amendments_for_citation(bill, "26 USC 213")
    assert any(op.kind == "add-end" for op in ops)
    applied_text, applied, _ = apply_ops(CORPUS_213, ops)
    assert "Special rule for elective surgery" in applied_text


def test_replace_all():
    bill = (
        "Section 213 of such Code is amended to read as follows: "
        "\"(a) Allowance.— There shall be allowed a deduction for qualified "
        "medical expenses in excess of 5 percent of adjusted gross income.\".\n"
    )
    ops = parse_amendments_for_citation(bill, "26 USC 213")
    assert any(op.kind == "replace-all" for op in ops)
    applied_text, _, _ = apply_ops(CORPUS_213, ops)
    assert "5 percent" in applied_text


def test_unapplied_when_needle_absent():
    bill = (
        "Section 213 of the Internal Revenue Code is amended by striking "
        "\"30 percent\" and inserting \"40 percent\".\n"
    )
    ops = parse_amendments_for_citation(bill, "26 USC 213")
    _, applied, unapplied = apply_ops(CORPUS_213, ops)
    assert not applied
    assert len(unapplied) == 1


def test_unified_diff_shape():
    before = "alpha\nbeta\ngamma"
    after = "alpha\nbeta-prime\ngamma\ndelta"
    diff = unified_diff(before, after)
    kinds = [d["kind"] for d in diff]
    assert "equal" in kinds
    assert ("remove" in kinds and "add" in kinds) or "change" in kinds
