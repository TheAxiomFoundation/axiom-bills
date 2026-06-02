from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_id.bill.scrape import (
    BillListItem,
    parse_bill_page,
    parse_list_items,
    session_for_year,
)


LIST_HTML = """
<table class="mini-data-table">
<tr id="billH0508">
<td><a href="/sessioninfo/2026/legislation/H0508">H0508</a>&nbsp;&nbsp;&nbsp;&nbsp;</td>
<td>Bike, ped projects, fed funds</td><td></td><td>LAW</td><td>+</td>
</tr>
</table>
"""

DETAIL_HTML = """
<table class="bill-table"><tr><td>H0508</td><td></td><td>by TRANSPORTATION AND DEFENSE COMMITTEE</td></tr></table>
<table class="bill-table"><tr><td>TRANSPORTATION - Amends and adds to existing law.</td></tr></table>
<p><a class="plain" id="H0508" href="/wp-content/uploads/sessioninfo/2026/legislation/H0508.pdf">Bill Text</a></p>
<table class="bill-table">
<tr><td></td><td>01/21</td><td>Introduced, read first time, referred to JRA for Printing</td><td></td></tr>
<tr><td></td><td>03/17</td><td>Rules Suspended: Ayes 66 Nays 0 - PASSED - 39-29-2 Title apvd - to Senate</td><td></td></tr>
<tr><td></td><td>04/02</td><td>Delivered to Governor at 10:38 a.m. on April 2, 2026</td><td></td></tr>
<tr><td></td><td></td><td>Reported Signed by Governor on April 2, 2026 Session Law Chapter 299 Effective: 07/01/2026</td><td></td></tr>
</table>
"""


def test_parse_list_items() -> None:
    items = parse_list_items(LIST_HTML)

    assert items[0].number == "H0508"
    assert items[0].title == "Bike, ped projects, fed funds"
    assert items[0].status == "LAW"
    assert items[0].url == "https://legislature.idaho.gov/sessioninfo/2026/legislation/H0508"


def test_session_for_year() -> None:
    session = session_for_year(2026)

    assert session.name == "2026 Idaho Legislature"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-01"


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem(
            number="H0508",
            title="Bike, ped projects, fed funds",
            url="https://legislature.idaho.gov/sessioninfo/2026/legislation/H0508",
            status="LAW",
        ),
        session=session_for_year(2026),
    )

    assert bill is not None
    assert bill.jurisdiction == "us-id"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "H0508"
    assert bill.title == "TRANSPORTATION - Amends and adds to existing law."
    assert bill.sponsors[0].name == "TRANSPORTATION AND DEFENSE COMMITTEE"
    assert bill.versions[0].source_url == (
        "https://legislature.idaho.gov/wp-content/uploads/sessioninfo/2026/legislation/H0508.pdf"
    )


def test_parse_bill_page_builds_actions() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem(
            number="H0508",
            title="Bike, ped projects, fed funds",
            url="https://legislature.idaho.gov/sessioninfo/2026/legislation/H0508",
            status="LAW",
        ),
        session=session_for_year(2026),
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.actions[2].normalized_status == NormalizedStatus.ENROLLED
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert bill.actions[-1].occurred_at.isoformat() == "2026-04-02T00:00:00-06:00"
