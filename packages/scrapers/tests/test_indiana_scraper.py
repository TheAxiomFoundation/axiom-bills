from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_in.bill.citations import extract
from axiom_bills.jurisdictions.us_in.bill.kind import classify
from axiom_bills.jurisdictions.us_in.bill.scrape import (
    correct_bill_identifier,
    parse_actions,
    parse_bill,
    session_from_api,
    session_number,
    unpaginate_items,
)


SESSION = {
    "name": "2026 Session 124 of the Indiana General Assembly",
    "startDate": "2026-01-05",
    "endDate": "2026-03-15",
}

BILL = {
    "billName": "HB1001",
    "displayName": "HB 1001",
    "type": "bill",
    "description": "Housing matters.",
    "originChamber": "House",
    "year": 2026,
    "authors": [{"firstName": "Chris", "lastName": "Campbell"}],
    "latestVersion": {
        "digest": "Housing matters. Amends IC 36-7-4-1106.",
        "subjects": [{"entry": "LOCAL GOVERNMENT"}],
    },
    "versions": [
        {
            "billName": "HB1001",
            "printVersionName": "HB1001.01.INTR",
            "stageVerbose": "Introduced",
            "link": "/2026/bills/hb1001/versions/HB1001.01.INTR",
        }
    ],
}

ACTIONS = [
    {
        "description": "First reading: referred to Committee on Ways and Means",
        "date": "2026-01-08T00:00:00",
        "chamber": {"name": "House"},
        "link": "/2026/bills/hb1001/actions/1",
    },
    {
        "description": "Third reading: passed; Roll Call 25: yeas 72, nays 21",
        "date": "2026-02-03",
        "chamber": {"name": "House"},
        "link": "/2026/bills/hb1001/actions/2",
    },
]


def test_indiana_bill_parsing() -> None:
    session = session_from_api(2026, SESSION)
    bill = parse_bill(BILL, ACTIONS, session=session, session_no=session_number(SESSION))

    assert session.name == "2026 Session 124 of the Indiana General Assembly"
    assert bill.number == "HB 1001"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "Housing matters."
    assert bill.subjects == ["LOCAL GOVERNMENT"]
    assert bill.sponsors[0].name == "Chris Campbell"
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.versions[0].source_url.endswith("/124/2026/house/bills/HB1001/HB1001.01.INTR.pdf")


def test_indiana_helpers_kind_citations_and_pagination() -> None:
    assert parse_actions(ACTIONS)[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert correct_bill_identifier("SC 2", "CRES") == "SCR 2"
    assert classify("Vehicle Bill") == BillKind.VEHICLE
    assert classify("Various fiscal matters") == BillKind.APPROPRIATIONS
    assert extract("A bill to amend Indiana Code and IC 36-7-4-1106.") == [
        ("IC 36-7-4-1106", "IC 36-7-4-1106"),
        ("Indiana Code", "Indiana Code"),
    ]

    pages = {
        "https://api.iga.in.gov/2026/bills?page=2": {"items": [{"billName": "SB1"}]},
    }
    payload = {
        "items": [{"billName": "HB1001"}],
        "nextLink": "/2026/bills?page=2",
    }
    assert [item["billName"] for item in unpaginate_items(payload, pages.__getitem__)] == ["HB1001", "SB1"]
