"""Structured amendment-block parser tests.

The patterns here are derived from real federal bills we've encountered
(H.R.7024, H.R.2573 LIZARD Act, S.253 medical-expense bill) plus
synthetic minimal cases for each op kind we support.
"""
from __future__ import annotations

from axiom_bills._common.amendment_blocks import parse_bill_amendments


# ────────────────────────────────────────────────────────────────────
#  Single-block, single-op patterns
# ────────────────────────────────────────────────────────────────────

def test_simple_strike_insert_with_usc_paren():
    text = (
        "SECTION 1. AMENDMENT.\n"
        "Section 213 of the Internal Revenue Code of 1986 (26 U.S.C. 213) "
        "is amended by striking ``7.5 percent'' and inserting ``10 percent''.\n"
    )
    blocks = parse_bill_amendments(text)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.target == "26 USC 213"
    assert len(b.operations) == 1
    op = b.operations[0]
    assert op.kind == "strike-insert"
    assert op.target == "26 USC 213"
    assert op.needle == "7.5 percent"
    assert op.payload == "10 percent"


def test_target_inferred_from_act_name():
    """Without a (T U.S.C. N) parenthetical, fall back to the act."""
    text = (
        "Section 213 of the Internal Revenue Code is amended by striking "
        "``7.5'' and inserting ``10''."
    )
    blocks = parse_bill_amendments(text)
    assert blocks[0].target == "26 USC 213"


# ────────────────────────────────────────────────────────────────────
#  H.R.2573 LIZARD Act — the duplicate-tab bug we're fixing
# ────────────────────────────────────────────────────────────────────

def test_lizard_act_scope_narrowing():
    text = (
        "Section 4(a) of the Endangered Species Act of 1973 (16 U.S.C. 1533(a)) "
        "is amended--\n"
        "    (1) in paragraph (1), by striking ``The Secretary shall by "
        "regulation'' and inserting ``Except as provided in paragraph (4), "
        "the Secretary shall by regulation''; and\n"
        "    (2) by adding at the end the following:\n"
        "        ``(4) Applicability to Dunes Sagebrush Lizard.--The "
        "Secretary may not make a determination under this section.''.\n"
    )
    blocks = parse_bill_amendments(text)
    # Exactly ONE block, not two. The duplicate-citation bug we're fixing.
    assert len(blocks) == 1
    b = blocks[0]
    assert b.target == "16 USC 1533(a)"
    assert len(b.operations) == 2

    op1 = b.operations[0]
    assert op1.kind == "strike-insert"
    # Scope narrowed: "in paragraph (1), by striking..."
    assert op1.target == "16 USC 1533(a)(1)"
    assert op1.needle == "The Secretary shall by regulation"
    assert "Except as provided in paragraph (4)" in op1.payload

    op2 = b.operations[1]
    assert op2.kind == "add-end"
    assert op2.target == "16 USC 1533(a)"
    assert "Applicability to Dunes Sagebrush Lizard" in op2.payload


# ────────────────────────────────────────────────────────────────────
#  Phase 2 op kinds: repeal, redesignate, insert-after, amend-to-read
# ────────────────────────────────────────────────────────────────────

def test_repeal():
    text = (
        "Section 213 of such Code (26 U.S.C. 213) is amended--\n"
        "    (1) by repealing subsection (b);\n"
    )
    blocks = parse_bill_amendments(text)
    assert blocks[0].operations[0].kind == "repeal"
    assert blocks[0].operations[0].target == "26 USC 213(b)"


def test_redesignate():
    text = (
        "Section 213 of such Code (26 U.S.C. 213) is amended "
        "by redesignating subsection (b) as subsection (c).\n"
    )
    op = parse_bill_amendments(text)[0].operations[0]
    assert op.kind == "redesignate"
    assert op.target == "26 USC 213(b)"
    assert op.redesignate_to == "c"


def test_insert_after():
    text = (
        "Section 213 of such Code (26 U.S.C. 213) is amended "
        "by inserting after ``insulin'' the following: ``or eligible "
        "long-term care premiums''."
    )
    op = parse_bill_amendments(text)[0].operations[0]
    assert op.kind == "insert-after"
    assert op.anchor == "insulin"
    assert "long-term care premiums" in op.payload


def test_amend_to_read_wholesale():
    text = (
        "Section 213(a) of such Code (26 U.S.C. 213(a)) is amended to read "
        "as follows: ``(a) New text here.''.\n"
    )
    block = parse_bill_amendments(text)[0]
    assert block.operations[0].kind == "amend-to-read"
    assert "New text here" in block.operations[0].payload


# ────────────────────────────────────────────────────────────────────
#  Phase 3 — unparsed blocks
# ────────────────────────────────────────────────────────────────────

def test_unparseable_verb_records_warning():
    text = (
        "Section 213 of such Code (26 U.S.C. 213) is amended by "
        "doing something totally undocumented to its provisions."
    )
    block = parse_bill_amendments(text)[0]
    # No ops parsed
    assert block.operations == []
    # Warning preserves the raw clause
    assert block.parse_warnings
    assert "undocumented" in block.parse_warnings[0]


def test_multi_section_bill_yields_one_block_per_section():
    text = (
        "Section 213 of such Code (26 U.S.C. 213) is amended by striking "
        "``7.5'' and inserting ``10''.\n\n"
        "Section 67 of such Code (26 U.S.C. 67) is amended by striking "
        "``2-percent'' and inserting ``5-percent''.\n"
    )
    blocks = parse_bill_amendments(text)
    targets = {b.target for b in blocks}
    assert targets == {"26 USC 213", "26 USC 67"}


# ────────────────────────────────────────────────────────────────────
#  Word-boundary matching and trailing scope qualifiers
# ────────────────────────────────────────────────────────────────────

from axiom_bills._common.amendment_blocks import (  # noqa: E402
    _norm_spans,
    _peel_trailing_scope,
    _replace_trailing,
)


def test_norm_spans_skips_matches_inside_a_word():
    text = "the standard deduction, and the other one"
    assert len(_norm_spans(text, "and")) == 1
    # Unbounded is what used to corrupt the text: "standard" also hits.
    assert len(_norm_spans(text, "and", bounded=False)) == 2


def test_norm_spans_tolerates_wrapped_whitespace():
    text = "exceed 7.5\n        percent of adjusted gross income"
    spans = _norm_spans(text, "7.5 percent")
    assert len(spans) == 1
    start, end = spans[0]
    assert text[start:end] == "7.5\n        percent"


def test_norm_spans_leaves_punctuation_needles_unconstrained():
    # A needle that starts/ends on punctuation has no word boundary to
    # respect, so both periods are still candidates.
    assert len(_norm_spans("one. two.", ".")) == 2


def test_peel_trailing_scope_reads_of_paragraph():
    target, at_end, eaten = _peel_trailing_scope(
        " at the end of paragraph (6);", "26 USC 63(b)")
    assert target == "26 USC 63(b)(6)"
    assert at_end is True
    assert eaten > 0


def test_peel_trailing_scope_handles_chained_labels():
    target, _, _ = _peel_trailing_scope(
        " of subparagraph (A)(ii)", "26 USC 63(b)")
    assert target == "26 USC 63(b)(A)(ii)"


def test_peel_trailing_scope_marks_position_without_narrowing():
    target, at_end, eaten = _peel_trailing_scope(" at the end;", "26 USC 63(b)")
    assert target == "26 USC 63(b)"
    assert at_end is True
    assert eaten > 0


def test_peel_trailing_scope_is_a_noop_without_a_qualifier():
    target, at_end, eaten = _peel_trailing_scope(
        " and inserting ``x''", "26 USC 63(b)")
    assert (target, at_end, eaten) == ("26 USC 63(b)", False, 0)


def test_replace_trailing_targets_the_final_occurrence():
    text = "first. second."
    out, ok = _replace_trailing(text, ".", ", and")
    assert ok
    assert out == "first. second, and"


def test_replace_trailing_declines_when_not_at_the_end():
    _, ok = _replace_trailing("ends with a comma,", ".", "!")
    assert not ok
