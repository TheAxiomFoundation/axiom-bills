from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_mi.bill.citations import extract
from axiom_bills.jurisdictions.us_mi.bill.kind import classify
from axiom_bills.jurisdictions.us_mi.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_sponsors,
    parse_subjects,
    parse_versions,
    session_for_code,
)


LIST_HTML = """
<table>
  <tr>
    <td><a href="/Home/GetObject?objectName=2025-HB-4001">HB 4001 of 2025</a></td>
    <td>House Bill</td>
    <td>Labor: hours and wages; minimum hourly wage rate; modify. Amends secs. 4 &amp; 4b of 2014 PA 138 (MCL 408.414 &amp; 408.414b). Last Action: referred to committee</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<h1>House Bill 4001 of 2025</h1>
<section><h2>Sponsors</h2>
  <a href="/Search/ExecuteSearch?sponsor=John+Roth&amp;sponsorTypesList=primary">John Roth (District 104)</a>
  <a href="/Search/ExecuteSearch?sponsor=Jay+DeBoyer&amp;sponsorTypesList=cosponsor">Jay DeBoyer (District 63)</a>
</section>
<section><h2>Categories</h2>
  Labor: hours and wages
  Labor: hours and wages; minimum hourly wage rate; modify. Amends secs. 4 &amp; 4b of 2014 PA 138 (MCL 408.414 &amp; 408.414b).
</section>
<section><h2>Documents</h2>
  <a href="/documents/2025-2026/billintroduced/House/pdf/2025-HIB-4001.pdf">PDF</a>
  <a href="/documents/2025-2026/billintroduced/House/htm/2025-HIB-4001.htm">HTML</a>
</section>
<table>
  <tr><td>1/09/2025</td><td>HJ 2 Pg. 31</td><td>introduced by Representative Rep. John Roth</td></tr>
  <tr><td>1/09/2025</td><td>HJ 2 Pg. 31</td><td>referred to Committee on Labor</td></tr>
  <tr><td>1/23/2025</td><td>HJ 7 Pg. 56</td><td>passed; given immediate effect Roll Call #4 Yeas 63 Nays 41</td></tr>
</table>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_code("2025-2026")
    items = parse_listing(LIST_HTML)

    assert session.name == "Michigan Legislature 2025-2026"
    assert items[0].number == "HB 4001"
    assert items[0].detail_url == "https://www.legislature.mi.gov/Home/GetObject?objectName=2025-HB-4001"


def test_detail_actions_sponsors_subjects_and_versions() -> None:
    actions = parse_actions(DETAIL_HTML)
    versions = parse_versions(DETAIL_HTML)
    sponsors = parse_sponsors(DETAIL_HTML)
    subjects = parse_subjects(DETAIL_HTML)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.format for version in versions] == ["pdf", "html"]
    assert [sponsor.name for sponsor in sponsors] == ["John Roth", "Jay DeBoyer"]
    assert subjects == ["Labor"]


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LIST_HTML)[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_code("2025-2026"))

    assert bill.jurisdiction == "us-mi"
    assert bill.number == "HB 4001"
    assert bill.chamber == Chamber.LOWER
    assert "minimum hourly wage rate" in (bill.summary or "")


def test_michigan_kind_and_citations() -> None:
    assert classify("Appropriations: omnibus budget bill") == BillKind.APPROPRIATIONS
    assert classify("A resolution to memorialize Congress") == BillKind.CEREMONIAL
    assert extract("Amends 2014 PA 138 (MCL 408.414) and PA 2'25.") == [
        ("MCL 408.414", "MCL 408.414"),
        ("2014 PA 138", "2014 PA 138"),
        ("PA 2'25", "PA 2'25"),
    ]
