from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ar.bill.citations import extract
from axiom_bills.jurisdictions.us_ar.bill.scrape import (
    BillListItem,
    parse_actions,
    parse_bill,
    parse_bill_list,
    parse_detail_fields,
    parse_session,
)


LIST_HTML = """
<html><body>
<h1>House Bills - Arkansas State Legislature</h1>
<p>95th General Assembly - Regular Session, 2025</p>
<div role="grid" aria-rowcount="3" data-per-page="20">
  <div class="row tableRow" role="row">
    <div role="gridcell">
      <a aria-label="Bill Number HB1001" href="/Bills/Detail?id=HB1001&amp;ddBienniumSession=2025%2F2025R">HB1001</a>
    </div>
    <div role="gridcell">AN ACT FOR THE ARKANSAS HOUSE OF REPRESENTATIVES APPROPRIATION FOR THE 2024-2025 FISCAL YEAR.</div>
    <div role="gridcell"><a aria-label="Sponsor:House Management">House Management</a></div>
    <div role="gridcell">
      <a aria-label="HB1001.pdf" href="/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001.pdf">Bill</a>
      <a aria-label="Act3.PDF" href="/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&amp;file=3.pdf&amp;ddBienniumSession=2025%2F2025R">Act</a>
      <a aria-label="HB1001 Status History" href="/Bills/Detail?id=HB1001&amp;ddBienniumSession=2025%2F2025R#status">Status</a>
    </div>
  </div>
  <div class="row tableRowAlt" role="row">
    <div role="gridcell">
      <a aria-label="Bill Number HB1002" href="/Bills/Detail?id=HB1002&amp;ddBienniumSession=2025%2F2025R">HB1002</a>
    </div>
    <div role="gridcell">THE GENERAL APPROPRIATION ACT FOR THE 2025-2026 FISCAL YEAR.</div>
    <div role="gridcell"><a aria-label="Sponsor:Joint Budget Committee">Joint Budget Committee</a></div>
    <div role="gridcell">
      <a aria-label="HB1002.pdf" href="/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1002.pdf">Bill</a>
    </div>
  </div>
</div>
</body></html>
"""

DETAIL_HTML = """
<html><body>
<div role="grid">
  <div class="row tableRow" role="row">
    <div role="gridcell">Bill Number:</div>
    <div role="gridcell"><a href="/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001.pdf">PDF</a> HB1001</div>
  </div>
  <div class="row tableRowAlt" role="row">
    <div role="gridcell">Status:</div>
    <div role="gridcell">House -- Notification that HB1001 is now Act 3</div>
  </div>
  <div class="row tableRow" role="row">
    <div role="gridcell">Originating Chamber:</div>
    <div role="gridcell">House</div>
  </div>
  <div class="row tableRowAlt" role="row">
    <div role="gridcell">Lead Sponsor:</div>
    <div role="gridcell"><a>House Management</a></div>
  </div>
</div>
<h3>Bill Status History</h3>
<div role="grid" aria-rowcount="4">
  <div class="row tableRow" role="row">
    <div role="gridcell">House</div>
    <div role="gridcell">1/27/2025&nbsp;5:40:27 PM</div>
    <div role="gridcell">Notification that HB1001 is now Act 3</div>
    <div role="gridcell"></div>
  </div>
  <div class="row tableRowAlt" role="row">
    <div role="gridcell">House</div>
    <div role="gridcell">1/13/2025&nbsp;4:43:19 PM</div>
    <div role="gridcell">Read the first time, rules suspended, read the second time and referred to the Committee on JOINT BUDGET COMMITTEE</div>
    <div role="gridcell"></div>
  </div>
  <div class="row tableRow" role="row">
    <div role="gridcell">House</div>
    <div role="gridcell">1/22/2025&nbsp;1:48:07 PM</div>
    <div role="gridcell">Read the third time and passed and ordered transmitted to the Senate.</div>
    <div role="gridcell">House Votes</div>
  </div>
</div>
<div role="grid" aria-rowcount="2">
  <div class="row tableRow" role="row">
    <div role="gridcell">Chamber: House</div>
    <div role="gridcell">Amendment Number: H1</div>
    <div role="gridcell">House Management</div>
    <div role="gridcell">1/14/2025 4:03:43 PM</div>
    <div role="gridcell"><a aria-label="Download PDF" href="/Home/FTPDocument?path=%2FAMEND%2F2025R%2FPublic%2FHB1001-H1.pdf">PDF</a></div>
  </div>
</div>
</body></html>
"""

PREVIOUS_HTML = """
<html><body>
  <a href="/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001%2FHB1001_011320251439.pdf">HB1001 Original</a>
  <a href="/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001%2FHB1001011520250942.pdf">HB1001 V2</a>
</body></html>
"""


def test_parse_session_from_official_heading() -> None:
    session = parse_session(LIST_HTML)

    assert session.name == "95th General Assembly - Regular Session, 2025"
    assert session.start_date.isoformat() == "2025-01-01"
    assert session.end_date.isoformat() == "2025-12-31"
    assert session.is_current is True


def test_parse_bill_list_extracts_rows_and_documents() -> None:
    items = parse_bill_list(LIST_HTML)

    assert [item.number for item in items] == ["HB1001", "HB1002"]
    assert items[0].sponsor == "House Management"
    assert items[0].detail_url.endswith("/Bills/Detail?id=HB1001&ddBienniumSession=2025%2F2025R")
    assert items[0].bill_url.endswith("/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001.pdf")
    assert "file=3.pdf" in (items[0].act_url or "")


def test_parse_detail_fields_and_actions() -> None:
    fields = parse_detail_fields(DETAIL_HTML)
    actions = parse_actions(DETAIL_HTML, source_url="https://www.arkleg.state.ar.us/Bills/Detail?id=HB1001")

    assert fields["Bill Number"] == "HB1001"
    assert fields["Lead Sponsor"] == "House Management"
    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.LOWER


def test_parse_bill_builds_core_fields_versions_and_kind() -> None:
    item = BillListItem(
        number="HB1001",
        title="AN ACT FOR THE ARKANSAS HOUSE OF REPRESENTATIVES APPROPRIATION FOR THE 2024-2025 FISCAL YEAR.",
        sponsor="House Management",
        detail_url="https://www.arkleg.state.ar.us/Bills/Detail?id=HB1001&ddBienniumSession=2025%2F2025R",
        bill_url="https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FBills%2F2025R%2FPublic%2FHB1001.pdf",
        act_url="https://www.arkleg.state.ar.us/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&file=3.pdf&ddBienniumSession=2025%2F2025R",
    )
    bill = parse_bill(item, DETAIL_HTML, PREVIOUS_HTML, session=parse_session(LIST_HTML))

    assert bill.jurisdiction == "us-ar"
    assert bill.number == "HB1001"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "House Management"
    assert bill.kind == BillKind.APPROPRIATIONS
    assert {version.label for version in bill.versions} >= {"current", "act", "amendment", "original", "v2"}


def test_extracts_arkansas_citations() -> None:
    assert extract("Amend Arkansas Code § 5-4-201 and A.C.A. 6-20-2305. See Act 123 of 2025.") == [
        ("Arkansas Code § 5-4-201", "Arkansas Code § 5-4-201"),
        ("A.C.A. 6-20-2305", "A.C.A. 6-20-2305"),
        ("Act 123 of 2025", "Act 123 of 2025"),
    ]
