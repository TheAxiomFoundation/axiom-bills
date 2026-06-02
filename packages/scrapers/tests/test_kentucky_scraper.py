from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ky.bill.citations import extract
from axiom_bills.jurisdictions.us_ky.bill.kind import classify
from axiom_bills.jurisdictions.us_ky.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_subjects,
    parse_versions,
    session_for_code,
)


LIST_HTML = """
<table class="table table-hover table-bordered">
  <tr><th>Bill</th><th>Prime Sponsor</th><th>Title</th></tr>
  <tr>
    <td><a href="hb1.html">House Bill 1</a></td>
    <td>K. Moser</td>
    <td>AN ACT implementing the federal education opportunity program in Kentucky.</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<h3>House Bill 1</h3>
<table class="table table-striped table-bordered">
  <tr><th>Last Action</th><td>03/17/26: delivered to Secretary of State (Acts Ch. 4)</td></tr>
  <tr><th>Title</th><td>AN ACT implementing the federal education opportunity program in Kentucky.</td></tr>
  <tr><th>Bill Documents</th><td>
    <a href="https://apps.legislature.ky.gov/law/acts/26RS/documents/0004.pdf">Acts Chapter 4</a>
    <a href="https://apps.legislature.ky.gov/recorddocuments/bill/26RS/hb1/bill.pdf">Current/Final</a>
    <a href="https://apps.legislature.ky.gov/recorddocuments/bill/26RS/hb1/orig_bill.pdf">Introduced</a>
  </td></tr>
  <tr><th>Sponsors</th><td>K. Moser, T. Roberts</td></tr>
  <tr><th>Summary of Original Version</th><td>Create a new section of KRS Chapter 14.</td></tr>
  <tr><th>Index Headings of Original Version</th><td>
    <a href="0080.html">Administrative Regulations And Proceedings</a>
    <a href="3200.html">Education, Elementary And Secondary</a>
  </td></tr>
</table>
<h4>Actions</h4>
<table class="table table-striped table-bordered">
  <tr><td>02/19/26</td><td>introduced in House to Committee on Committees (H) to Appropriations &amp; Revenue (H)</td></tr>
  <tr><td>02/27/26</td><td>3rd reading, passed 33-5 received in House enrolled, signed by Speaker of the House</td></tr>
  <tr><td>03/02/26</td><td>enrolled, signed by President of the Senate delivered to Governor</td></tr>
  <tr><td>03/17/26</td><td>delivered to Secretary of State (Acts Ch. 4)</td></tr>
</table>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_code("26RS")
    items = parse_listing(LIST_HTML, session_code="26RS")

    assert session.name == "2026 Kentucky Regular Session"
    assert items[0].number == "HB 1"
    assert items[0].prime_sponsor == "K. Moser"
    assert items[0].detail_url == "https://apps.legislature.ky.gov/record/26rs/hb1.html"


def test_detail_actions_subjects_and_versions() -> None:
    actions = parse_actions(DETAIL_HTML)
    versions = parse_versions(DETAIL_HTML)
    subjects = parse_subjects(DETAIL_HTML)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.label for version in versions] == ["Acts Chapter 4", "Current/Final", "Introduced"]
    assert subjects == ["Administrative Regulations And Proceedings", "Education, Elementary And Secondary"]


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LIST_HTML, session_code="26RS")[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_code("26RS"))

    assert bill.jurisdiction == "us-ky"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "AN ACT implementing the federal education opportunity program in Kentucky."
    assert bill.summary == "Create a new section of KRS Chapter 14."
    assert [sponsor.name for sponsor in bill.sponsors] == ["K. Moser", "T. Roberts"]


def test_kentucky_kind_and_citations() -> None:
    assert classify("AN ACT making an appropriation") == BillKind.APPROPRIATIONS
    assert classify("A RESOLUTION honoring Kentucky veterans") == BillKind.CEREMONIAL
    assert extract("Create a new section of KRS Chapter 14 and amend KRS 160.370. Acts Ch. 4.") == [
        ("KRS Chapter 14", "KRS Chapter 14"),
        ("KRS 160.370", "KRS 160.370"),
        ("Acts Ch. 4", "Acts Ch. 4"),
    ]

