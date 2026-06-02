from __future__ import annotations

from selectolax.parser import HTMLParser

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus, Session
from axiom_bills.jurisdictions.us_tx.bill.citations import extract
from axiom_bills.jurisdictions.us_tx.bill.kind import classify
from axiom_bills.jurisdictions.us_tx.bill.scrape import (
    TexasIndexItem,
    current_session_from_reports,
    parse_actions,
    parse_bill,
    parse_filing_date_report,
    parse_versions,
)


REPORTS_HTML = """
<span id="usrHeader_lblApplicationName">89th Legislature Second Called Session</span>
<select id="cboLegSess">
  <option selected="selected" value="892">89(2) - 2025</option>
</select>
"""

FILING_HTML = """
<div class="bill-search-results">
  <div class="row">
    <div class="bill-search-result-label">
      <a href="http://capitol.texas.gov/BillLookup/History.aspx?LegSess=892&amp;Bill=HB1">HB 1</a>
    </div>
    <div class="bill-search-result-data"></div>
    <div class="bill-search-result-data"><b>Author</b>:</div>
    <div class="bill-search-result-data">Darby | King</div>
    <div class="bill-search-result-label"><b>Last Action:</b></div>
    <div class="bill-search-result-data">09/05/2025 E Effective immediately</div>
    <div class="bill-search-result-label"><b>Caption</b>:</div>
    <div class="bill-search-result-data">Relating to youth camp emergency plans and preparedness.</div>
  </div>
</div>
"""

HISTORY_HTML = """
<span id="lblCaptionText">Relating to youth camp emergency plans and preparedness; authorizing penalties.</span>
<span id="lblAuthor">Darby | King | Meyer</span>
<span id="lblSponsor">Perry</span>
<span id="lblSubjects">Disaster Preparedness &amp; Relief (I0211)<br/>Water--Development (I0875)<br/></span>
<table class="actions">
  <tr><th colspan="2">Description</th><th>Comment</th><th>Date</th></tr>
  <tr><td data-label="Action Chamber">H</td><td data-label="Action Description">Filed</td><td></td><td>08/15/2025</td></tr>
  <tr><td data-label="Action Chamber">H</td><td data-label="Action Description">Read first time</td><td></td><td>08/18/2025</td></tr>
  <tr><td data-label="Action Chamber">E</td><td data-label="Action Description">Signed by the Governor</td><td></td><td>09/05/2025</td></tr>
</table>
"""

TEXT_HTML = """
<table>
  <tr>
    <td data-label="Version">Introduced</td>
    <td data-label="Bill">
      <a href="https://capitol.texas.gov/tlodocs/892/billtext/pdf/HB00001I.pdf">PDF</a>
      <a href="https://capitol.texas.gov/tlodocs/892/billtext/html/HB00001I.htm">HTML</a>
    </td>
  </tr>
</table>
"""


def test_texas_session_and_filing_report_parsing() -> None:
    session = current_session_from_reports(REPORTS_HTML)
    item = parse_filing_date_report(FILING_HTML)[0]

    assert session.code == "892"
    assert session.name == "89th Legislature Second Called Session, 89(2) - 2025"
    assert item.number == "HB 1"
    assert item.roster_title == "Relating to youth camp emergency plans and preparedness."
    assert item.source_url == "https://capitol.texas.gov/BillLookup/History.aspx?LegSess=892&Bill=HB1"


def test_texas_bill_parsing() -> None:
    session = Session(name="89th Legislature Second Called Session, 89(2) - 2025")
    item = TexasIndexItem(
        number="HB 1",
        source_url="https://capitol.texas.gov/BillLookup/History.aspx?LegSess=892&Bill=HB1",
    )
    bill = parse_bill(item, history_html=HISTORY_HTML, text_html=TEXT_HTML, session=session)

    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Darby"
    assert bill.sponsors[-1].role == "sponsor"
    assert bill.subjects == ["Disaster Preparedness & Relief (I0211)", "Water--Development (I0875)"]
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert len(bill.versions) == 2


def test_texas_kind_status_and_citations() -> None:
    tree = HTMLParser(HISTORY_HTML)

    assert parse_actions(tree)[1].chamber == Chamber.LOWER
    assert parse_versions(HTMLParser(TEXT_HTML))[0].format == "pdf"
    assert classify("General Appropriations Bill.") == BillKind.APPROPRIATIONS
    assert classify("A resolution congratulating a champion") == BillKind.CEREMONIAL
    assert extract("Amends Sections 418.005 and 418.006, Government Code.") == [
        ("Sections 418.005 and 418.006, Government Code", "Sections 418.005 and 418.006, Government Code")
    ]
