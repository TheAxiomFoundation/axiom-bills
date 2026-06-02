from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_hi.bill.citations import extract
from axiom_bills.jurisdictions.us_hi.bill.kind import classify
from axiom_bills.jurisdictions.us_hi.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_measure_fields,
    parse_report,
    parse_versions,
    session_for_year,
)


REPORT_HTML = """
<table id="GridViewReports">
  <tr><th>PDF</th><th>Measure Status</th><th>Current Status</th><th>Introducers</th><th>Current Referral</th><th>Companion</th></tr>
  <tr>
    <td><a href="/sessions/session2026/bills/HB1_.pdf">pdf</a></td>
    <td>
      <a class="report" href="https://www.capitol.hawaii.gov/session/measure_indiv.aspx?billtype=HB&amp;billnumber=1&amp;year=2026">HB1</a>
      <span id="GridViewReports_Label1_0">State Building Code Council; Duties; Recommendations; Analysis</span>
      <span id="GridViewReports_Label7_0">RELATING TO BUILDING CODES.</span>
      <span id="GridViewReports_Label2_0">Amends responsibilities of the State Building Code Council.</span>
    </td>
    <td>(<span>H</span>) <span>2/5/2025</span>- <span>The committee(s) on HSG recommend(s) that the measure be deferred.</span></td>
    <td>MATAYOSHI, CHUN</td>
    <td>HSG, CPC, FIN</td>
    <td>SB120</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<div class="measure-number"><a class="measure-header">HB1</a></div>
<table id="measure-info">
  <tr><th>Measure Title:</th><td><span>RELATING TO BUILDING CODES.</span></td></tr>
  <tr><th>Report Title:</th><td><span>State Building Code Council; Duties; Recommendations; Analysis</span></td></tr>
  <tr><th>Description:</th><td><span>Amends responsibilities of the State Building Code Council.</span></td></tr>
  <tr><th>Current Referral:</th><td><span>HSG, CPC, FIN</span></td></tr>
  <tr><th>Introducer(s):</th><td><span>MATAYOSHI, CHUN</span></td></tr>
</table>
<table id="MainContent_GridViewStatus">
  <tr><th>Date</th><th>Chamber</th><th>Status Text</th></tr>
  <tr><td>12/8/2025</td><td>D</td><td>Carried over to 2026 Regular Session.</td></tr>
  <tr><td>2/5/2025</td><td>H</td><td>The committee(s) on HSG recommend(s) that the measure be deferred.</td></tr>
  <tr><td>1/21/2025</td><td>H</td><td>Referred to HSG, CPC, FIN, referral sheet 1</td></tr>
  <tr><td>1/16/2025</td><td>H</td><td>Introduced and Pass First Reading.</td></tr>
</table>
<div id="MainContent_UpdatePanel2">
  <a href="/sessions/session2026/bills/HB1_.HTM">HB1</a>
  <a href="/sessions/session2026/bills/HB1_.PDF">PDF</a>
</div>
"""


def test_session_and_report_parsing() -> None:
    session = session_for_year(2026)
    items = parse_report(REPORT_HTML)

    assert session.name == "2025-2026 Hawaii Regular Session"
    assert items[0].number == "HB1"
    assert items[0].detail_url == "https://data.capitol.hawaii.gov/session/measure_indiv.aspx?billtype=HB&billnumber=1&year=2026"
    assert items[0].pdf_url == "https://data.capitol.hawaii.gov/sessions/session2026/bills/HB1_.pdf"
    assert items[0].current_status_text == "The committee(s) on HSG recommend(s) that the measure be deferred."


def test_parse_detail_fields_versions_and_actions() -> None:
    fields = parse_measure_fields(DETAIL_HTML)
    versions = parse_versions(DETAIL_HTML, fallback_pdf_url=None)
    actions = parse_actions(DETAIL_HTML)

    assert fields["Measure Title"] == "RELATING TO BUILDING CODES."
    assert [version.format for version in versions] == ["html", "pdf"]
    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.FAILED,
        NormalizedStatus.IN_COMMITTEE,
    ]
    assert actions[0].chamber == Chamber.LOWER


def test_parse_bill_core_fields() -> None:
    item = parse_report(REPORT_HTML)[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_year(2026))

    assert bill.jurisdiction == "us-hi"
    assert bill.number == "HB1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "RELATING TO BUILDING CODES."
    assert [sponsor.name for sponsor in bill.sponsors] == ["MATAYOSHI", "CHUN"]
    assert bill.versions[0].source_url == "https://data.capitol.hawaii.gov/sessions/session2026/bills/HB1_.HTM"


def test_hawaii_kind_and_citations() -> None:
    assert classify("RELATING TO APPROPRIATIONS FOR CAPITAL IMPROVEMENT PROJECTS") == BillKind.APPROPRIATIONS
    assert classify("COMMENDING THE PUBLIC ACCESS ROOM") == BillKind.CEREMONIAL
    assert extract("Amend HRS § 431:10C-104 and section 302A-101, Hawaii Revised Statutes.") == [
        ("HRS § 431:10C-104", "HRS § 431:10C-104"),
        ("section 302A-101, Hawaii Revised Statutes", "section 302A-101, Hawaii Revised Statutes"),
    ]
