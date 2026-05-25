"""Per-jurisdiction kind classifiers, just like status patterns are tested.

Catches the H.R.6 / post-office bug class: a tweak that accidentally
demotes a substantive bill to ceremonial or vice versa is loud and
visible here.
"""
from __future__ import annotations

import pytest

from axiom_bills._common.models import BillKind

from axiom_bills.jurisdictions.us_federal.bill.kind import classify as classify_us
from axiom_bills.jurisdictions.us_ny.bill.kind import classify as classify_us_ny
from axiom_bills.jurisdictions.us_co.bill.kind import classify as classify_us_co
from axiom_bills.jurisdictions.us_mn.bill.kind import classify as classify_us_mn


@pytest.mark.parametrize("title,expected", [
    ("Reserved for the Speaker.",                          BillKind.PLACEHOLDER),
    ("Reserved for the Minority Leader.",                  BillKind.PLACEHOLDER),
    ("Making appropriations for the Department of Defense, FY2026",
                                                           BillKind.APPROPRIATIONS),
    ("To designate the facility at 100 Main St as the John Smith Post Office",
                                                           BillKind.CEREMONIAL),
    ("Expressing the sense of the House regarding international affairs",
                                                           BillKind.CEREMONIAL),
    ("Honoring the life of Senator Jane Doe",              BillKind.CEREMONIAL),
    ("Congratulating the University of X on their championship",
                                                           BillKind.CEREMONIAL),
    ("Providing for consideration of H.R. 1234",           BillKind.PROCEDURAL),
    ("Electing Members to certain standing committees",    BillKind.PROCEDURAL),
    ("A bill to amend the Internal Revenue Code to expand the Earned Income Tax Credit",
                                                           BillKind.SUBSTANTIVE),
    (None,                                                 BillKind.SUBSTANTIVE),
    ("",                                                   BillKind.SUBSTANTIVE),
])
def test_federal_kinds(title, expected):
    assert classify_us(title) == expected


@pytest.mark.parametrize("title,expected", [
    ("LEGISLATIVE RESOLUTION mourning the death of …",     BillKind.CEREMONIAL),
    ("LEGISLATIVE RESOLUTION commemorating the 50th anniversary …",
                                                           BillKind.CEREMONIAL),
    ("Memorializing Governor … to proclaim …",             BillKind.CEREMONIAL),
    ("Making appropriations for the support of government", BillKind.APPROPRIATIONS),
    ("Adopting the rules of the Senate for the 2025-2026 session",
                                                           BillKind.PROCEDURAL),
    ("An act to amend the tax law in relation to the empire state child credit",
                                                           BillKind.SUBSTANTIVE),
])
def test_ny_kinds(title, expected):
    assert classify_us_ny(title) == expected


@pytest.mark.parametrize("title,expected", [
    ("Concerning state general fund appropriations to the department of revenue",
                                                           BillKind.APPROPRIATIONS),
    ("A tribute to outgoing Senator …",                    BillKind.CEREMONIAL),
    ("Concerning the modification of the earned income tax credit",
                                                           BillKind.SUBSTANTIVE),
])
def test_co_kinds(title, expected):
    assert classify_us_co(title) == expected


@pytest.mark.parametrize("title,expected", [
    ("A bill for an act appropriating money for the department of human services",
                                                           BillKind.APPROPRIATIONS),
    ("A senate resolution recognizing the role of …",      BillKind.CEREMONIAL),
    ("A bill for an act relating to taxation; modifying the child tax credit",
                                                           BillKind.SUBSTANTIVE),
])
def test_mn_kinds(title, expected):
    assert classify_us_mn(title) == expected
