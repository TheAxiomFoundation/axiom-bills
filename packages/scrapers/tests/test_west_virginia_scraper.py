from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_wv.bill.citations import extract
from axiom_bills.jurisdictions.us_wv.bill.kind import classify
from axiom_bills.jurisdictions.us_wv.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_bill_list,
    parse_versions,
    session_from_year,
)


LIST_HTML = """
<table id="results">
<tr><th>Bill</th><th>Title</th><th>Status</th></tr>
<tr><td><a href="Bills_history.cfm?input=1&year=2026&sessiontype=RS&btype=bill">SB 1</a></td>
<td>Small Business Growth Act</td><td>Signed&nbsp;</td><td colspan="3">Effective from passage</td></tr>
</table>
"""

HISTORY_HTML = """
<table class="bstat">
<tr><td class="nums"><strong>SUMMARY:</strong></td><td>Small Business Growth Act</td></tr>
<tr><td class="nums"><strong>LEAD SPONSOR:</strong></td><td><a>Smith (Mr. President)</a></td></tr>
<tr><td class="nums"><strong>SPONSORS:</strong></td><td><a>Phillips</a>, <a>Queen</a></td></tr>
<tr><td class="nums"><strong>BILL TEXT:</strong></td><td>
Introduced Version - <a href="bills_text.cfm?billdoc=sb1%20intr.htm&yr=2026&sesstype=RS&i=1" title="HTML - Introduced Version - Senate Bill 1">html</a>
| <a data-type="pdf" href="/Bill_Text_HTML/2026_SESSIONS/RS/bills/sb1 intr.pdf" title="PDF - Introduced Version - Senate Bill 1">pdf</a>
</td></tr>
<tr><td class="nums"><strong>SUBJECTS:</strong></td><td><a>Economic Development</a></td></tr>
</table>
<table>
<tr id="act-1" class="actionrows"><td class="tdborder act-chamber">S</td><td class="tdborder act-url">Filed for introduction</td><td class="tdborder">01/14/26</td></tr>
<tr id="act-2" class="actionrows"><td class="tdborder act-chamber">S</td><td class="tdborder act-url"><a href="/legisdocs/2026/RS/votes/senate/02-06-0047.pdf">Passed Senate (Roll No. 47)</a></td><td class="tdborder">02/06/26</td></tr>
</table>
"""


def test_west_virginia_list_and_bill_parsing() -> None:
    rows = parse_bill_list(LIST_HTML)
    session = session_from_year(2026, "RS")
    bill = parse_bill(rows[0], HISTORY_HTML, session=session)

    assert session.name == "2026 West Virginia Regular Session"
    assert rows[0]["number"] == "SB 1"
    assert bill.chamber == Chamber.UPPER
    assert bill.title == "Small Business Growth Act"
    assert bill.sponsors[0].name == "Smith (Mr. President)"
    assert bill.subjects == ["Economic Development"]
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER


def test_west_virginia_actions_versions_kind_and_citations() -> None:
    assert parse_actions(HISTORY_HTML)[0].normalized_status == NormalizedStatus.INTRODUCED
    assert parse_versions(HISTORY_HTML)[1].format == "pdf"
    assert classify("Budget Bill") == BillKind.APPROPRIATIONS
    assert classify("A resolution honoring a championship team") == BillKind.CEREMONIAL
    assert extract("A BILL to amend the Code of West Virginia by adding §5 B- 12 - 1.") == [
        ("§5 B- 12 - 1", "§5 B- 12 - 1"),
        ("Code of West Virginia", "Code of West Virginia"),
    ]
