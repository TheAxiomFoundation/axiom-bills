from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_mo.bill.citations import extract
from axiom_bills.jurisdictions.us_mo.bill.kind import classify
from axiom_bills.jurisdictions.us_mo.bill.scrape import (
    parse_house_bill,
    parse_house_sponsors,
    parse_listing,
    parse_senate_actions,
    parse_senate_bill,
    parse_subjects,
    session_for_year,
)


LIST_HTML = """
<table>
  <tr><th>Bill</th><th>Sponsor</th><th></th><th>Bill String</th><th>Date/Last Action</th></tr>
  <tr>
    <td><a href="Bill.aspx?bill=HB2751&amp;year=2026&amp;code=R ">HB2751</a></td>
    <td>Perkins, Chad</td><td></td><td>HCS HB 2751</td>
    <td>4/29/2026 Placed Back on Formal Perfection Calendar (H)</td>
  </tr>
</table>
"""

HOUSE_DETAIL_HTML = """
<div>103rd General Assembly, 2nd Regular Session HB 2751 Modifies provisions relating to public safety Sponsor:</div>
<table>
  <tr><td>Perkins, Chad (040)</td><td>Sponsor:</td></tr>
  <tr><td>8/28/2026</td><td>Proposed Effective Date:</td></tr>
  <tr><td>HCS HB 2751</td><td>Bill String:</td></tr>
</table>
<a href="https://documents.house.mo.gov/billtracking/bills261/hlrbillspdf/6221H.01I.pdf">Introduced</a>
<a href="https://documents.house.mo.gov/billtracking/bills261/hlrbillspdf/6221H.07C.pdf">Committee</a>
"""

HOUSE_ACTIONS_HTML = """
<table>
  <tr><th>Date</th><th>Jrn Pg</th><th>Activity Description</th></tr>
  <tr><td>1/06/2026</td><td></td><td>Prefiled (H)</td></tr>
  <tr><td>1/08/2026</td><td>H 321</td><td>Referred: Corrections and Public Institutions(H)</td></tr>
  <tr><td>2/17/2026</td><td>H 849</td><td>HCS Reported Do Pass (H)</td></tr>
</table>
"""

SENATE_DETAIL_HTML = """
<button data-modal-url="/BillTracking/Bills/BillInformation?year=2026&amp;billId=378&amp;billPrefix=SB&amp;billSuffix=859&amp;handler=Actions">All Actions</button>
<button data-modal-url="/BillTracking/Bills/BillInformation?year=2026&amp;billId=378&amp;handler=BillText">Available Bill Text</button>
<div>SB 859 - Moon, Mike Creates provisions relating to artificial intelligence Sponsor Moon, Mike LR Number 4600S.01I Title SB 859 Effective Date August 28, 2026 Committee General Laws Current Status Hearing Conducted S General Laws Committee Quick Links CURRENT BILL SUMMARY SB 859 - This act establishes the AI Non-Sentience and Responsibility Act. JULIA SHEVE</div>
"""

SENATE_ACTIONS_HTML = """
<table>
  <tr><th>Date</th><th>Action</th><th>Journal</th></tr>
  <tr><td>12/01/2025</td><td>Prefiled</td><td></td></tr>
  <tr><td>01/07/2026</td><td>S First Read</td><td>S37</td></tr>
  <tr><td>03/04/2026</td><td>Hearing Conducted S General Laws Committee</td><td></td></tr>
</table>
"""

SENATE_TEXT_HTML = """
<a href="/26info/pdf-bill/intro/SB859.pdf">4600S.01I - Introduced</a>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_year(2026)
    items = parse_listing(LIST_HTML)

    assert session.name == "2026 Missouri Regular Session"
    assert items[0].number == "HB 2751"
    assert items[0].sponsor == "Perkins, Chad"
    assert items[0].detail_url == "https://house.mo.gov/Bill.aspx?bill=HB2751&year=2026&code=R"


def test_house_detail_actions_and_versions() -> None:
    item = parse_listing(LIST_HTML)[0]
    bill = parse_house_bill(
        item,
        HOUSE_DETAIL_HTML,
        HOUSE_ACTIONS_HTML,
        session=session_for_year(2026),
        source_url="https://house.mo.gov/BillContent.aspx?bill=HB2751&year=2026&code=R&style=new",
    )

    assert bill.number == "HB 2751"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "Modifies provisions relating to public safety"
    assert [action.normalized_status for action in bill.actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.IN_COMMITTEE,
    ]
    assert [sponsor.name for sponsor in parse_house_sponsors(HOUSE_DETAIL_HTML)] == ["Chad Perkins"]
    assert len(bill.versions) == 2


def test_senate_detail_actions_versions_and_subjects() -> None:
    item = parse_listing("""
    <table><tr><td><a href="https://www.senate.mo.gov/BillTracking/Bills/BillInformation?handler=legislation&amp;year=2026&amp;session=R&amp;billPrefix=SB&amp;billSuffix=859">SB859</a></td><td>Moon, Mike</td><td></td><td>SB 859</td><td>3/4/2026 Hearing Conducted</td></tr></table>
    """)[0]
    bill = parse_senate_bill(
        item,
        SENATE_DETAIL_HTML,
        SENATE_ACTIONS_HTML,
        SENATE_TEXT_HTML,
        session=session_for_year(2026),
    )

    assert bill.number == "SB 859"
    assert bill.chamber == Chamber.UPPER
    assert "AI Non-Sentience" in (bill.summary or "")
    assert [action.normalized_status for action in parse_senate_actions(SENATE_ACTIONS_HTML)] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
    ]
    assert bill.versions[0].format == "pdf"
    assert parse_subjects("Creates provisions relating to artificial intelligence") == ["Artificial Intelligence"]


def test_missouri_kind_and_citations() -> None:
    assert classify("Appropriations: fiscal year budget") == BillKind.APPROPRIATIONS
    assert classify("Recognizing Missouri veterans") == BillKind.CEREMONIAL
    assert extract("Amends sections 105.963, RSMo, RSMo 143.611, and Article IV, Section 27.") == [
        ("RSMo 143.611", "RSMo 143.611"),
        ("sections 105.963, RSMo", "sections 105.963, RSMo"),
        ("Article IV, Section 27", "Article IV, Section 27"),
    ]
