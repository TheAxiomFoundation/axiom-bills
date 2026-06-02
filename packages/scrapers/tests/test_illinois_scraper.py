from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_il.bill.citations import extract
from axiom_bills.jurisdictions.us_il.bill.kind import classify
from axiom_bills.jurisdictions.us_il.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_range_urls,
    parse_sponsors,
    parse_versions,
    session_for_general_assembly,
)


LANDING_HTML = """
<a href="/Legislation/RegularSession/SB?num1=0001&amp;num2=0100&amp;DocTypeID=SB&amp;GaId=18&amp;SessionId=114">0001 - 0100</a>
<a href="/Legislation/RegularSession/HB?num1=0001&amp;num2=0100&amp;DocTypeID=HB&amp;GaId=18&amp;SessionId=114">0001 - 0100</a>
<a href="/Legislation/RegularSession/HB?num1=0101&amp;num2=0200&amp;DocTypeID=HB&amp;GaId=17&amp;SessionId=112">old</a>
"""

LIST_HTML = """
<table class="table table-striped border">
  <tr>
    <td><a href="/Legislation/BillStatus?DocNum=1&amp;GAID=18&amp;DocTypeID=HB&amp;LegId=156928&amp;SessionID=114">HB0001</a></td>
    <td><a href="/Legislation/BillStatus?DocNum=1&amp;GAID=18&amp;DocTypeID=HB&amp;LegId=156928&amp;SessionID=114">HEMP CANNABINOIDS-MINORS</a></td>
  </tr>
</table>
"""

DETAIL_HTML = """
<h2>Bill Status of HB0001</h2>
<h2>HB0001 - 104th General Assembly</h2>
<h5 class="fw-bold">HEMP CANNABINOIDS-MINORS</h5>
<div id="sponsorDiv">
  <h5>House Sponsors</h5><span>Rep. </span>
  <span><a href="/House/Members/Details/3272">La Shawn K. Ford</a> and <a href="/House/Members/Details/3280">Rita Mayfield</a></span>
</div>
<div>
  <h5>Statutes Amended In Order of Appearance</h5>
  <div class="row ml-4"><div class="col-sm">New Act</div></div>
  <h5>Synopsis As Introduced</h5>
  <div class="list-group"><span class="list-group-item">Creates the Prevention of Use of Hemp Cannabinoid Products Act.</span></div>
</div>
<a href="/Legislation/BillStatus/FullText?GAID=18&amp;DocNum=1&amp;DocTypeID=HB&amp;LegId=156928&amp;SessionID=114">Full Text</a>
<table class="table table-striped border text-start">
  <tr><th>Date</th><th>Chamber</th><th>Action</th></tr>
  <tr><td>12/02/2024</td><td>House</td><td>Prefiled with Clerk by Rep. La Shawn K. Ford</td></tr>
  <tr><td>1/09/2025</td><td>House</td><td>First Reading</td></tr>
  <tr><td>1/09/2025</td><td>House</td><td>Referred to Rules Committee</td></tr>
  <tr><td>2/06/2025</td><td>House</td><td>Placed on Calendar Order of 2nd Reading</td></tr>
  <tr><td>2/25/2025</td><td>House</td><td>Added Co-Sponsor Rep. Rita Mayfield</td></tr>
  <tr><td>4/10/2025</td><td>House</td><td>House Concurs</td></tr>
  <tr><td>5/20/2025</td><td>House</td><td>Sent to the Governor</td></tr>
</table>
"""


def test_range_and_listing_parsing() -> None:
    session = session_for_general_assembly(104)
    ranges = parse_range_urls(LANDING_HTML, ga_id=18, session_id=114)
    items = parse_listing(LIST_HTML)

    assert session.name == "104th Illinois General Assembly (2025-2026)"
    assert ranges == [
        "https://www.ilga.gov/Legislation/RegularSession/HB?num1=0001&num2=0100&DocTypeID=HB&GaId=18&SessionId=114",
        "https://www.ilga.gov/Legislation/RegularSession/SB?num1=0001&num2=0100&DocTypeID=SB&GaId=18&SessionId=114",
    ]
    assert items[0].number == "HB 1"
    assert items[0].title == "HEMP CANNABINOIDS-MINORS"
    assert items[0].leg_id == 156928


def test_detail_actions_sponsors_and_versions() -> None:
    actions = parse_actions(DETAIL_HTML)
    sponsors = parse_sponsors(DETAIL_HTML)
    versions = parse_versions(DETAIL_HTML)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_BOTH,
        NormalizedStatus.ENROLLED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [sponsor.name for sponsor in sponsors] == ["La Shawn K. Ford", "Rita Mayfield"]
    assert versions[0].source_url == "https://www.ilga.gov/Legislation/BillStatus/FullText?GAID=18&DocNum=1&DocTypeID=HB&LegId=156928&SessionID=114"


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LIST_HTML)[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_general_assembly(104))

    assert bill.jurisdiction == "us-il"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "HEMP CANNABINOIDS-MINORS"
    assert bill.summary == "Creates the Prevention of Use of Hemp Cannabinoid Products Act."
    assert bill.subjects == ["New Act"]


def test_illinois_kind_and_citations() -> None:
    assert classify("APPROPRIATIONS-GENERAL FUNDS") == BillKind.APPROPRIATIONS
    assert classify("COMMENDS THE FIRE DEPARTMENT") == BillKind.CEREMONIAL
    assert extract("Amends 5 ILCS 100/5-45 and 77 Ill. Adm. Code 250. Public Act 103-0001.") == [
        ("5 ILCS 100/5-45", "5 ILCS 100/5-45"),
        ("77 Ill. Adm. Code 250", "77 Ill. Adm. Code 250"),
        ("Public Act 103-0001", "Public Act 103-0001"),
    ]
