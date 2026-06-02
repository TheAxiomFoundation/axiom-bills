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
from axiom_bills.jurisdictions.us_ks.bill.status import PATTERNS as KS_PATTERNS
from axiom_bills.jurisdictions.us_md.bill.status import PATTERNS as MD_PATTERNS
from axiom_bills.jurisdictions.us_mn.bill.status import PATTERNS as MN_PATTERNS
from axiom_bills.jurisdictions.us_oh.bill.status import PATTERNS as OH_PATTERNS
from axiom_bills.jurisdictions.us_or.bill.status import PATTERNS as OR_PATTERNS
from axiom_bills.jurisdictions.us_ut.bill.status import PATTERNS as UT_PATTERNS
from axiom_bills.jurisdictions.us_wi.bill.status import PATTERNS as WI_PATTERNS


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
    ("Introduced on Wednesday, January 15, 2025",
                                                NormalizedStatus.INTRODUCED),
    ("Referred to Committee on Taxation",       NormalizedStatus.IN_COMMITTEE),
    ("Committee Report recommending bill be passed as amended",
                                                NormalizedStatus.PASSED_CHAMBER),
    ("Enrolled and presented to Governor on Monday, February 2, 2026",
                                                NormalizedStatus.ENROLLED),
    ("Approved by Governor on Thursday, February 5, 2026",
                                                NormalizedStatus.SIGNED),
    ("Published in the Kansas Register",        NormalizedStatus.ENACTED),
    ("Veto overridden",                         NormalizedStatus.VETO_OVERRIDDEN),
])
def test_ks_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, KS_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("In the House - First Reading House Rules and Executive Nominations",
                                                NormalizedStatus.IN_COMMITTEE),
    ("In the House - Hearing 1/20 at 1:00 p.m.",
                                                NormalizedStatus.IN_COMMITTEE),
    ("Favorable with Amendments",               NormalizedStatus.IN_COMMITTEE),
    ("Third Reading Passed",                    NormalizedStatus.PASSED_CHAMBER),
    ("Passed by the General Assembly",          NormalizedStatus.ENROLLED),
    ("Approved by the Governor",                NormalizedStatus.SIGNED),
])
def test_md_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, MD_PATTERNS) == expected


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


@pytest.mark.parametrize("text,expected", [
    ("Introduced",                              NormalizedStatus.INTRODUCED),
    ("Refer to Committee: Public Safety",       NormalizedStatus.IN_COMMITTEE),
    ("Reported - Substitute",                   NormalizedStatus.IN_COMMITTEE),
    ("Passed",                                  NormalizedStatus.PASSED_CHAMBER),
    ("Concurred in Senate amendments",          NormalizedStatus.PASSED_CHAMBER),
    ("Enrolled",                                NormalizedStatus.ENROLLED),
    ("Governor signed",                         NormalizedStatus.SIGNED),
    ("Effective",                               NormalizedStatus.ENACTED),
])
def test_oh_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, OH_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduction and first reading. Referred to Speaker's desk.",
                                                NormalizedStatus.INTRODUCED),
    ("Referred to Revenue.",                    NormalizedStatus.IN_COMMITTEE),
    ("Recommendation: Do pass.",                NormalizedStatus.IN_COMMITTEE),
    ("Third reading. Carried by Fahey. Passed.", NormalizedStatus.PASSED_CHAMBER),
    ("Speaker signed.",                         NormalizedStatus.ENROLLED),
    ("Governor signed.",                        NormalizedStatus.SIGNED),
    ("Chapter 24, Oregon Laws 2026.",           NormalizedStatus.ENACTED),
    ("Failed upon adjournment.",                NormalizedStatus.FAILED),
])
def test_or_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, OR_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("House/ 1st reading (Introduced)",          NormalizedStatus.INTRODUCED),
    ("House/ to standing committee",             NormalizedStatus.IN_COMMITTEE),
    ("House/ committee report favorable",        NormalizedStatus.IN_COMMITTEE),
    ("House/ 3rd reading passed",                NormalizedStatus.PASSED_CHAMBER),
    ("House/ to Governor",                       NormalizedStatus.ENROLLED),
    ("Governor Signed",                          NormalizedStatus.SIGNED),
    ("Lieutenant Governor's office for filing",  NormalizedStatus.ENACTED),
])
def test_ut_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, UT_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduced by Senators Example",          NormalizedStatus.INTRODUCED),
    ("Read first time and referred to Committee on Revenue",
                                               NormalizedStatus.INTRODUCED),
    ("Public hearing held",                    NormalizedStatus.IN_COMMITTEE),
    ("Report passage recommended by Committee on Agriculture and Revenue",
                                               NormalizedStatus.IN_COMMITTEE),
    ("Passed",                                 NormalizedStatus.PASSED_CHAMBER),
    ("Presented to Governor",                  NormalizedStatus.ENROLLED),
    ("Governor approved",                      NormalizedStatus.SIGNED),
    ("Failed to pass pursuant to Senate Joint Resolution 1",
                                               NormalizedStatus.FAILED),
])
def test_wi_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, WI_PATTERNS) == expected
