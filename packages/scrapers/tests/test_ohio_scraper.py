from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_oh.bill.scrape import parse_bill, parse_session


SESSION = {
    "name": "2025 - Regular Session",
    "current": True,
    "active": True,
    "id": "general_assembly_136",
    "start": "2025-01-06",
    "end": "2026-12-31",
}

ROW = {
    "name": "H. B. No. 1",
    "chamber": "House",
    "short_title": "Enact Ohio Property Protection Act",
    "long_title": (
        "To amend sections 319.202, 5301.256, and 5323.02 of the "
        "Revised Code to modify real property acquisition law."
    ),
    "number": "hb1",
    "governor_signed_date": None,
    "concurrence_date": None,
    "effective_date": None,
    "sponsors": [
        {
            "full_name": "Angela N. King",
            "district": "84",
            "party": "party_republican_1",
        }
    ],
    "cosponsors": [{"full_name": "Sean P. Brennan", "district": "14"}],
    "subjects": [{"primary": "Property", "secondary": "Real Estate"}],
}


def test_parse_session_extracts_current_session() -> None:
    session = parse_session(SESSION)

    assert session.name == "2025 - Regular Session"
    assert session.is_current is True
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2025-01-06"


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(ROW, SESSION, action_rows=[], document_rows=[])

    assert bill is not None
    assert bill.jurisdiction == "us-oh"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB1"
    assert bill.title.startswith("To amend sections")
    assert bill.subjects == ["Property", "Real Estate"]
    assert bill.sponsors[0].name == "Angela N. King"
    assert bill.sponsors[0].party == "Republican"
    assert bill.sponsors[1].role == "cosponsor"
    assert bill.source_url == "https://www.legislature.ohio.gov/legislation/136/hb1"


def test_parse_bill_builds_actions_and_versions() -> None:
    bill = parse_bill(
        ROW,
        SESSION,
        action_rows=[
            {
                "chamber": "House",
                "occurred": "2025-01-23T19:21:36-05:00",
                "description": "Introduced",
                "action": "Introduced",
                "committee": "",
            },
            {
                "chamber": "House",
                "occurred": "2025-01-28T17:48:44-05:00",
                "description": "Refer to Committee",
                "action": "Refer to Committee",
                "committee": "Public Safety",
            },
        ],
        document_rows=[
            {
                "version": "As Introduced",
                "version_number": 0,
                "download": "/api/v2/general_assembly_136/legislation/hb1/00_IN/pdf/",
            }
        ],
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].action_text == "Refer to Committee: Public Safety"
    assert bill.actions[1].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.versions[0].label == "As Introduced"
    assert bill.versions[0].format == "pdf"
