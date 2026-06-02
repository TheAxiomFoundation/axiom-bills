from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nd.bill.citations import extract
from axiom_bills.jurisdictions.us_nd.bill.scrape import (
    assembly_for_year,
    parse_bill,
    session_from_payload,
)


PAYLOAD = {
    "assembly": 69,
    "assembly_name": "69th Legislative Assembly",
    "biennium_start": 2025,
    "biennium_end": 2027,
}

ROW = {
    "name": "HB 1001",
    "number": "1001",
    "summary": "Relating to salaries of the governor and lieutenant governor.",
    "title": (
        "AN ACT to provide an appropriation for defraying the expenses of the office of "
        "the governor; to amend and reenact sections 54-07-04 and 54-08-03 of the North "
        "Dakota Century Code, relating to salaries of the governor and lieutenant governor."
    ),
    "chamber": "House",
    "url": "https://ndlegis.gov/assembly/69-2025/regular/bill-overview/bo1001.html",
    "sponsors": [{"name": "House Appropriations", "type": "committee", "primary": True}],
    "actions": [
        {
            "description": "Introduced, first reading, referred Appropriations Committee",
            "date": "2025-01-07T23:59:59",
            "chamber": "House",
        },
        {
            "description": "Second reading, passed, yeas 83 nays 4",
            "date": "2025-02-20T23:59:59",
            "chamber": "House",
        },
        {
            "description": "Delivered to Governor",
            "date": "2025-04-07T23:59:59",
            "chamber": "House",
        },
        {
            "description": "Governor signed",
            "date": "2025-04-11T23:59:59",
            "chamber": "House",
        },
        {
            "description": "Filed with Secretary Of State 04/11",
            "date": "2025-04-11T23:59:59",
            "chamber": "House",
        },
    ],
    "versions": [
        {
            "lc_number": "25.0145.01000",
            "description": "INTRODUCED",
            "document_url": "https://ndlegis.gov/assembly/69-2025/regular/documents/25-0145-01000.pdf",
        }
    ],
}


def test_assembly_for_year() -> None:
    assert assembly_for_year(2025) == "69-2025"
    assert assembly_for_year(2026) == "69-2025"
    assert assembly_for_year(2027) == "70-2027"


def test_session_from_payload() -> None:
    session = session_from_payload(PAYLOAD)

    assert session.name == "69th Legislative Assembly (2025-2027)"
    assert session.start_date.isoformat() == "2025-01-01"
    assert session.end_date.isoformat() == "2027-12-31"


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(ROW, session=session_from_payload(PAYLOAD))

    assert bill is not None
    assert bill.jurisdiction == "us-nd"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB 1001"
    assert bill.sponsors[0].name == "House Appropriations"
    assert bill.sponsors[0].role == "committee"
    assert bill.kind == BillKind.APPROPRIATIONS
    assert bill.versions[0].label == "INTRODUCED - 25.0145.01000"


def test_parse_bill_builds_actions() -> None:
    bill = parse_bill(ROW, session=session_from_payload(PAYLOAD))

    assert bill is not None
    statuses = [action.normalized_status for action in bill.actions]
    assert statuses == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.SIGNED,
        NormalizedStatus.ENACTED,
    ]


def test_extracts_north_dakota_citations() -> None:
    assert extract("Amend North Dakota Century Code section 54-07-04 and N.D.C.C. § 54-08-03.") == [
        ("North Dakota Century Code section 54-07-04", "N.D.C.C. § 54-07-04"),
        ("N.D.C.C. § 54-08-03", "N.D.C.C. § 54-08-03"),
    ]
