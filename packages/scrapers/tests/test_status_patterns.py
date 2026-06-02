"""Status-normalization patterns are the most bug-prone part of the
scraper layer because one bad regex silently mis-classifies thousands of
bills. Test exhaustively per jurisdiction with real action strings.
"""
from __future__ import annotations

import pytest

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import match_first

from axiom_bills.jurisdictions.us_federal.bill.status import (
    PATTERNS as FEDERAL_PATTERNS,
)
from axiom_bills.jurisdictions.us_ny.bill.status import PATTERNS as NY_PATTERNS
from axiom_bills.jurisdictions.us_co.bill.status import PATTERNS as CO_PATTERNS
from axiom_bills.jurisdictions.us_de.bill.status import PATTERNS as DE_PATTERNS
from axiom_bills.jurisdictions.us_mn.bill.status import PATTERNS as MN_PATTERNS


@pytest.mark.parametrize("text,expected", [
    ("Introduced in House",               NormalizedStatus.INTRODUCED),
    ("Referred to the Committee on Ways and Means.",
                                          NormalizedStatus.IN_COMMITTEE),
    ("Passed/agreed to in House: On passage Passed by the Yeas and Nays",
                                          NormalizedStatus.PASSED_CHAMBER),
    ("Presented to President.",           NormalizedStatus.ENROLLED),
    ("Signed by President.",              NormalizedStatus.SIGNED),
    ("Became Public Law No: 119-12.",     NormalizedStatus.ENACTED),
    ("Vetoed by President.",              NormalizedStatus.VETOED),
])
def test_federal_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, FEDERAL_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("REFERRED TO RULES",                       NormalizedStatus.IN_COMMITTEE),
    ("PASSED SENATE",                           NormalizedStatus.PASSED_CHAMBER),
    ("DELIVERED TO GOVERNOR",                   NormalizedStatus.ENROLLED),
    ("APPROVED BY GOVERNOR",                    NormalizedStatus.SIGNED),
    ("SIGNED CHAP.145",                         NormalizedStatus.ENACTED),
    ("VETOED MEMO.123",                         NormalizedStatus.VETOED),
])
def test_ny_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, NY_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduced In House",                     NormalizedStatus.INTRODUCED),
    ("House Committee on Finance Refer Amended", NormalizedStatus.IN_COMMITTEE),
    ("Third Reading Passed - No Amendments",    NormalizedStatus.PASSED_CHAMBER),
    ("Sent to the Governor",                    NormalizedStatus.ENROLLED),
    ("Governor Signed",                         NormalizedStatus.SIGNED),
    ("Governor Signed into Law",                NormalizedStatus.ENACTED),
])
def test_co_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, CO_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduced",                               NormalizedStatus.INTRODUCED),
    ("In committee",                             NormalizedStatus.IN_COMMITTEE),
    ("Out of committee",                         NormalizedStatus.IN_COMMITTEE),
    ("House passed",                             NormalizedStatus.PASSED_CHAMBER),
    ("Senate passed",                            NormalizedStatus.PASSED_CHAMBER),
    ("Governor signed",                          NormalizedStatus.SIGNED),
    ("Stricken",                                 NormalizedStatus.FAILED),
])
def test_de_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, DE_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduction and first reading, referred to Taxes",
                                                NormalizedStatus.INTRODUCED),
    ("Third reading Passed",                    NormalizedStatus.PASSED_CHAMBER),
    ("Presented to Governor",                   NormalizedStatus.ENROLLED),
    ("Signed by Governor",                      NormalizedStatus.SIGNED),
    ("Secretary of State Chapter 145 03/15/26", NormalizedStatus.ENACTED),
])
def test_mn_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, MN_PATTERNS) == expected
