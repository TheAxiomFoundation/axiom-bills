from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ak.bill.citations import extract
from axiom_bills.jurisdictions.us_ak.bill.scrape import (
    parse_bill_list,
    parse_bill_page,
    session_for_id,
    session_id_for_year,
)


LIST_HTML = """
<table><tr><th>Bill</th><th>Short Title</th><th>Prime Sponsor(s)</th><th></th><th>Current Status</th><th>Status Date</th></tr>
<tr class="House">
<td class="billRoot"><a href="/basis/Bill/Detail/34?Root=HB   1">HB   1</a></td>
<td class="col02">SPECIE AS LEGAL TENDER</td>
<td class="col03">REPRESENTATIVE MCCABE<br>SENATOR RAUSCHER</td>
<td></td><td class="col04">CHAPTER 6 SLA 26</td><td class="col05">05/29/2026</td>
</tr>
</table>
"""

DETAIL_HTML = """
<ul class="information">
<li><span>Bill </span><strong>HB   1</strong></li>
<li><span>Current Status </span><strong>CHAPTER 6 SLA 26</strong></li>
<li><span>Status Date </span><strong>05/29/2026</strong></li>
</ul>
<ul class="information">
<li><span>Bill Version</span><strong>CSHB 1(STA)</strong></li>
<li><span>Short Title </span><strong>SPECIE AS LEGAL TENDER</strong></li>
</ul>
<ul class="information">
<li><span>Sponsor(S) </span><strong> REPRESENTATIVES MCCABE, Underwood<br>SENATORS Rauscher</strong></li>
<li><span>Title</span><strong>"An Act relating to specie as legal tender in the state."</strong></li>
</ul>
<div class="fulltext" id="tab1_4">
<table><tbody>
<tr><td><span><a href="/basis/Bill/Text/34?Hsid=HB0001A">HB0001A</a></span></td>
<td><span class="blue">HB 1</span></td>
<td><a class="pdf" href="https://www.akleg.gov/PDF/34/Bills/HB0001A.PDF">pdf</a></td></tr>
<tr class="Merrors"><td></td><td><a href="https://www.akleg.gov/PDF/34/ManifestErrors/HB1.pdf">Manifest Error(s)</a></td>
<td><a class="pdf" href="https://www.akleg.gov/PDF/34/ManifestErrors/HB1.pdf">pdf</a></td></tr>
</tbody></table>
</div>
<table><tbody>
<tr class="floorAction"><td><time datetime="2026-05-07">5/7/2026</time></td><td></td>
<td><span data-label="Text" class="text">(H) PASSED Y40</span></td></tr>
<tr class="floorAction"><td><time datetime="2026-05-13">5/13/2026</time></td><td></td>
<td><span data-label="Text" class="text">(H) 2:55 P.M. 5/13/26 TRANSMITTED TO GOVERNOR</span></td></tr>
<tr class="floorAction"><td><time datetime="2026-05-29">5/29/2026</time></td><td></td>
<td><span data-label="Text" class="text">(H) LAW W/O GOV SIGNATURE 5/29 CH 6 SLA 26</span></td></tr>
</tbody></table>
<ul class="list-links"><li><a href="/basis/Bill/Subject/34?subject=FINANCE">FINANCE</a></li></ul>
"""


def test_session_helpers() -> None:
    assert session_id_for_year(2025) == 34
    assert session_id_for_year(2026) == 34
    assert session_for_id(34).name == "34th Alaska Legislature (2025-2026)"


def test_parse_bill_list() -> None:
    item = parse_bill_list(LIST_HTML)[0]

    assert item.number == "HB 1"
    assert item.title == "SPECIE AS LEGAL TENDER"
    assert item.sponsors == ["Representative Mccabe", "Senator Rauscher"]
    assert item.status == "CHAPTER 6 SLA 26"
    assert item.status_date.isoformat() == "2026-05-29"
    assert item.detail_url == "https://www.akleg.gov/basis/Bill/Detail/34?Root=HB   1"


def test_parse_bill_page_extracts_core_fields() -> None:
    item = parse_bill_list(LIST_HTML)[0]
    bill = parse_bill_page(DETAIL_HTML, item=item, session=session_for_id(34))

    assert bill is not None
    assert bill.jurisdiction == "us-ak"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB 1"
    assert bill.title == "An Act relating to specie as legal tender in the state."
    assert bill.subjects == ["FINANCE"]
    assert bill.versions[0].label == "HB0001A - HB 1"
    assert bill.versions[0].source_url.endswith("HB0001A.PDF")


def test_parse_bill_page_builds_actions() -> None:
    item = parse_bill_list(LIST_HTML)[0]
    bill = parse_bill_page(DETAIL_HTML, item=item, session=session_for_id(34))

    assert bill is not None
    statuses = [action.normalized_status for action in bill.actions]
    assert statuses == [
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.ENACTED,
    ]


def test_extracts_alaska_citations() -> None:
    assert extract("Amend AS 29.45.650 and Alaska Statutes section 43.05.001.") == [
        ("AS 29.45.650", "AS 29.45.650"),
        ("Alaska Statutes section 43.05.001", "AS 43.05.001"),
    ]
