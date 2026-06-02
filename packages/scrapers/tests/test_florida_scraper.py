from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_fl.bill.scrape import (
    BillListItem,
    parse_bill_page,
    parse_list_items,
    parse_next_url,
    selected_session_year,
    session_for_year,
)


LIST_HTML = """
<select name="SessionYear"><option value="2026F" selected="selected">2026F</option></select>
<div id="billListDiv">
<table><tbody>
<tr>
  <th scope="row"><a href="/Session/Bill/2026F/4F">SB 4F</a></th>
  <td>Property Tax Administration</td>
  <td>Avila</td>
  <td>Last Action: 6/1/2026 S Placed on Special Order Calendar, 06/02/26</td>
</tr>
</tbody></table>
</div>
<a class="next" href="/Session/Bills/2026F?Chamber=senate&amp;PageNumber=2">Next</a>
"""

DETAIL_HTML = """
<h2>CS/SB 4-F: Property Tax Administration</h2>
<p class="width80">Revising provisions for property tax administration.</p>
<div id="tabBodyBillHistory">
<table><tbody>
<tr><td>5/28/2026</td><td>Senate</td><td>&bull; Filed<br>&bull; Referred to Appropriations</td></tr>
<tr><td>6/1/2026</td><td>Senate</td><td>&bull; CS by- Appropriations; YEAS 13 NAYS 5<br>&bull; Placed on Calendar, on 2nd reading</td></tr>
<tr><td>6/2/2026</td><td>Senate</td><td>&bull; Passed; YEAS 30 NAYS 8</td></tr>
</tbody></table>
</div>
<div id="tabBodyBillText">
<table><tbody>
<tr><td>S 4F Filed</td><td>5/28/2026 10:01 AM</td><td>
<a href="/Session/Bill/2026F/4F/BillText/Filed/HTML">Web Page</a>
<a href="/Session/Bill/2026F/4F/BillText/Filed/PDF">PDF</a>
</td></tr>
</tbody></table>
</div>
<div id="tabBodyCitations">
<table><tbody>
<tr><td>200.065</td><td>Method of fixing millage.</td><td>Page 2</td></tr>
</tbody></table>
</div>
"""


def test_selected_session_year_and_list_items() -> None:
    assert selected_session_year(LIST_HTML) == "2026F"

    items = parse_list_items(LIST_HTML)

    assert items[0].number == "SB 4F"
    assert items[0].title == "Property Tax Administration"
    assert items[0].sponsor == "Avila"
    assert items[0].url == "https://www.flsenate.gov/Session/Bill/2026F/4F"
    assert parse_next_url(LIST_HTML) == (
        "https://www.flsenate.gov/Session/Bills/2026F?Chamber=senate&PageNumber=2"
    )


def test_session_for_year() -> None:
    session = session_for_year("2026F")

    assert session.name == "2026F Florida Legislature"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-01"


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem(
            number="SB 4F",
            title="Property Tax Administration",
            sponsor="Avila",
            url="https://www.flsenate.gov/Session/Bill/2026F/4F",
        ),
        session=session_for_year("2026F"),
    )

    assert bill is not None
    assert bill.jurisdiction == "us-fl"
    assert bill.chamber == Chamber.UPPER
    assert bill.number == "SB 4F"
    assert bill.title == "Property Tax Administration"
    assert bill.summary == "Revising provisions for property tax administration."
    assert bill.sponsors[0].name == "Avila"
    assert bill.subjects == ["Florida Statutes 200.065"]


def test_parse_bill_page_builds_actions_and_versions() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem(
            number="SB 4F",
            title="Property Tax Administration",
            sponsor="Avila",
            url="https://www.flsenate.gov/Session/Bill/2026F/4F",
        ),
        session=session_for_year("2026F"),
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.versions[0].label == "S 4F Filed"
    assert bill.versions[0].source_url == (
        "https://www.flsenate.gov/Session/Bill/2026F/4F/BillText/Filed/PDF"
    )
