"""Regression tests for block-target misattribution.

Both cases are real bills whose amendment blocks were attributed to
'26 USC 1' in production — surfaced the moment unapplied ops stopped
being silently dropped.
"""

from __future__ import annotations

from textwrap import dedent

from axiom_bills._common.amendment_blocks import parse_bill_amendments


def test_bill_enumerator_does_not_swallow_real_header():
    """S.3027: the bill's own 'SECTION 1. <HEADING>.' line used to match
    as the block header, bridging over the real 'Section 48(c)(1)(E) of
    the Internal Revenue Code' reference."""
    text = dedent("""\
        A BILL To amend the Internal Revenue Code of 1986 to extend the
        energy credit for qualified fuel cell property.

        SECTION 1. EXTENSION OF ENERGY CREDIT FOR QUALIFIED FUEL CELL PROPERTY.

        Section 48(c)(1)(E) of the Internal Revenue Code of 1986 is amended
        by striking ``January 1, 2025'' and inserting ``January 1, 2033''.
    """)
    blocks = parse_bill_amendments(text)
    targets = [b.target for b in blocks]
    assert "26 USC 48(c)(1)(E)" in targets
    assert not any(t == "26 USC 1" for t in targets)


def test_et_seq_parenthetical_resolves_title():
    """H.R.1865: '(30 U.S.C. 601 et seq.)' failed the parenthetical
    regex, and the unknown act name fell through to the bill-level IRC
    context — fabricating '26 USC 1'."""
    text = dedent("""\
        (c) Conforming Amendment.--Section 1 of the Act of July 31, 1947,
        entitled ``An Act to provide for the disposal of materials on the
        public lands of the United States'' (30 U.S.C. 601 et seq.) is amended
        by striking ``common varieties of'' in the first sentence.
    """)
    blocks = parse_bill_amendments(text)
    targets = [b.target for b in blocks]
    assert not any(t.startswith("26 USC") for t in targets)
    assert any(t == "30 USC 601" for t in targets)


def test_unknown_act_without_parenthetical_is_not_guessed():
    """An unmapped act name must not inherit the bill-level context
    title — a wrong citation is worse than an unresolved one."""
    text = dedent("""\
        To amend the Internal Revenue Code of 1986 and for other purposes.

        SEC. 2. CONFORMING CHANGES.

        Section 4 of the Frobnication Standards Act is amended by striking
        ``twelve'' and inserting ``fifteen''.
    """)
    blocks = parse_bill_amendments(text)
    assert not any(
        b.target == "26 USC 4" for b in blocks
    ), [b.target for b in blocks]


def test_such_act_still_chains_to_context():
    text = dedent("""\
        (a) In General.--Section 32(b) of the Internal Revenue Code of 1986
        is amended by striking ``$600'' and inserting ``$700''.
        (b) Conforming.--Section 32(c) of such Code is amended by striking
        ``$50'' and inserting ``$60''.
    """)
    blocks = parse_bill_amendments(text)
    targets = [b.target for b in blocks]
    assert "26 USC 32(b)" in targets
    assert "26 USC 32(c)" in targets
