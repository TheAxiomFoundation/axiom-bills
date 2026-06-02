from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_mt.bill.citations import extract
from axiom_bills.jurisdictions.us_mt.bill.kind import classify
from axiom_bills.jurisdictions.us_mt.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_subjects,
    parse_versions,
    session_from_api,
    sponsor_from_api,
)


SESSION = {
    "id": 2,
    "ordinals": "20251",
    "active": True,
    "startDate": "2025-01-06T00:00:00",
    "sineDieDate": "2025-04-30T14:30:00",
    "type": "REGULAR",
    "legislature": {"id": 2, "ordinals": "69", "endDate": "2026-12-31"},
}

BILL = {
    "id": 1372,
    "billNumber": 1,
    "sponsorId": 119,
    "billType": {"id": 1, "description": "House Bill", "code": "HB", "chamber": "HOUSE"},
    "draft": {
        "id": 1372,
        "draftNumber": "LC1374",
        "shortTitle": "Feed bill to fund 69th legislative session and prepare for 2027",
        "description": "An act appropriating money for legislative expenses.",
        "subjects": [
            {
                "subjectCode": {
                    "code": "APP",
                    "description": "Appropriations  (see also: State Finance)",
                }
            },
            {"subjectCode": {"code": "LEG", "description": "Legislature"}},
        ],
        "billStatuses": [
            {
                "timeStamp": "2024-12-06T16:12:00",
                "billStatusCode": {"name": "(H) Introduced", "chamber": "HOUSE"},
                "billProgressCategory": {"description": "In First House--Introduced"},
            },
            {
                "timeStamp": "2025-01-07T17:53:08.21331",
                "billStatusCode": {
                    "name": "(H) Committee Executive Action--Bill Passed",
                    "chamber": "HOUSE",
                },
                "billProgressCategory": {"description": "In First House Committee--Nontabled"},
            },
            {
                "timeStamp": "2025-01-30T08:07:35",
                "billStatusCode": {"name": "Chapter Number Assigned", "chamber": "HOUSE"},
                "billProgressCategory": {"description": "Became Law"},
            },
        ],
    },
}


def test_session_and_subject_parsing() -> None:
    session = session_from_api(SESSION)

    assert session.name == "20251 Montana Regular Session"
    assert session.start_date.isoformat() == "2025-01-06"
    assert parse_subjects(BILL["draft"]) == [
        "Appropriations (see also: State Finance)",
        "Legislature",
    ]


def test_actions_versions_and_sponsor_parsing() -> None:
    actions = parse_actions(BILL["draft"]["billStatuses"])
    versions = parse_versions([
        {
            "id": 267198,
            "fileName": "HB0001_1.pdf",
            "attributes": [
                {
                    "name": "DocumentLink",
                    "stringValue": "https://docs.legmt.gov/download-ticket?ticketId=abc",
                }
            ],
        }
    ])
    sponsor = sponsor_from_api({
        "firstName": "Llew",
        "lastName": "Jones",
        "politicalParty": {"code": "R"},
        "district": {"name": "HOUSE DISTRICT 18"},
    })

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert versions[0].format == "pdf"
    assert sponsor is not None
    assert sponsor.name == "Llew Jones"
    assert sponsor.party == "R"


def test_parse_bill_core_fields() -> None:
    bill = parse_bill(
        BILL,
        session=session_from_api(SESSION),
        session_ordinal="20251",
        sponsor=None,
        versions=[],
    )

    assert bill.jurisdiction == "us-mt"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.source_url == "https://bills.legmt.gov/#/bill/20251/HB1"
    assert bill.kind == BillKind.APPROPRIATIONS


def test_montana_kind_and_citations() -> None:
    assert classify("Budget and general fund appropriations") == BillKind.APPROPRIATIONS
    assert classify("Recognizing a championship team") == BillKind.CEREMONIAL
    assert extract("Amend section 15-30-2103 and 15-30-2104, MCA.") == [
        ("section 15-30-2103", "section 15-30-2103"),
        ("15-30-2104, MCA", "15-30-2104, MCA"),
    ]
