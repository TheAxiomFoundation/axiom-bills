from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ut.bill.scrape import parse_bill, session_from_id


ROW = {
    "year": "2026",
    "sessionID": "2026GS",
    "billNumber": "HB0001",
    "billNumberLong": "HB0001",
    "shortTitle": "Public Education Base Budget Amendments",
    "primeSponsorName": "Rep. Whyte, Stephen L.",
    "floorSponsorName": "Sen. Balderree, Heidi",
    "generalProvisions": "This bill supplements public education appropriations.",
    "highlightedProvisions": "This bill:<hr><ltbullet>sets the WPU value.",
    "actionHistoryList": [
        {
            "description": "House/ 1st reading (Introduced)",
            "actionDate": "2026-01-20 15:38:22.000",
            "actionClass": "H",
        },
        {
            "description": "Governor Signed",
            "actionDate": "2026-01-31 23:18:35.990",
            "actionClass": "G",
        },
    ],
    "billVersionList": [
        {
            "subjectList": [{"description": "Education"}],
            "sectionAffectedList": [{"secNo": "53F-2-301"}],
            "coSponsorList": [{"sponsorName": "Rep. Example"}],
            "billDocs": [
                {
                    "shortDesc": "Introduced",
                    "url": "/Session/2026/bills/introduced/HB0001.xml",
                }
            ],
        }
    ],
}


def test_session_from_id() -> None:
    session = session_from_id("2026GS")

    assert session.name == "2026 General Session"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-01"


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(ROW)

    assert bill is not None
    assert bill.jurisdiction == "us-ut"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB0001"
    assert bill.title == "Public Education Base Budget Amendments"
    assert bill.subjects == ["Education", "Utah Code 53F-2-301"]
    assert bill.sponsors[0].name == "Rep. Whyte, Stephen L."
    assert bill.sponsors[1].role == "floor"
    assert bill.sponsors[2].role == "cosponsor"
    assert bill.source_url == "https://le.utah.gov/~2026/bills/static/HB0001.html"


def test_parse_bill_builds_actions_and_versions() -> None:
    bill = parse_bill(ROW)

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[-1].normalized_status == NormalizedStatus.SIGNED
    assert bill.versions[0].label == "Introduced"
    assert bill.versions[0].source_url == (
        "https://le.utah.gov/Session/2026/bills/introduced/HB0001.xml"
    )
