"""S. 3596 (119th), the Stronger Start for Working Families Act, against
the corpus rows axiom.org/bills actually gets.

Section 2(a) strikes "$3,000" in 26 USC 24(d)(1)(B)(i) and inserts "$1".
Section 2(b) strikes 26 USC 24(h)(6). Corpus has a row for (h)(6) and none
below 24(d)(1), so the second applies and the first is declined: the row
for (d)(1) is wider than the clause the bill names, and one "$3,000" in a
wider row is not proof it sits in that clause. The page must then list the
instruction, with that reason, and show no diff. These tests pin both
halves, so the page's honesty does not depend on anyone remembering why.

Two attempts to apply the first instruction anyway, by locating clause
(B)(i) inside the row with the marker heuristics, were withdrawn after
independent review. The first edited the wrong text in 10 of 75 newly
applied instructions across 490 bills. The second applied only a text
strike whose single occurrence the located span "confirmed"; review then
showed a range reference in the parent's trailing text closing the span
falsely, a nested roman "(I)" answering for a subparagraph across a
numbering gap, and "$3,000" matching inside "$3,000,000". The durable fix
is clause-level rows in axiom-corpus, which the corpus-row path below
already handles.
"""
from __future__ import annotations

from axiom_bills._common.amendment_blocks import apply_block, parse_bill_amendments
from axiom_bills._common.amendments import slice_subsection
from tests.fixtures.usc_24_rows import ROW_24_D_1, ROW_24_H, ROW_24_H_6, S3596_TEXT


def test_the_bill_parses_into_a_threshold_change_and_a_conforming_strike():
    threshold, conforming = parse_bill_amendments(S3596_TEXT)
    assert threshold.target == "26 USC 24(d)(1)(B)(i)"
    assert [(o.kind, o.needle, o.payload) for o in threshold.operations] == [
        ("strike-insert", "$3,000", "$1"),
    ]
    assert not threshold.parse_warnings
    assert conforming.target == "26 USC 24(h)"
    assert [(o.kind, o.target) for o in conforming.operations] == [
        ("repeal", "26 USC 24(h)(6)"),
    ]


def test_the_threshold_change_is_declined_inside_the_wider_paragraph_row():
    """What the page lists under "not applied", with this reason."""
    block = parse_bill_amendments(S3596_TEXT)[0]
    result = apply_block(
        block, ROW_24_D_1, slice_subsection,
        resolve_scope=lambda _citation: None,
        body_is_exact=False,
    )
    assert not result.applied
    ((op, note),) = result.unapplied
    assert (op.kind, op.needle, op.payload) == ("strike-insert", "$3,000", "$1")
    assert "corpus has no row for 26 USC 24(d)(1)(B)(i)" in note
    assert "cannot delimit" in note
    # Current law is shown untouched: no diff is claimed.
    assert result.before_text == ROW_24_D_1
    assert result.after_text == ROW_24_D_1


def test_the_conforming_strike_applies_through_the_corpus_row_for_paragraph_6():
    block = parse_bill_amendments(S3596_TEXT)[1]
    result = apply_block(
        block, ROW_24_H, slice_subsection,
        resolve_scope={"26 USC 24(h)(6)": ROW_24_H_6}.get,
    )
    assert not result.unapplied
    assert [o.scope_source for o in result.applied] == ["corpus"]
    assert "“$2,500”" not in result.after_text
    assert "(5) Maximum amount of refundable credit" in result.after_text
    assert "(7) Social security number required" in result.after_text
