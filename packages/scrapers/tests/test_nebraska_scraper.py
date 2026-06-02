from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ne.bill.citations import extract
from axiom_bills.jurisdictions.us_ne.bill.scrape import (
    BillListItem,
    parse_bill_page,
    parse_date_csv,
    parse_session_days,
    session_for_year,
)


SEARCH_HTML = """
<select name="SessionDay" id="SessionDay">
<option value="2026-01-07">Wednesday January 7th</option>
<option value="2026-01-08">Thursday January 8th</option>
<option value="2025-01-09">Old</option>
</select>
"""

CSV_TEXT = '''"Document","Primary Introducer","Status","Description","Document ID"
"LB716","Executive Board: Hansen, Chairperson","Passed","Revisor's bill to eliminate obsolete provisions and provisions that have terminated","63242"
'''

DETAIL_HTML = """
<h2>LB716 - Revisor's bill to eliminate obsolete provisions and provisions that have terminated</h2>
<a href="../FloorDocs/109/PDF/Intro/LB716.pdf">Introduced</a>
<a href="../FloorDocs/109/PDF/Final/LB716.pdf">Final Reading</a>
<a href="../FloorDocs/109/PDF/Slip/LB716.pdf">Slip Law</a>
<table><tbody>
<tr><td class="py-1">Feb 18, 2026</td><td class="py-1">Approved by Governor on February 17, 2026</td></tr>
<tr><td class="py-1">Feb 12, 2026</td><td class="py-1">Presented to Governor on  February 12, 2026</td></tr>
<tr><td class="py-1">Feb 12, 2026</td><td class="py-1">Passed on Final Reading 46-0-3</td></tr>
<tr><td class="py-1">Jan 07, 2026</td><td class="py-1">Date of introduction</td></tr>
</tbody></table>
"""


def test_parse_session_days() -> None:
    assert parse_session_days(SEARCH_HTML, year=2026) == ["2026-01-07", "2026-01-08"]


def test_parse_date_csv() -> None:
    item = parse_date_csv(CSV_TEXT)[0]

    assert item.number == "LB716"
    assert item.sponsor == "Executive Board: Hansen, Chairperson"
    assert item.status == "Passed"
    assert item.document_id == "63242"


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem(
            number="LB716",
            title="fallback",
            sponsor="Executive Board: Hansen, Chairperson",
            status="Passed",
            document_id="63242",
        ),
        session=session_for_year(2026),
    )

    assert bill.jurisdiction == "us-ne"
    assert bill.chamber == Chamber.JOINT
    assert bill.number == "LB716"
    assert bill.title == "Revisor's bill to eliminate obsolete provisions and provisions that have terminated"
    assert bill.sponsors[0].name == "Executive Board: Hansen, Chairperson"
    assert bill.versions[0].source_url == "https://nebraskalegislature.gov/FloorDocs/109/PDF/Intro/LB716.pdf"


def test_parse_bill_page_builds_actions() -> None:
    bill = parse_bill_page(
        DETAIL_HTML,
        item=BillListItem("LB716", "fallback", "Hansen", "Passed", "63242"),
        session=session_for_year(2026),
    )

    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    statuses = [action.normalized_status for action in bill.actions]
    assert NormalizedStatus.PASSED_CHAMBER in statuses
    assert NormalizedStatus.ENROLLED in statuses
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert bill.actions[-1].occurred_at.isoformat() == "2026-02-18T00:00:00-06:00"


def test_extracts_nebraska_citations() -> None:
    assert extract("Amending Neb. Rev. Stat. § 28-101 and section 44-101.") == [
        ("Neb. Rev. Stat. § 28-101", "Neb. Rev. Stat. § 28-101"),
        ("section 44-101", "Neb. Rev. Stat. § 44-101"),
    ]
