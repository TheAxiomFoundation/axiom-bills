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
from axiom_bills.jurisdictions.us_fl.bill.status import PATTERNS as FL_PATTERNS
from axiom_bills.jurisdictions.us_id.bill.status import PATTERNS as ID_PATTERNS
from axiom_bills.jurisdictions.us_ks.bill.status import PATTERNS as KS_PATTERNS
from axiom_bills.jurisdictions.us_md.bill.status import PATTERNS as MD_PATTERNS
from axiom_bills.jurisdictions.us_mn.bill.status import PATTERNS as MN_PATTERNS
from axiom_bills.jurisdictions.us_nd.bill.status import PATTERNS as ND_PATTERNS
from axiom_bills.jurisdictions.us_ne.bill.status import PATTERNS as NE_PATTERNS
from axiom_bills.jurisdictions.us_oh.bill.status import PATTERNS as OH_PATTERNS
from axiom_bills.jurisdictions.us_or.bill.status import PATTERNS as OR_PATTERNS
from axiom_bills.jurisdictions.us_ri.bill.status import PATTERNS as RI_PATTERNS
from axiom_bills.jurisdictions.us_sd.bill.status import PATTERNS as SD_PATTERNS
from axiom_bills.jurisdictions.us_ut.bill.status import PATTERNS as UT_PATTERNS
from axiom_bills.jurisdictions.us_wi.bill.status import PATTERNS as WI_PATTERNS
from axiom_bills.jurisdictions.us_wy.bill.status import PATTERNS as WY_PATTERNS


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
    ("Filed",                                      NormalizedStatus.INTRODUCED),
    ("Introduced",                                 NormalizedStatus.INTRODUCED),
    ("Referred to Appropriations",                 NormalizedStatus.IN_COMMITTEE),
    ("On Committee agenda-- Appropriations, 06/01/26",
                                                   NormalizedStatus.IN_COMMITTEE),
    ("CS by- Appropriations; YEAS 13 NAYS 5",      NormalizedStatus.IN_COMMITTEE),
    ("CS by Appropriations read 1st time",         NormalizedStatus.IN_COMMITTEE),
    ("Placed on Special Order Calendar, 06/02/26", NormalizedStatus.IN_COMMITTEE),
    ("Passed; YEAS 36 NAYS 0",                    NormalizedStatus.PASSED_CHAMBER),
    ("Ordered enrolled",                           NormalizedStatus.ENROLLED),
    ("Approved by Governor",                       NormalizedStatus.SIGNED),
    ("Chapter No. 2026-12",                        NormalizedStatus.ENACTED),
    ("Laid on Table, refer to HB 6507",            NormalizedStatus.FAILED),
])
def test_fl_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, FL_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Introduced, read first time, referred to JRA for Printing",
                                                   NormalizedStatus.INTRODUCED),
    ("Reported Printed and Referred to Transportation & Defense",
                                                   NormalizedStatus.IN_COMMITTEE),
    ("Reported out of Committee with Do Pass Recommendation",
                                                   NormalizedStatus.IN_COMMITTEE),
    ("Read second time; Filed for Third Reading",  NormalizedStatus.IN_COMMITTEE),
    ("U.C. to hold place on third reading calendar one legislative day",
                                                   NormalizedStatus.IN_COMMITTEE),
    ("Rules Suspended: Ayes 66 Nays 0 - PASSED - 39-29-2",
                                                   NormalizedStatus.PASSED_CHAMBER),
    ("Reported Enrolled; Signed by Speaker; Transmitted to Senate",
                                                   NormalizedStatus.ENROLLED),
    ("Delivered to Governor at 10:38 a.m. on April 2, 2026",
                                                   NormalizedStatus.ENROLLED),
    ("Reported Signed by Governor on April 2, 2026",
                                                   NormalizedStatus.SIGNED),
    ("Session Law Chapter 299",                    NormalizedStatus.ENACTED),
])
def test_id_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, ID_PATTERNS) == expected


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
    ("Introduced, first reading, referred Appropriations Committee",
                                                NormalizedStatus.INTRODUCED),
    ("Committee Hearing 08:30",                 NormalizedStatus.IN_COMMITTEE),
    ("Reported back amended, do pass, amendment placed on calendar 23 0 0",
                                                NormalizedStatus.IN_COMMITTEE),
    ("Second reading, passed, yeas 83 nays 4", NormalizedStatus.PASSED_CHAMBER),
    ("Concurred",                              NormalizedStatus.PASSED_CHAMBER),
    ("Emergency clause carried",               NormalizedStatus.PASSED_CHAMBER),
    ("Delivered to Governor",                  NormalizedStatus.ENROLLED),
    ("Sent to Governor",                       NormalizedStatus.ENROLLED),
    ("Signed by President",                    NormalizedStatus.ENROLLED),
    ("Governor signed",                        NormalizedStatus.SIGNED),
    ("Filed with Secretary Of State 04/11",    NormalizedStatus.ENACTED),
    ("Failed in House",                        NormalizedStatus.FAILED),
    ("Refused to concur",                      NormalizedStatus.IN_COMMITTEE),
    ("Division A lost",                        NormalizedStatus.IN_COMMITTEE),
])
def test_nd_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, ND_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("Date of introduction",                         NormalizedStatus.INTRODUCED),
    ("Placed on General File",                       NormalizedStatus.IN_COMMITTEE),
    ("Advanced to Enrollment and Review Initial",    NormalizedStatus.IN_COMMITTEE),
    ("Quick priority bill",                          NormalizedStatus.IN_COMMITTEE),
    ("Provisions/portions of LB725 amended into LB889 by AM3058",
                                                        NormalizedStatus.IN_COMMITTEE),
    ("Passed on Final Reading 46-0-3",               NormalizedStatus.PASSED_CHAMBER),
    ("Dispensing of reading at large approved",      NormalizedStatus.PASSED_CHAMBER),
    ("President/Speaker signed",                     NormalizedStatus.ENROLLED),
    ("Presented to Governor on February 12, 2026",   NormalizedStatus.ENROLLED),
    ("Approved by Governor on February 17, 2026",    NormalizedStatus.ENACTED),
    ("Indefinitely postponed",                       NormalizedStatus.FAILED),
    ("Kauth FA345 withdrawn",                        NormalizedStatus.FAILED),
])
def test_ne_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, NE_PATTERNS) == expected


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
    ("Introduced, referred to House Corporations", NormalizedStatus.IN_COMMITTEE),
    ("Scheduled for hearing and/or consideration (01/20/2026)",
                                                    NormalizedStatus.IN_COMMITTEE),
    ("Committee recommended measure be held for further study",
                                                    NormalizedStatus.FAILED),
    ("Committee recommends passage",               NormalizedStatus.PASSED_CHAMBER),
    ("Proposed Substitute",                        NormalizedStatus.IN_COMMITTEE),
    ("Committee transferred to House Finance",     NormalizedStatus.IN_COMMITTEE),
    ("Committee postponed at request of sponsor (04/09/2026)",
                                                    NormalizedStatus.IN_COMMITTEE),
    ("Placed on House Calendar (03/17/2026)",      NormalizedStatus.IN_COMMITTEE),
    ("House read and passed",                      NormalizedStatus.PASSED_CHAMBER),
    ("House passed Sub A",                         NormalizedStatus.PASSED_CHAMBER),
    ("Senate passed Sub A in concurrence",         NormalizedStatus.PASSED_CHAMBER),
    ("Senate passed in concurrence",               NormalizedStatus.PASSED_CHAMBER),
    ("Transmitted to Governor",                    NormalizedStatus.ENROLLED),
    ("Effective without Governor's signature",     NormalizedStatus.ENACTED),
])
def test_ri_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, RI_PATTERNS) == expected


@pytest.mark.parametrize("text,expected", [
    ("First read in House and referred to",    NormalizedStatus.IN_COMMITTEE),
    ("Scheduled for hearing",                  NormalizedStatus.IN_COMMITTEE),
    ("Do Pass",                                NormalizedStatus.PASSED_CHAMBER),
    ("Do Pass Amended",                        NormalizedStatus.PASSED_CHAMBER),
    ("Signed by the Speaker",                  NormalizedStatus.ENROLLED),
    ("Delivered to the Governor",              NormalizedStatus.ENROLLED),
    ("Signed by the Governor",                 NormalizedStatus.SIGNED),
    ("Deferred to the 41st legislative day",   NormalizedStatus.FAILED),
])
def test_sd_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, SD_PATTERNS) == expected


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


@pytest.mark.parametrize("text,expected", [
    ("Bill Number Assigned",                    NormalizedStatus.INTRODUCED),
    ("H Received for Introduction",             NormalizedStatus.INTRODUCED),
    ("H Introduced and Referred to H09 - Minerals 59-2-1-0-0",
                                                NormalizedStatus.IN_COMMITTEE),
    ("H09 - Minerals:Recommend Amend and Do Pass 9-0-0-0-0",
                                                NormalizedStatus.IN_COMMITTEE),
    ("H COW:Passed",                           NormalizedStatus.IN_COMMITTEE),
    ("S Appointed JCC01 Members",              NormalizedStatus.IN_COMMITTEE),
    ("H Received for Concurrence",             NormalizedStatus.IN_COMMITTEE),
    (":Rerefer to S02 - Appropriations",       NormalizedStatus.IN_COMMITTEE),
    ("H 3rd Reading:Laid Back",                NormalizedStatus.IN_COMMITTEE),
    ("S 3rd Reading:Passed 31-0-0-0-0",        NormalizedStatus.PASSED_CHAMBER),
    ("H Concur:Passed 60-0-2-0-0",             NormalizedStatus.PASSED_CHAMBER),
    ("H Speaker Signed HEA No. 0016",          NormalizedStatus.ENROLLED),
    ("Governor Signed HEA No. 0016",           NormalizedStatus.SIGNED),
    ("Assigned Chapter Number 42",             NormalizedStatus.ENACTED),
    ("H See Mirror Bill SF0001",               NormalizedStatus.FAILED),
    ("H No report prior to CoW Cutoff",        NormalizedStatus.FAILED),
    ("H Did not Consider for Introduction",    NormalizedStatus.FAILED),
    ("S Motion to Suspend Rules Failed 13-18-0-0-0",
                                                NormalizedStatus.FAILED),
])
def test_wy_patterns(text: str, expected: NormalizedStatus) -> None:
    assert match_first(text, WY_PATTERNS) == expected
