from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_co.bill.scrape import (
    parse_bill_page,
    parse_search_bill_urls,
)


SEARCH_HTML = """
<html>
  <body>
    <h2>HB26-1069</h2>
    <h3><a href="/bills/hb26-1069">Availability of Emergency Medical Services</a></h3>
    <h2>SB26-121</h2>
    <h3><a href="/bills/sb26-121">Some Senate Bill</a></h3>
    <h3><a href="/bills/hb26-1069">Duplicate link</a></h3>
    <a href="/bills/hjr26-1001">Resolution should be ignored</a>
  </body>
</html>
"""


BILL_HTML = """
<html>
  <body>
    <h1>HB26-1061</h1>
    <h1>Community Integration Housing Tax Credits</h1>
    <div>Type Bill</div>
    <div>Session 2026 Regular Session</div>
    <h2>Subjects</h2>
    <a>Fiscal Policy &amp; Taxes</a>
    <a>Housing</a>
    <p>Concerning funding for community integration housing.</p>
    <a href="/bill_files/111467/download">Recent Bill (PDF)</a>
    <h2>Bill Summary:</h2>
    <p>The bill creates a targeted allocation priority.</p>
    <p>(Note: This summary applies to this bill as introduced.)</p>
    <h2>Prime Sponsors</h2>
    <a>Representative Max Brooks</a>
    <h2>Committees</h2>
    <h2>Status</h2>
    <div>Under Consideration</div>
    <h2>Related Documents &amp; Information</h2>
    <h4>All Versions (1)</h4>
    <table>
      <tr><th>Date</th><th>Version</th><th>Documents</th></tr>
      <tr><td>01/14/2026</td><td>Introduced</td><td><a href="/bill_files/111467/download">PDF</a></td></tr>
    </table>
    <h4>Bill history (1)</h4>
    <table>
      <tr><th>Date</th><th>Location</th><th>Action</th></tr>
      <tr>
        <td>01/14/2026</td>
        <td>House</td>
        <td>Introduced In House - Assigned to Transportation, Housing &amp; Local Government</td>
      </tr>
      <tr>
        <td>02/20/2026</td>
        <td>House</td>
        <td>House Committee on Finance Refer Amended</td>
      </tr>
    </table>
    <h4>Sponsors</h4>
  </body>
</html>
"""


def test_parse_search_bill_urls_deduplicates_and_filters_to_bills() -> None:
    assert parse_search_bill_urls(SEARCH_HTML) == [
        "https://leg.colorado.gov/bills/hb26-1069",
        "https://leg.colorado.gov/bills/sb26-121",
    ]


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://leg.colorado.gov/bills/hb26-1061",
    )

    assert bill is not None
    assert bill.jurisdiction == "us-co"
    assert bill.session_name == "2026 Regular Session"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB26-1061"
    assert bill.title == "Community Integration Housing Tax Credits"
    assert bill.subjects == ["Fiscal Policy & Taxes", "Housing"]
    assert bill.summary == "The bill creates a targeted allocation priority."
    assert bill.sponsors[0].name == "Representative Max Brooks"
    assert bill.versions[0].source_url == "https://leg.colorado.gov/bill_files/111467/download"


def test_parse_bill_page_extracts_actions_with_statuses() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://leg.colorado.gov/bills/hb26-1061",
    )

    assert bill is not None
    assert len(bill.actions) == 2
    assert bill.actions[0].chamber == Chamber.LOWER
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.IN_COMMITTEE
