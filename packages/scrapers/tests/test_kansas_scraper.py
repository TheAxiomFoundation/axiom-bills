from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ks.bill.scrape import parse_listing_row


ROW = {
    "BILLNO": "HB2347",
    "SHORTTITLE": (
        "Changing the culpability required for certain types of theft and "
        "increasing the criminal penalty for theft."
    ),
}

HISTORY = [
    {
        "chamber": "House",
        "occurred_datetime": "2025-01-15T09:15:00",
        "status": "Introduced on Wednesday, January 15, 2025",
    },
    {
        "chamber": "House",
        "occurred_datetime": "2026-02-02T13:59:13",
        "status": "Enrolled and presented to Governor on Monday, February 2, 2026",
    },
    {
        "chamber": "House",
        "occurred_datetime": "2026-02-06T13:04:03",
        "status": "Approved by Governor on Thursday, February 5, 2026",
    },
]


def test_parse_listing_row_extracts_core_fields() -> None:
    bill = parse_listing_row(ROW, HISTORY)

    assert bill is not None
    assert bill.jurisdiction == "us-ks"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB2347"
    assert bill.title.startswith("Changing the culpability")
    assert bill.source_url == "https://www.kslegislature.gov/li/b2025_26/measures/HB2347/"


def test_parse_listing_row_builds_sorted_actions() -> None:
    bill = parse_listing_row(ROW, list(reversed(HISTORY)))

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[-1].normalized_status == NormalizedStatus.SIGNED


def test_parse_listing_row_handles_senate_bill() -> None:
    bill = parse_listing_row({"BILLNO": "SB335", "SHORTTITLE": "A senate bill."}, [])

    assert bill is not None
    assert bill.chamber == Chamber.UPPER
