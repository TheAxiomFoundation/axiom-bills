"""Tests for the federal citation extractor.

These cover the normalization paths that feed axiom_encodings lookups
directly — a wrong citation here silently breaks corpus and rulespec
matching downstream.
"""

from __future__ import annotations

from axiom_bills.jurisdictions.us_federal.bill.citations import extract


def _citations(text: str) -> list[str]:
    return [c for _, c in extract(text)]


def test_usc_formal_and_informal():
    assert _citations("26 U.S.C. § 32(a)(1)") == ["26 USC 32(a)(1)"]
    assert _citations("26 USC 32") == ["26 USC 32"]


def test_cfr():
    assert _citations("7 C.F.R. § 273.3") == ["7 CFR 273.3"]


def test_irc_act_form():
    assert "26 USC 32(a)(1)" in _citations(
        "section 32(a)(1) of the Internal Revenue Code"
    )
    assert "26 USC 24" in _citations(
        "section 24 of the Internal Revenue Code of 1986"
    )


def test_food_and_nutrition_act_with_year_suffix():
    """Regression: the 'of 2008' suffix used to make the act lookup miss,
    silently dropping the citation; and the section number was emitted
    un-offset ('7 USC 6') — a citation that doesn't exist."""
    got = _citations("section 6(b) of the Food and Nutrition Act of 2008")
    assert got == ["7 USC 2015(b)"]


def test_food_and_nutrition_act_without_year():
    assert _citations("section 3 of the Food and Nutrition Act") == ["7 USC 2012"]


def test_social_security_act_not_miscited():
    """SSA codification is non-linear (§1902 → 42 USC 1396a); a 1:1 map
    used to emit '42 USC 1902', which doesn't exist. Better nothing
    than a wrong citation."""
    got = _citations("section 1902 of the Social Security Act")
    assert "42 USC 1902" not in got
