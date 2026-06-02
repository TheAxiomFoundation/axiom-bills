from __future__ import annotations

from datetime import datetime

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_de.bill.scrape import parse_feed_item


def test_parse_feed_item_extracts_core_fields() -> None:
    item = {
        "GeneralAssemblySession": 153,
        "Title": "HB 430",
        "LongTitle": "AN ACT TO AMEND TITLE 30 OF THE DELAWARE CODE RELATING TO TAXES.",
        "Synopsis": "This Act changes tax administration.",
        "Link": "https://legis.delaware.gov/BillDetail?legislationId=143349",
        "Actions": [
            (
                NormalizedStatus.INTRODUCED,
                "Introduced",
                datetime.fromisoformat("2026-05-19T12:46:59"),
            )
        ],
    }

    bill = parse_feed_item(item, "153th General Assembly (2025-2026)")

    assert bill is not None
    assert bill.jurisdiction == "us-de"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB430"
    assert bill.title == "AN ACT TO AMEND TITLE 30 OF THE DELAWARE CODE RELATING TO TAXES."
    assert bill.summary == "This Act changes tax administration."
    assert bill.source_url.endswith("legislationId=143349")
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED


def test_parse_feed_item_handles_senate_bill() -> None:
    item = {
        "GeneralAssemblySession": 153,
        "Title": "SB 326",
        "LongTitle": "AN ACT TO AMEND TITLE 26 OF THE DELAWARE CODE.",
        "Synopsis": "Utility regulation changes.",
        "Link": "https://legis.delaware.gov/BillDetail?legislationId=143336",
        "Actions": [(NormalizedStatus.SIGNED, "Governor signed", None)],
    }

    bill = parse_feed_item(item, "153th General Assembly (2025-2026)")

    assert bill is not None
    assert bill.chamber == Chamber.UPPER
    assert bill.number == "SB326"
    assert bill.actions[0].normalized_status == NormalizedStatus.SIGNED


def test_parse_feed_item_skips_amendment_titles() -> None:
    item = {
        "GeneralAssemblySession": 153,
        "Title": "HA 1 to HB 165",
        "Link": "https://legis.delaware.gov/BillDetail?legislationId=143348",
        "Actions": [],
    }

    assert parse_feed_item(item, "153th General Assembly (2025-2026)") is None
