from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ia.bill.citations import extract
from axiom_bills.jurisdictions.us_ia.bill.kind import classify
from axiom_bills.jurisdictions.us_ia.bill.scrape import (
    parse_actions,
    parse_all_bills,
    parse_bill,
    parse_sponsors,
    parse_versions,
    session_from_all_bills,
)


ALL_BILLS_HTML = """
<ul class="selectionList ga">
  <li class="selected" data-ga="91">
    <span>General Assembly: 91 <span class="r">(01/13/2025 - 01/10/2027)</span></span>
  </li>
</ul>
<table id="sortableTable">
  <tr><th>Bill_prefix</th><th>Bill</th><th>Bill Title</th><th>Companion</th><th>Similar</th><th>Sponsor</th></tr>
  <tr>
    <td>HF</td>
    <td><a href="/legislation/BillBook?ga=91&amp;ba=HF 1">HF 1</a></td>
    <td>A bill for an act relating to school attendance. (See HF 189.)</td>
    <td>SF 22</td>
    <td>HF 189</td>
    <td>STONE</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<input type="hidden" name="selectedBill" value="HF 1">
<h1>HF 1</h1>
<div class="docOutputTypes">
  <iframe src="/docs/publications/LGI/91/attachments/HF1.html?layout=false"></iframe>
  <a href="/docs/publications/LGI/91/HF1.pdf">PDF</a>
  <a href="/docs/publications/LGI/91/attachments/HF1.rtf">RTF</a>
</div>
"""

ACTION_HTML = """
<table class="billActionTable widgetTable">
  <tbody>
    <tr><td>03/21/2025</td><td>Withdrawn. <a href="/docs/publications/HJNL/20250321_HJNL.pdf#page=3">H.J. 772</a>.</td></tr>
    <tr><td>01/30/2025</td><td>Committee report approving bill, renumbered as <a href="/legislation/BillBook?ga=91&amp;ba=HF 189">HF 189</a>.</td></tr>
    <tr><td>01/14/2025</td><td>Introduced, referred to Education. <a href="/docs/publications/HJNL/20250114_HJNL.pdf#page=2">H.J. 38</a>.</td></tr>
  </tbody>
</table>
"""


def test_session_and_all_bills_parsing() -> None:
    session = session_from_all_bills(ALL_BILLS_HTML, 91)
    items = parse_all_bills(ALL_BILLS_HTML, general_assembly=91)

    assert session.name == "91st Iowa General Assembly (2025-2027)"
    assert items[0].number == "HF 1"
    assert items[0].title == "A bill for an act relating to school attendance. (See HF 189.)"
    assert items[0].detail_url == "https://www.legis.iowa.gov/legislation/BillBook?ga=91&ba=HF%201"
    assert items[0].sponsor == "STONE"


def test_actions_versions_and_sponsors() -> None:
    actions = parse_actions(ACTION_HTML, fallback_chamber=Chamber.LOWER)
    versions = parse_versions(DETAIL_HTML)
    sponsors = parse_sponsors("STONE, A. MEYER")

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.FAILED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.format for version in versions] == ["html", "pdf", "txt"]
    assert [sponsor.name for sponsor in sponsors] == ["STONE", "A. MEYER"]


def test_parse_bill_core_fields() -> None:
    item = parse_all_bills(ALL_BILLS_HTML, general_assembly=91)[0]
    bill = parse_bill(item, DETAIL_HTML, ACTION_HTML, session=session_from_all_bills(ALL_BILLS_HTML, 91))

    assert bill.jurisdiction == "us-ia"
    assert bill.number == "HF 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.title == "A bill for an act relating to school attendance. (See HF 189.)"
    assert bill.summary == "A bill for an act relating to school attendance. (See HF 189.)"
    assert bill.subjects == ["Companion: SF 22", "Similar: HF 189"]
    assert bill.versions[0].source_url == "https://www.legis.iowa.gov/docs/publications/LGI/91/attachments/HF1.html?layout=false"


def test_iowa_kind_and_citations() -> None:
    assert classify("A bill for an act making appropriations") == BillKind.APPROPRIATIONS
    assert classify("A resolution honoring Iowa veterans") == BillKind.CEREMONIAL
    assert extract("Amend Iowa Code section 321.1 and section 331.301, Code.") == [
        ("Iowa Code section 321.1", "Iowa Code section 321.1"),
        ("section 331.301, Code", "section 331.301, Code"),
    ]
