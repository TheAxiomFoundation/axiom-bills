from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_la.bill.citations import extract
from axiom_bills.jurisdictions.us_la.bill.kind import classify
from axiom_bills.jurisdictions.us_la.bill.scrape import (
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
    <td><a href="BillInfo.aspx?i=249908">1</a></td>
    <td>SENT GOVERNOR</td>
    <td><a href="BillInfo.aspx?i=250493">631</a></td>
    <td>ACT 108</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<span id="ctl00_PageBody_LabelBillID">HB1</span>
<span id="ctl00_PageBody_LabelShortTitle">
  APPROPRIATIONS: Provides for the ordinary operating expenses of state government.
</span>
<a id="ctl00_PageBody_LinkAuthor" href="https://house.louisiana.gov/H_Reps/members.aspx?ID=13">Jack McFarland</a>
<a href="https://house.louisiana.gov/H_Reps/members.aspx?ID=13">Jack McFarland (primary)</a>
<a href="https://house.louisiana.gov/H_Reps/members.aspx?ID=59">Tony Bacala</a>
<a href="ViewDocument.aspx?d=1478641">HB1 Enrolled</a>
<a href="ViewDocument.aspx?d=1461390">HB1 Engrossed</a>
<table>
  <tr><td>02/20</td><td>H</td><td></td><td>Prefiled.</td><td></td></tr>
  <tr><td>03/09</td><td>H</td><td>10</td><td>Read by title, under the rules, referred to the Committee on Appropriations.</td><td></td></tr>
  <tr><td>04/16</td><td>H</td><td>19</td><td>Read third time by title, roll called on final passage, yeas 104, nays 0. Finally passed, title adopted, ordered to the Senate.</td><td></td></tr>
  <tr><td>06/01</td><td>H</td><td></td><td>Sent to the Governor for executive approval.</td><td></td></tr>
</table>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_code("26RS")
    items = parse_listing(LIST_HTML, prefix="HB")

    assert session.name == "2026 Louisiana Regular Session"
    assert session.start_date.year == 2026
    assert items[0].number == "HB 1"
    assert items[0].detail_url == "https://www.legis.la.gov/legis/BillInfo.aspx?i=249908"


def test_detail_actions_sponsors_subjects_and_versions() -> None:
    actions = parse_actions(DETAIL_HTML, session_year=2026)
    versions = parse_versions(DETAIL_HTML)
    sponsors = parse_sponsors(DETAIL_HTML)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.label for version in versions] == ["HB1 Enrolled", "HB1 Engrossed"]
    assert [sponsor.name for sponsor in sponsors] == ["Jack McFarland", "Tony Bacala"]
    assert [sponsor.role for sponsor in sponsors] == ["primary", "cosponsor"]
    assert parse_subjects("PUBLIC MEETINGS: Provides for electronic voting.") == ["Public Meetings"]


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LIST_HTML, prefix="HB")[0]
    bill = parse_bill(item, DETAIL_HTML, session=session_for_code("26RS"))

    assert bill.jurisdiction == "us-la"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "APPROPRIATIONS: Provides for the ordinary operating expenses of state government."
    assert bill.summary == bill.title
    assert bill.kind == BillKind.APPROPRIATIONS


def test_louisiana_kind_and_citations() -> None:
    assert classify("APPROPRIATIONS: Provides for the state budget") == BillKind.APPROPRIATIONS
    assert classify("COMMENDATIONS: Commends a championship team") == BillKind.CEREMONIAL
    assert extract("Amends La. R.S. 17:1519.11, Code of Criminal Procedure Art. 895, and Act No. 220.") == [
        ("La. R.S. 17:1519.11", "La. R.S. 17:1519.11"),
        ("Code of Criminal Procedure Art. 895", "Code of Criminal Procedure Art. 895"),
        ("Act No. 220", "Act No. 220"),
    ]
