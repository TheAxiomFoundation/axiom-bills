from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ri.bill.citations import extract
from axiom_bills.jurisdictions.us_ri.bill.scrape import (
    BillTextItem,
    parse_bill_text_index,
    parse_status_results,
    session_for_year,
)


INDEX_HTML = """
<table>
<tr class="bill_row">
<td class="bill_col1">H7005</td>
<td class="bill_col2"><a href="H7005.pdf">PDF</a></td>
<td class="bill_col3"><a href="H7005.htm">HTML</a></td>
</tr>
</table>
"""

STATUS_HTML = """
<span id="lblBills">
<div>Condition: {Session Year: 2026} {Bill Range: 7005-7005}</div>
<div>House Bill No. <a href="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/H7005.pdf">7005</a></div>
<div>Chapter 007</div>
<div><b>BY</b>&nbsp;&nbsp;Boylan, Knight</div>
<div><b>ENTITLED,&nbsp;</b>AN ACT RELATING TO TAXATION -- PROPERTY SUBJECT TO TAXATION (Authorizes the town of Barrington to provide a tax dollar credit reduction for legally blind persons by ordinance.)</div>
<div style="margin-left: 20%">{LC3126/1}</div>
<div style="margin-left: 5%">01/07/2026 Introduced, referred to House Municipal Government &amp; Housing</div>
<div style="margin-left: 5%">01/20/2026 Committee recommended measure be held for further study</div>
<div style="margin-left: 5%">01/27/2026 Committee recommends passage</div>
<div style="margin-left: 5%">02/03/2026 House read and passed</div>
<div style="margin-left: 5%">04/02/2026 Senate passed in concurrence</div>
<div style="margin-left: 5%">04/02/2026 Transmitted to Governor</div>
<div style="margin-left: 5%">04/10/2026 Effective without Governor's signature</div>
</span>
"""


def test_parse_bill_text_index() -> None:
    items = parse_bill_text_index(
        INDEX_HTML,
        base_url="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/HouseText26.html",
    )

    assert items == [
        BillTextItem(
            number="H7005",
            pdf_url="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/H7005.pdf",
            html_url="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/H7005.htm",
        )
    ]


def test_parse_status_results_extracts_bill() -> None:
    item = BillTextItem(
        number="H7005",
        pdf_url="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/H7005.pdf",
        html_url="http://webserver.rilegislature.gov/BillText/BillText26/HouseText26/H7005.htm",
    )
    bills = parse_status_results(
        STATUS_HTML,
        session=session_for_year(2026),
        chamber=Chamber.LOWER,
        item_by_number={"H7005": item},
    )

    assert len(bills) == 1
    bill = bills[0]
    assert bill.jurisdiction == "us-ri"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "H7005"
    assert bill.sponsors[0].name == "Boylan, Knight"
    assert bill.title.startswith("AN ACT RELATING TO TAXATION")
    assert bill.kind == BillKind.SUBSTANTIVE
    assert bill.versions[0].format == "pdf"
    assert bill.versions[1].format == "html"


def test_parse_status_results_builds_actions() -> None:
    bills = parse_status_results(
        STATUS_HTML,
        session=session_for_year(2026),
        chamber=Chamber.LOWER,
        item_by_number={},
    )
    actions = bills[0].actions

    assert actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert actions[1].normalized_status == NormalizedStatus.FAILED
    assert actions[2].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert actions[-2].normalized_status == NormalizedStatus.ENROLLED
    assert actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert actions[-1].occurred_at.isoformat() == "2026-04-10T00:00:00-04:00"


def test_extracts_ri_citations() -> None:
    assert extract("Amending R.I. Gen Laws § 44-3-4 and section 5-37-1.") == [
        ("R.I. Gen Laws § 44-3-4", "RI Gen. Laws § 44-3-4"),
        ("section 5-37-1", "RI Gen. Laws § 5-37-1"),
    ]
