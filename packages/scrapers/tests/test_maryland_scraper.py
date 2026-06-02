from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_md.bill.scrape import parse_bill


ROW = {
    "BillNumber": "HB0002",
    "SponsorPrimary": "Delegate Griffith",
    "Sponsors": [{"Name": "Delegate Griffith"}],
    "Synopsis": "Increasing a subtraction modification under the Maryland income tax.",
    "Title": "Subtraction Modification - Public Safety Retirement Income",
    "Status": "In the House - Hearing 1/20 at 1:00 p.m.",
    "FirstReadingDateHouseOfOrigin": "2026-01-14",
    "HearingDateTimePrimaryHouseOfOrigin": "2026-01-20T13:00:00",
    "ReportDateHouseOfOrigin": None,
    "ReportActionHouseOfOrigin": "",
    "SecondReadingDateHouseOfOrigin": None,
    "SecondReadingActionHouseOfOrigin": "",
    "ThirdReadingDateHouseOfOrigin": None,
    "ThirdReadingActionHouseOfOrigin": "",
    "FirstReadingDateOppositeHouse": None,
    "HearingDateTimePrimaryOppositeHouse": None,
    "ReportDateOppositeHouse": None,
    "ReportActionOppositeHouse": "",
    "SecondReadingDateOppositeHouse": None,
    "SecondReadingActionOppositeHouse": "",
    "ThirdReadingDateOppositeHouse": None,
    "ThirdReadingActionOppositeHouse": "",
    "PassedByMGA": False,
    "BroadSubjects": [{"Code": "q3", "Name": "Taxes - Income"}],
    "NarrowSubjects": [{"Code": "incomet", "Name": "Income Tax"}],
    "StatusCurrentAsOf": "2026-02-04T17:45:08.947",
}


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(ROW, "2026 Regular Session", 2026)

    assert bill is not None
    assert bill.jurisdiction == "us-md"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB0002"
    assert bill.title == "Subtraction Modification - Public Safety Retirement Income"
    assert bill.summary == "Increasing a subtraction modification under the Maryland income tax."
    assert bill.subjects == ["Taxes - Income", "Income Tax"]
    assert bill.sponsors[0].name == "Delegate Griffith"
    assert bill.source_url == (
        "https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/hb0002?ys=2026RS"
    )


def test_parse_bill_builds_actions_and_statuses() -> None:
    bill = parse_bill(ROW, "2026 Regular Session", 2026)

    assert bill is not None
    assert len(bill.actions) == 3
    assert bill.actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.actions[1].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.actions[-1].action_text == "In the House - Hearing 1/20 at 1:00 p.m."


def test_parse_bill_handles_passed_by_mga() -> None:
    row = {
        **ROW,
        "BillNumber": "SB0123",
        "PassedByMGA": True,
        "Status": "Passed by the General Assembly",
    }

    bill = parse_bill(row, "2026 Regular Session", 2026)

    assert bill is not None
    assert bill.chamber == Chamber.UPPER
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENROLLED
