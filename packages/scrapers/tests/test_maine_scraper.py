from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_me.bill.citations import extract
from axiom_bills.jurisdictions.us_me.bill.kind import classify
from axiom_bills.jurisdictions.us_me.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_sponsors,
    parse_subjects,
    parse_versions,
    session_for_legislature,
)


LIST_HTML = """
<table>
  <tr>
    <td>1.</td>
    <td>LD 2162, HP 1451, 132nd Legislature</td>
    <td>An Act to Regulate Artificial Intelligence Chatbots</td>
  </tr>
  <tr><td></td><td colspan="2">
    <a href="display_ps.asp?snum=132&amp;paper=HP1451&amp;PID=1456">Bill &amp; Fiscal Information</a>
  </td></tr>
</table>
"""

DETAIL_HTML = """
<h2>An Act to Regulate Artificial Intelligence Chatbots</h2>
<a href="//legislature.maine.gov/LawMakerWeb/summary.asp?paper=HP1451&amp;SessionID=16">Chamber Status</a>
<p>Final Disposition Emergency Enacted, Apr 22, 2025 Governor's Action: Emergency Signed, Apr 22, 2025</p>
<a href="getPDF.asp?paper=HP1451&amp;item=1&amp;snum=132">Printed Document PDF</a>
<a href="getPDF.asp?paper=HP1451&amp;item=2&amp;snum=132">Printed Document PDF</a>
"""

ACTIONS_HTML = """
<table>
  <tr><th>Date</th><th>Chamber</th><th>Action</th></tr>
  <tr><td>1/13/2026</td><td>House</td><td>Committee on JUDICIARY suggested and ordered printed. The Bill was REFERRED to the Committee.</td></tr>
  <tr><td>4/9/2026</td><td>House</td><td>PASSED TO BE ENACTED. Sent for concurrence.</td></tr>
  <tr><td>4/29/2026</td><td>Senate</td><td>Died in Possession of the Senate when the Legislature adjourned Sine Die. (DEAD)</td></tr>
</table>
"""

SPONSORS_HTML = """
<table>
  <tr><td>Sponsored By:</td><td><b>Representative Lori GRAMLICH of Old Orchard Beach</b></td></tr>
  <tr><td>Cosponsored By:</td><td><b>Senator Donna BAILEY of York <br> Representative Michael BRENNAN of Portland</b></td></tr>
</table>
"""

SUBJECTS_HTML = """
<table>
  <tr><td></td><td>Major Subject</td><td>Minor Subject</td><td>Detail Subject</td></tr>
  <tr><td></td><td>MENTAL HEALTH SERVICES</td><td>DELIVERY</td><td>ARTIFICIAL INTELLIGENCE USE</td></tr>
</table>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_legislature(132)
    items = parse_listing(LIST_HTML)

    assert session.name == "132nd Maine Legislature (2025-2026)"
    assert items[0].number == "LD 2162"
    assert items[0].paper == "HP1451"
    assert items[0].detail_url == "https://legislature.maine.gov/bills/display_ps.asp?snum=132&paper=HP1451&PID=1456"


def test_detail_actions_sponsors_subjects_and_versions() -> None:
    actions = parse_actions(ACTIONS_HTML)
    versions = parse_versions(DETAIL_HTML)
    sponsors = parse_sponsors(SPONSORS_HTML)
    subjects = parse_subjects(SUBJECTS_HTML)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.PASSED_BOTH,
        NormalizedStatus.FAILED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.label for version in versions] == ["Printed Document PDF 1", "Printed Document PDF 2"]
    assert [sponsor.name for sponsor in sponsors] == ["Lori Gramlich", "Donna Bailey", "Michael Brennan"]
    assert [sponsor.role for sponsor in sponsors] == ["primary", "cosponsor", "cosponsor"]
    assert subjects == ["Mental Health Services", "Delivery", "Artificial Intelligence Use"]


def test_parse_bill_core_fields_and_final_disposition_action() -> None:
    item = parse_listing(LIST_HTML)[0]
    bill = parse_bill(
        item,
        DETAIL_HTML,
        actions_html=ACTIONS_HTML,
        sponsors_html=SPONSORS_HTML,
        subjects_html=SUBJECTS_HTML,
        session=session_for_legislature(132),
    )

    assert bill.jurisdiction == "us-me"
    assert bill.number == "LD 2162"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "An Act to Regulate Artificial Intelligence Chatbots"
    assert NormalizedStatus.ENACTED in {action.normalized_status for action in bill.actions}


def test_maine_kind_and_citations() -> None:
    assert classify("An Act Making Supplemental Appropriations and Allocations") == BillKind.APPROPRIATIONS
    assert classify("Resolve, Recognizing Maine Veterans") == BillKind.CEREMONIAL
    assert extract("Amend 36 MRSA § 5219-QQ, Title 36, section 5122 and Public Law 2025, chapter 33.") == [
        ("36 MRSA § 5219-QQ", "36 MRSA § 5219-QQ"),
        ("Title 36, section 5122", "Title 36, section 5122"),
        ("Public Law 2025, chapter 33", "Public Law 2025, chapter 33"),
    ]
