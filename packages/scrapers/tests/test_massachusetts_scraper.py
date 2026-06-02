from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ma.bill.citations import extract
from axiom_bills.jurisdictions.us_ma.bill.scrape import (
    general_court_for_year,
    parse_bill,
    session_for_general_court,
)


SUMMARY = {
    "BillNumber": "H3444",
    "DocketNumber": "HD2050",
    "Title": "An Act relative to s-license compliance",
    "GeneralCourtNumber": 194,
    "IsDocketBookOnly": False,
}

DETAIL = {
    **SUMMARY,
    "PrimarySponsor": {"Name": "James C. Arena-DeRosa", "Type": 1},
    "Cosponsors": [{"Name": "James C. Arena-DeRosa", "Type": 1}],
    "Pinslip": "By Representative Arena-DeRosa of Holliston.",
    "DocumentText": "Section 57 of Chapter 147 of the General Laws is hereby amended.",
    "Attachments": [{"Description": "Attachment", "DownloadUrl": "https://malegislature.gov/example.pdf"}],
}

ACTIONS = [
    {
        "Date": "2025-02-27T10:38:52.3833333",
        "Branch": "House",
        "Action": "Referred to the committee on Telecommunications, Utilities and Energy",
        "IsStricken": False,
    },
    {
        "Date": "2025-02-27T10:38:52.3833333",
        "Branch": "Senate",
        "Action": "Senate concurred",
        "IsStricken": False,
    },
    {
        "Date": "2025-04-30T14:29:25.14",
        "Branch": "Joint",
        "Action": "Hearing scheduled for 05/06/2025 from 11:00 AM-01:00 PM in A-2",
        "IsStricken": False,
    },
    {
        "Date": "2026-04-06T15:17:48.51",
        "Branch": "House",
        "Action": "Accompanied a study order, see H5323",
        "IsStricken": False,
    },
]


def test_session_helpers() -> None:
    assert general_court_for_year(2025) == 194
    assert general_court_for_year(2026) == 194
    assert general_court_for_year(2027) == 195
    assert session_for_general_court(194).name == "194th Massachusetts General Court (2025-2026)"


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(DETAIL, ACTIONS, summary=SUMMARY, session=session_for_general_court(194))

    assert bill is not None
    assert bill.jurisdiction == "us-ma"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "H3444"
    assert bill.title == "An Act relative to s-license compliance"
    assert bill.sponsors[0].name == "James C. Arena-DeRosa"
    assert bill.source_url == "https://malegislature.gov/Bills/194/H3444"
    assert bill.versions[0].source_url == "https://malegislature.gov/Bills/194/H3444.Html"
    assert bill.versions[1].format == "pdf"


def test_parse_bill_builds_actions() -> None:
    bill = parse_bill(DETAIL, ACTIONS, summary=SUMMARY, session=session_for_general_court(194))

    assert bill is not None
    statuses = [action.normalized_status for action in bill.actions]
    assert statuses == [
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.FAILED,
    ]


def test_extracts_massachusetts_citations() -> None:
    assert extract("Amend section 57 of Chapter 147 and M.G.L. c. 93A, § 2.") == [
        ("section 57 of Chapter 147", "M.G.L. c. 147, § 57"),
        ("M.G.L. c. 93A, § 2", "M.G.L. c. 93A, § 2"),
    ]
