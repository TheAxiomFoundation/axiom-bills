"""Tests for the op→encoding scope rule.

Regression context (H.R.372): one add-end op against '7 USC 2015'
prefix-matched nine nested statutes/7/2015/... files and produced nine
no-content variants. Appending new text cannot change what an existing
child file encodes.
"""

from __future__ import annotations

from axiom_bills._common.citation_scope import (
    is_ancestor,
    normalize_citation,
    op_affects_encoding,
)


def test_normalize_citation_collapses_format_drift():
    """Rule sources drift ('20 U.S.C. 1070a', '26 U. S. C. § 32');
    unnormalized prefix comparisons silently fail across the forms."""
    assert normalize_citation("20 U.S.C. 1070a(b)(5)") == "20 USC 1070a(b)(5)"
    assert normalize_citation("7 C.F.R. 273.3") == "7 CFR 273.3"
    assert normalize_citation("26 U.S.C. § 32(a)") == "26 USC 32(a)"
    assert normalize_citation("26 USC 32") == "26 USC 32"
    assert normalize_citation("IRC section 63(c)(5)") == "26 USC 63(c)(5)"
    assert normalize_citation("IRC § 24(h)") == "26 USC 24(h)"
    # Non-mappable forms pass through (counted by the index warning).
    assert normalize_citation("paragraph (1)") == "paragraph (1)"
    assert normalize_citation("91 FR 33348") == "91 FR 33348"


def test_is_ancestor():
    assert is_ancestor("7 USC 2015", "7 USC 2015(d)(2)(A)")
    assert is_ancestor("26 USC 32", "26 USC 32(a)")
    assert is_ancestor("7 CFR 273", "7 CFR 273.3")
    assert not is_ancestor("7 USC 2015", "7 USC 2015")      # not strict
    assert not is_ancestor("7 USC 201", "7 USC 2015")       # no token split
    assert not is_ancestor("7 USC 2015(d)", "7 USC 2015")


def test_exact_target_always_affected():
    assert op_affects_encoding("7 USC 2015", "7 USC 2015", "add-end")
    assert op_affects_encoding("26 USC 24(e)", "26 USC 24(e)", "strike-insert")


def test_ancestor_file_affected_by_any_op():
    # File encodes the whole section; an edit inside it is its business.
    assert op_affects_encoding("26 USC 24", "26 USC 24(e)", "strike-insert")
    assert op_affects_encoding("26 USC 24", "26 USC 24(h)(2)", "add-end")


def test_additive_op_cannot_affect_descendants():
    """The H.R.372 spam: add-end at §2015 fanned out to every child."""
    for child in ("7 USC 2015(b)(1)", "7 USC 2015(d)(2)",
                  "7 USC 2015(d)(2)(A)", "7 USC 2015(e)"):
        assert not op_affects_encoding(child, "7 USC 2015", "add-end")
        assert not op_affects_encoding(child, "7 USC 2015", "insert-after")


def test_modifying_ops_do_affect_descendants():
    # 'Section 2015(d) is amended to read...' rewrites its children.
    assert op_affects_encoding("7 USC 2015(d)(2)", "7 USC 2015(d)", "amend-to-read")
    assert op_affects_encoding("7 USC 2015(d)(2)", "7 USC 2015", "strike-insert")
    assert op_affects_encoding("7 USC 2015(d)(2)", "7 USC 2015(d)", "repeal")


def test_scope_check_survives_format_drift():
    """The choke point normalizes its own inputs — drift in either
    argument must not silently fail the comparison."""
    assert op_affects_encoding("20 U.S.C. 1070a(b)(5)", "20 USC 1070a",
                               "strike-insert")
    assert op_affects_encoding("20 USC 1070a(b)(5)", "20 U.S.C. § 1070a",
                               "strike-insert")
    assert not op_affects_encoding("20 U.S.C. 1070a(b)(5)", "20 USC 1070a",
                                   "add-end")


def test_unrelated_citations_never_affected():
    assert not op_affects_encoding("26 USC 32(a)", "7 USC 2015", "strike-insert")
    assert not op_affects_encoding("7 USC 2025", "7 USC 2015", "amend-to-read")
