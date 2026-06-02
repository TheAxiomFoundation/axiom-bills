from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ga.bill.citations import extract
from axiom_bills.jurisdictions.us_ga.bill.kind import classify
from axiom_bills.jurisdictions.us_ga.bill.scrape import (
    bill_number,
    parse_actions,
    parse_bill,
    parse_sponsors,
    parse_versions,
    session_from_api,
)


SESSION = {
    "id": 1033,
    "isCurrent": True,
    "description": "2025-2026 Regular Session",
    "library": "http://www.legis.ga.gov/Legislation/20252026/",
}

DETAIL = {
    "id": 69281,
    "session": {"id": 1033, "isCurrent": True, "description": "2025-2026 Regular Session", "library": "20252026"},
    "chamber": 1,
    "number": "1",
    "title": "Pediatric Health Safe Storage Act; enact",
    "status": "House Second Readers",
    "firstReader": (
        "A BILL to amend Part 3 of Article 4 of Chapter 11 of Title 16 of the "
        "Official Code of Georgia Annotated, relating to carrying and possession of firearms."
    ),
    "suffix": "",
    "documentType": 1,
    "sponsors": [
        {"name": "Au, Michelle ", "sequence": 1, "sponsorType": 1, "district": "50th"},
        {"name": "Cooper, Sharon ", "sequence": 2, "sponsorType": 1, "district": "45th"},
    ],
    "versions": [{"id": 229744, "name": "LC 56 0217/a", "versionNumber": 2, "isCurrent": False}],
    "statusHistory": [
        {"date": "2025-01-15T10:15:29", "name": "House Second Readers"},
        {"date": "2025-01-14T11:42:47", "name": "House First Readers"},
        {"date": "2025-01-13T13:03:11", "name": "House Hopper"},
    ],
}


def test_session_and_bill_number() -> None:
    session = session_from_api(SESSION)

    assert session.name == "2025-2026 Regular Session (1033)"
    assert session.start_date.isoformat() == "2025-01-01"
    assert session.end_date.isoformat() == "2026-12-31"
    assert bill_number(DETAIL) == "HB 1"
    assert bill_number({**DETAIL, "chamber": 2, "documentType": 2, "number": "244"}) == "SR 244"


def test_parse_bill_core_fields() -> None:
    bill = parse_bill(DETAIL, session=session_from_api(SESSION))

    assert bill.jurisdiction == "us-ga"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "Pediatric Health Safe Storage Act; enact"
    assert bill.sponsors[0].name == "Au, Michelle"
    assert bill.source_url == "https://www.legis.ga.gov/legislation/69281"
    assert bill.versions[0].source_url == "https://www.legis.ga.gov/api/legislation/document/20252026/229744"


def test_parse_sponsors_versions_and_actions() -> None:
    sponsors = parse_sponsors(DETAIL)
    versions = parse_versions(DETAIL)
    actions = parse_actions(DETAIL)

    assert [sponsor.name for sponsor in sponsors] == ["Au, Michelle", "Cooper, Sharon"]
    assert [version.label for version in versions] == ["LC 56 0217/a"]
    assert [action.action_text for action in actions] == [
        "House Hopper",
        "House First Readers",
        "House Second Readers",
    ]
    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
    ]


def test_georgia_kind_and_citations() -> None:
    assert classify("Recognizing March as Red Cross Month in Georgia") == BillKind.CEREMONIAL
    assert classify("General appropriations; State Fiscal Year 2026") == BillKind.APPROPRIATIONS
    assert extract(
        "Amend O.C.G.A. § 16-11-101 and Code Section 20-2-690.1 of the Official Code of Georgia Annotated."
    ) == [
        ("O.C.G.A. § 16-11-101", "O.C.G.A. § 16-11-101"),
        (
            "Code Section 20-2-690.1 of the Official Code of Georgia Annotated",
            "Code Section 20-2-690.1 of the Official Code of Georgia Annotated",
        ),
    ]

