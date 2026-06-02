from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_sd.bill.scrape import parse_bill, session_from_row


SESSION_ROW = {
    "SessionId": 71,
    "Year": "2026",
    "YearString": "2026",
    "LongName": "One Hundred First Session",
    "StartDate": "2026-01-13T00:00:00-06:00",
    "CurrentSession": True,
}

DETAIL = {
    "BillId": 26699,
    "BillType": "HB",
    "BillNumber": 1001,
    "Title": "provide for prescribed burning of state-owned land.",
    "BillSponsor": [{"Name": "Rep. Example"}],
    "BillCommitteeSponsor": (
        'The Chair of the Committee on <a href="https://sdlegislature.gov/Session/Committee/1260/Detail">'
        "Agriculture and Natural Resources</a>"
    ),
    "Keywords": [{"Keyword": "Public Health and Safety"}, {"Keyword": "Property"}],
}

SUMMARY = {
    "BillId": 26699,
    "BillType": "HB",
    "BillNumber": "1001",
    "Title": "provide for prescribed burning of state-owned land.",
}

ACTION_ROWS = [
    {
        "DocumentId": 291894,
        "StatusText": "First read in House and referred to",
        "ActionDate": "2026-01-13T12:00:00-06:00",
        "ActionCommittee": {"Body": "H"},
        "AssignedCommittee": {"FullName": "House Agriculture and Natural Resources"},
        "ShowAssignedCommittee": True,
        "Vote": None,
    },
    {
        "DocumentId": 306483,
        "StatusText": "Signed by the Governor",
        "ActionDate": "2026-03-09T14:00:00-05:00",
        "ActionCommittee": {"Body": "H"},
        "Vote": None,
    },
]

VERSION_ROWS = [
    {
        "DocumentId": 291304,
        "BillVersion": "Introduced",
        "DocumentDate": "2025-12-19T16:31:05.527-06:00",
    },
    {
        "DocumentId": 305073,
        "BillVersion": "Enrolled",
        "DocumentDate": "2026-02-26T12:08:40.447-06:00",
    },
]


def test_session_from_row() -> None:
    session = session_from_row(SESSION_ROW)

    assert session.name == "One Hundred First Session"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-13"
    assert session.end_date is not None
    assert session.end_date.isoformat() == "2026-12-31"
    assert session.is_current is True


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(
        DETAIL,
        SUMMARY,
        ACTION_ROWS,
        VERSION_ROWS,
        session=session_from_row(SESSION_ROW),
    )

    assert bill is not None
    assert bill.jurisdiction == "us-sd"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB1001"
    assert bill.title == "provide for prescribed burning of state-owned land."
    assert bill.subjects == ["Public Health and Safety", "Property"]
    assert bill.sponsors[0].name == "Rep. Example"
    assert bill.sponsors[1].role == "committee"
    assert bill.source_url == "https://sdlegislature.gov/Session/Bill/26699"


def test_parse_bill_builds_actions_and_versions() -> None:
    bill = parse_bill(
        DETAIL,
        SUMMARY,
        ACTION_ROWS,
        VERSION_ROWS,
        session=session_from_row(SESSION_ROW),
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert "House Agriculture and Natural Resources" in bill.actions[0].action_text
    assert bill.actions[-1].normalized_status == NormalizedStatus.SIGNED
    assert bill.versions[0].label == "Introduced"
    assert bill.versions[0].source_url == "https://mylrc.sdlegislature.gov/api/Documents/291304.pdf"
