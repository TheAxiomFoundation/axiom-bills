from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_or.bill.scrape import parse_measure, parse_session


SESSION_ROW = {
    "SessionKey": "2026R1",
    "SessionName": "2026 Regular Session",
    "BeginDate": "2026-01-12T00:00:00",
    "EndDate": "2026-03-08T00:00:00",
    "DefaultSession": False,
}

MEASURE_ROW = {
    "SessionKey": "2026R1",
    "MeasurePrefix": "HB",
    "MeasureNumber": 4002,
    "CatchLine": "Directs state agencies to take specified actions.",
    "MeasureSummary": "\tDigest: Directs agencies to take specified actions.",
    "RelatingTo": "Relating to tax credits.",
    "CurrentLocation": "Filed with Secretary of State",
    "ModifiedDate": "2026-03-05T16:54:28",
}


def test_parse_session_extracts_dates() -> None:
    session = parse_session(SESSION_ROW)

    assert session.name == "2026 Regular Session"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-12"
    assert session.end_date is not None
    assert session.end_date.isoformat() == "2026-03-08"


def test_parse_measure_extracts_core_fields() -> None:
    bill = parse_measure(
        MEASURE_ROW,
        "2026 Regular Session",
        action_rows=[],
        sponsor_rows=[
            {
                "LegislatoreCode": "Rep Speaker Fahey",
                "CommitteeCode": None,
                "SponsorLevel": "Chief",
                "SponsorType": "Member",
                "PrintOrder": "1",
            }
        ],
        document_rows=[
            {
                "VersionDescription": "Introduced",
                "DocumentUrl": (
                    "https://olis.oregonlegislature.gov/liz/2026R1/"
                    "Downloads/MeasureDocument/HB4002/Introduced"
                ),
                "CreatedDate": "2026-01-28T15:25:24.76",
            }
        ],
    )

    assert bill is not None
    assert bill.jurisdiction == "us-or"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB4002"
    assert bill.title == "Relating to tax credits."
    assert bill.summary == "Digest: Directs agencies to take specified actions."
    assert bill.sponsors[0].name == "Rep Speaker Fahey"
    assert bill.versions[0].label == "Introduced"
    assert bill.source_url == "https://olis.oregonlegislature.gov/liz/2026R1/Measures/Overview/HB4002"


def test_parse_measure_builds_history_actions() -> None:
    bill = parse_measure(
        MEASURE_ROW,
        "2026 Regular Session",
        action_rows=[
            {
                "ActionDate": "2026-01-12T09:15:00",
                "Chamber": "H",
                "ActionText": "Introduction and first reading. Referred to Speaker's desk.",
            },
            {
                "ActionDate": "2026-02-18T10:00:00",
                "Chamber": "H",
                "ActionText": "Third reading. Carried by Fahey. Passed.",
            },
        ],
        sponsor_rows=[],
        document_rows=[],
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
