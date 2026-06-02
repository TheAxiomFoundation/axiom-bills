from __future__ import annotations

from selectolax.parser import HTMLParser

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus, Session
from axiom_bills.jurisdictions.us_tn.bill.citations import extract
from axiom_bills.jurisdictions.us_tn.bill.kind import classify
from axiom_bills.jurisdictions.us_tn.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_bill_index,
    parse_range_urls,
    parse_sponsors,
    parse_versions,
    TennesseeIndexItem,
)


INDEX_HTML = """
<a href="/apps/Indexes/BillIndex?startNum=HB0001&amp;endNum=HB0100&amp;ga=114">HB0001 - HB0100</a>
<a href="https://wapp.capitol.tn.gov/apps/Indexes/BillIndex?startNum=SB0001&amp;endNum=SB0100&amp;ga=114">SB0001 - SB0100</a>
"""

RANGE_HTML = """
<table aria-label="Bill Index Table">
<tr><td>
<a href="https://wapp.capitol.tn.gov/apps/BillInfo/Default?BillNumber=HB0001&amp;ga=114"
   title="HB0001 by Lamberth - Education">HB0001</a>
</td></tr>
</table>
"""

DETAIL_HTML = """
<div id="udpBillInfo">
  <h2>
    <a href="https://capitol.tn.gov/Bills/114/Bill/HB0001.pdf">HB 0001</a>
    <small>
      <div>by <a href="https://wapp.capitol.tn.gov/apps/LegislatorInfo/Member?district=H44">*Lamberth</a></div>
      <div id="divCoPrimeSponsors" class="hidden-info">White, Slater</div>
    </small>
  </h2>
  <div id="divCaptionText">AN ACT to amend Tennessee Code Annotated, Title 4, Chapter 49 and Title 49.</div>
</div>
<div class="abstract-container">
Education - As introduced, enacts the "Education Freedom Act of 2025." - Amends TCA Title 4, Chapter 49 and Title 49.
</div>
<table id="gvBillActionHistory">
  <tr class="house"><th>HB0001</th><th>Date</th></tr>
  <tr class="house"><td>Intro., P1C.</td><td>01/14/2025</td></tr>
  <tr class="house"><td>Ref. to Education Committee -- Government Operations for Review</td><td>01/16/2025</td></tr>
  <tr class="house"><td>Passed H., Ayes 70, Nays 25</td><td>02/01/2025</td></tr>
</table>
<table id="gvCoActionHistory">
  <tr class="senate"><td>Introduced, Passed on First Consideration</td><td>01/14/2025</td></tr>
</table>
<div id="tabpanel-summary"><h3>Bill Summary</h3>This bill creates a scholarship program.</div>
"""


def test_tennessee_index_parsing() -> None:
    assert parse_range_urls(INDEX_HTML) == [
        "https://wapp.capitol.tn.gov/apps/Indexes/BillIndex?startNum=HB0001&endNum=HB0100&ga=114",
        "https://wapp.capitol.tn.gov/apps/Indexes/BillIndex?startNum=SB0001&endNum=SB0100&ga=114",
    ]

    item = parse_bill_index(RANGE_HTML)[0]

    assert item.number == "HB 1"
    assert item.roster_title == "Education"
    assert item.source_url == "https://wapp.capitol.tn.gov/apps/BillInfo/Default?BillNumber=HB0001&ga=114"


def test_tennessee_bill_parsing() -> None:
    session = Session(name="2025-2026 Tennessee 114th General Assembly")
    item = TennesseeIndexItem(
        compact_number="HB0001",
        number="HB 1",
        source_url="https://wapp.capitol.tn.gov/apps/BillInfo/Default?BillNumber=HB0001&ga=114",
    )
    bill = parse_bill(item, detail_html=DETAIL_HTML, session=session)

    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.subjects == ["Education"]
    assert bill.sponsors[0].name == "Lamberth"
    assert bill.sponsors[0].district == "H44"
    assert [s.name for s in bill.sponsors[1:]] == ["White", "Slater"]
    assert len(bill.actions) == 3
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.versions[0].format == "pdf"


def test_tennessee_kind_status_and_citations() -> None:
    tree = HTMLParser(DETAIL_HTML)

    assert parse_sponsors(tree)[0].role == "primary"
    assert parse_actions(tree)[0].chamber == Chamber.LOWER
    assert len(parse_versions(tree)) == 1
    assert classify("AN ACT making appropriations for state government") == BillKind.APPROPRIATIONS
    assert classify("A resolution to honor a champion") == BillKind.CEREMONIAL
    assert extract("Amends TCA Title 4, Chapter 49 and Title 49.") == [
        ("TCA Title 4, Chapter 49 and Title 49", "TCA Title 4, Chapter 49 and Title 49")
    ]
