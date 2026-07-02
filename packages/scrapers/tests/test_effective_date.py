"""Tests for statutory effective-date extraction."""

from __future__ import annotations

from datetime import date

from axiom_bills._common.effective_date import extract_effective_date


def test_taxable_years_beginning_after():
    text = ("(c) Effective Date.--The amendments made by this section "
            "shall apply to taxable years beginning after December 31, 2026.")
    assert extract_effective_date(text) == date(2027, 1, 1)


def test_takes_effect_on():
    text = "This Act shall take effect on January 1, 2027."
    assert extract_effective_date(text) == date(2027, 1, 1)


def test_enactment_relative_returns_none():
    text = ("The amendments made by this section shall take effect on "
            "the date of the enactment of this Act.")
    assert extract_effective_date(text) is None


def test_conflicting_dates_return_none():
    text = ("Section 2 shall apply to taxable years beginning after "
            "December 31, 2026. Section 3 shall take effect on "
            "July 1, 2028.")
    assert extract_effective_date(text) is None


def test_same_date_via_two_phrasings_is_unambiguous():
    text = ("shall apply to taxable years beginning after December 31, 2026. "
            "The remainder shall take effect on January 1, 2027.")
    assert extract_effective_date(text) == date(2027, 1, 1)


def test_no_date_language():
    assert extract_effective_date("Section 32 is amended by striking '$600'.") is None
    assert extract_effective_date("") is None
