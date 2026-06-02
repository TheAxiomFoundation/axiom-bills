from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nh.bill.citations import extract
from axiom_bills.jurisdictions.us_nh.bill.kind import classify
from axiom_bills.jurisdictions.us_nh.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_sponsors,
    parse_versions,
    session_for_years,
)
from selectolax.parser import HTMLParser


LISTING_HTML = """
<div id="dvResultsWrap">
  <div style="background-color: #EBEBEB">
    <div class="BS-ResultsCol1BN">
      <a href="billinfo.aspx?id=1617&inflect=2" target="_blank">HB1564-FN</a><br />
      Year: 2026
    </div>
    <div class="BS-ResultsCol2"><b>Title:</b>&nbsp;&nbsp;
      <span>relative to access to the centralized voter registration database.</span>
    </div>
    <div><div class="BS-ResultsCol1">General Status:</div><div class="BS-ResultsCol2">HOUSE</div></div>
  </div>
</div>
"""

DETAIL_HTML = """
<div id="dvBillNo">SB549-FN</div>
<div id="dvTitle"><b>Title:</b>&nbsp;(New Title) requiring syringe disposal options.</div>
<div id="dvSponosrs"><b>Sponsors:</b>&nbsp;
  <a title="Sen. Keith Murphy (R)" class="SenMember"><i><b>(Prime)</b></i> Keith Murphy (R)</a>,
  <a title="Sen. Howard Pearl (r)" class="SenMember">Pearl (r)</a>
</div>
<div id="pageBody_dvHouseStat"><div class="dBarBodyComm"><b>Committee:</b>&nbsp;Health, Human Services and Elderly Affairs</div></div>
<div id="pageBody_dvSenStat"><div class="sdBarBodyComm"><b>Committee:</b>&nbsp;Health and Human Services</div></div>
<select id="pageBody_ddlBillVersions">
  <option value="Select a Bill Version -->">Select a Bill Version --></option>
  <option value="22201">Introduced</option>
  <option value="33413">CHAPTERED FINAL VERSION</option>
</select>
<div id="pageBody_pnlDocket">
  <div style="clear:both"><div class="dvDocketC1">S</div><div class="dvDocketC2">Introduced 01/07/2026 and Referred to Health and Human Services</div></div>
  <div style="clear:both"><div class="dvDocketC1">S</div><div class="dvDocketC2">Ought to Pass with Amendments 03/12/2026</div></div>
  <div style="clear:both"><div class="dvDocketC1">H</div><div class="dvDocketC2">Enrolled (in recess of) 05/14/2026</div></div>
  <div style="clear:both"><div class="dvDocketC1">S</div><div class="dvDocketC2">Signed by the Governor on 05/28/2026; Chapter 106</div></div>
</div>
"""


def test_listing_and_session_parsing() -> None:
    items = parse_listing(LISTING_HTML)
    session = session_for_years(2025, 2026)

    assert session.name == "2025-2026 New Hampshire General Court"
    assert items[0].number == "HB 1564-FN"
    assert items[0].detail_url == "https://gc.nh.gov/bill_status/billinfo.aspx?id=1617&inflect=2"
    assert items[0].status == "HOUSE"


def test_detail_actions_sponsors_and_versions() -> None:
    tree = HTMLParser(DETAIL_HTML)
    actions = parse_actions(tree)
    versions = parse_versions(tree)
    sponsors = parse_sponsors(tree)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.UPPER
    assert versions[0].source_url == "https://gc.nh.gov/bill_status/pdf.aspx?id=22201&q=billVersion"
    assert sponsors[0].name == "Keith Murphy"
    assert sponsors[0].role == "primary"
    assert sponsors[1].party == "R"


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LISTING_HTML)[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_years(2025, 2026))

    assert bill.jurisdiction == "us-nh"
    assert bill.number == "SB 549-FN"
    assert bill.chamber == Chamber.LOWER
    assert "syringe disposal" in (bill.title or "")
    assert bill.subjects == [
        "Health, Human Services and Elderly Affairs",
        "Health and Human Services",
    ]


def test_new_hampshire_kind_and_citations() -> None:
    assert classify("making appropriations for the state budget") == BillKind.APPROPRIATIONS
    assert classify("recognizing a championship team") == BillKind.CEREMONIAL
    assert extract("Amend RSA 21-P:12 and the New Hampshire Revised Statutes Annotated.") == [
        ("RSA 21-P:12", "RSA 21-P:12"),
        ("New Hampshire Revised Statutes Annotated", "New Hampshire Revised Statutes Annotated"),
    ]
