"""Additional amendment-grammar coverage tests.

S.268 "Saving American Workers' Benefits" exposed grammar we hadn't
seen: "Subsection (X) of section Y is amended", and "by striking
paragraph (N)" as a structural strike. These tests pin both.
"""
from __future__ import annotations

from axiom_bills._common.amendment_blocks import parse_bill_amendments


def test_subsection_of_section_header():
    text = (
        "Subsection (e) of section 24 of the Internal Revenue Code of 1986 "
        "is amended to read as follows: ``(e) New rule.''.\n"
    )
    blocks = parse_bill_amendments(text)
    assert len(blocks) == 1
    assert blocks[0].target == "26 USC 24(e)"


def test_subparagraph_of_section_with_subs():
    text = (
        "Subparagraph (I) of section 6213(g)(2) of the Internal Revenue "
        "Code of 1986 is amended by striking ``TIN'' and inserting "
        "``social security number''."
    )
    blocks = parse_bill_amendments(text)
    assert len(blocks) == 1
    assert blocks[0].target == "26 USC 6213(g)(2)(I)"
    assert blocks[0].operations[0].kind == "strike-insert"


def test_paragraph_of_subsection_of_section():
    text = (
        "Paragraph (1) of subsection (b) of section 24 of the Internal "
        "Revenue Code of 1986 is amended by striking ``X'' and inserting ``Y''."
    )
    blocks = parse_bill_amendments(text)
    assert blocks[0].target == "26 USC 24(b)(1)"


def test_strike_structural_paragraph():
    """`by striking paragraph (7)` should be parsed as repeal of (7)."""
    text = (
        "Subsection (h) of section 24 of the Internal Revenue Code of 1986 "
        "is amended by striking paragraph (7)."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "26 USC 24(h)"
    assert len(block.operations) == 1
    op = block.operations[0]
    assert op.kind == "repeal"
    assert op.target == "26 USC 24(h)(7)"


def test_no_duplicate_blocks_for_prefixed_and_bare():
    """If we match a prefixed header, the bare regex shouldn't ALSO
    match its inner 'section X' substring as a separate block."""
    text = (
        "Subsection (e) of section 24 of the Internal Revenue Code of 1986 "
        "is amended to read as follows: ``(e) New rule.''.\n"
    )
    blocks = parse_bill_amendments(text)
    assert len(blocks) == 1


def test_strike_period_at_end_and_insert():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d)(1) of such Code is amended by striking the period "
        "at the end and inserting ``, and for medical conditions described "
        "in subsection (e).''."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "26 USC 213(d)(1)"
    assert any(o.kind == "strike-insert" and o.needle == "." for o in block.operations)


def test_insert_before_punctuation():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d)(1)(D) of such Code is amended by inserting before "
        "the period at the end ``, including dental care''."
    )
    block = parse_bill_amendments(text)[0]
    op = block.operations[0]
    assert op.kind == "strike-insert"
    assert op.needle == "."
    assert "dental care" in op.payload


def test_add_literal_and_at_end():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d)(1)(B) of such Code is amended by adding ``and'' at the end."
    )
    op = parse_bill_amendments(text)[0].operations[0]
    assert op.kind == "add-end"
    assert op.payload == "and"


def test_strike_multiple_structural_elements():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d) of such Code is amended by striking paragraphs "
        "(7), (8), and (9)."
    )
    ops = parse_bill_amendments(text)[0].operations
    repealed_targets = {o.target for o in ops if o.kind == "repeal"}
    assert repealed_targets == {"26 USC 213(d)(7)", "26 USC 213(d)(8)", "26 USC 213(d)(9)"}


def test_insert_after_structural_anchor():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d) of such Code is amended by inserting after "
        "subparagraph (D) the following: ``(E) New rule.''."
    )
    block = parse_bill_amendments(text)[0]
    op = block.operations[0]
    assert op.kind == "insert-after"
    assert op.anchor == "(D)"
    assert "New rule" in op.payload


def test_chain_reference_of_such_title():
    """Second block uses 'of such title' to inherit title from first."""
    text = (
        "Section 1703A of title 38, United States Code, is amended by "
        "striking ``A''.\n"
        "Section 1832(b)(4) of such title is amended by striking ``X'' "
        "and inserting ``Y''.\n"
    )
    blocks = parse_bill_amendments(text)
    assert len(blocks) == 2
    assert blocks[0].target == "38 USC 1703A"
    assert blocks[1].target == "38 USC 1832(b)(4)"


def test_chain_reference_of_such_code():
    """Second block uses 'of such Code' after first established IRC."""
    text = (
        "Section 24 of the Internal Revenue Code of 1986 is amended by "
        "striking ``A''.\n"
        "Section 25 of such Code is amended by striking ``X''.\n"
    )
    blocks = parse_bill_amendments(text)
    assert blocks[0].target == "26 USC 24"
    assert blocks[1].target == "26 USC 25"


def test_multi_letter_hyphenated_section():
    """Title 42 sections like 300hh-14 have 2-3 letters before hyphen."""
    text = (
        "Section 709(a)(7) of the Security and Accountability for Every "
        "Port Act of 2006 (42 U.S.C. 300hh-14(a)(7)) is amended by "
        "striking ``X''."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "42 USC 300hh-14(a)(7)"


def test_usc_paren_with_sec_prefix():
    """'(6 U.S.C. Sec. 279(b)(2))' has 'Sec.' between USC and number."""
    text = (
        "Section 462(b)(2) of the Homeland Security Act of 2002 "
        "(6 U.S.C. Sec. 279(b)(2)) is amended by striking ``X''."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "6 USC 279(b)(2)"


def test_title_n_united_states_code_direct():
    """Bills referencing uncodified titles directly: 'of title 10, United States Code'."""
    text = (
        "Section 2704 of title 10, United States Code, is amended by "
        "striking subsection (f)."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "10 USC 2704"
    op = block.operations[0]
    assert op.kind == "repeal"
    assert op.target == "10 USC 2704(f)"


def test_hyphenated_usc_section():
    text = (
        "Section 2201(e) of the Water Infrastructure Improvements for the "
        "Nation Act (42 U.S.C. 300j-12 note) is amended by striking ``X'' "
        "and inserting ``Y''."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "42 USC 300j-12"


def test_act_name_with_lowercase_connectors():
    """'Water Infrastructure Improvements for the Nation Act' has 'for the'
    lowercase between capitalized words. Should still match."""
    text = (
        "Section 2203 of the Water Infrastructure Improvements for the "
        "Nation Act is amended by striking ``X''."
    )
    block = parse_bill_amendments(text)[0]
    # The act maps to title 33 in our ACT_TO_TITLE
    assert block.target == "33 USC 2203"


def test_insert_before_anchor():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213(d)(1)(D) of such Code is amended by inserting "
        "``qualified'' before ``medical care''."
    )
    op = parse_bill_amendments(text)[0].operations[0]
    assert op.kind == "strike-insert"
    assert op.needle == "medical care"
    assert op.payload == "qualified medical care"


def test_nested_paragraph_subparagraph_items():
    """The block-level splitter must NOT pick up (A)/(B) inside (1) as
    top-level siblings — H.R.68 regression case."""
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213 of such Code is amended--\n"
        "    (1) in subsection (b)--\n"
        "        (A) in paragraph (1), by striking ``A'' and inserting ``B'';\n"
        "        (B) in paragraph (2), by striking ``X'' and inserting ``Y''.\n"
    )
    block = parse_bill_amendments(text)[0]
    targets = {op.target for op in block.operations}
    assert targets == {"26 USC 213(b)(1)", "26 USC 213(b)(2)"}
    assert block.parse_warnings == []


def test_non_narrowing_in_the_heading_prefix():
    text = (
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 213 of such Code is amended--\n"
        "    (1) in the heading, by striking ``Medical'' and inserting ``Health''; and\n"
        "    (2) by adding ``or wellness'' at the end.\n"
    )
    block = parse_bill_amendments(text)[0]
    assert len(block.operations) == 2
    # "in the heading," is non-narrowing — target stays 26 USC 213.
    assert block.operations[0].target == "26 USC 213"
    assert block.operations[0].kind == "strike-insert"


def test_insert_after_flipped_payload_first():
    """SIFIA Act-style: by inserting ``X'' after ``Y''."""
    text = (
        # Bill establishes IRC context.
        "Amendment of the Internal Revenue Code of 1986.\n"
        "Section 512(b)(1) of such Code is amended by inserting "
        "``(other than interest of SIFIA bonds)'' after ``interest''."
    )
    block = parse_bill_amendments(text)[0]
    assert block.target == "26 USC 512(b)(1)"
    assert len(block.operations) == 1
    op = block.operations[0]
    assert op.kind == "insert-after"
    assert op.anchor == "interest"
    assert "SIFIA bonds" in op.payload
