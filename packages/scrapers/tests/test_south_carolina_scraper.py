from __future__ import annotations

from selectolax.parser import HTMLParser

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus, Session
from axiom_bills.jurisdictions.us_sc.bill.citations import extract
from axiom_bills.jurisdictions.us_sc.bill.kind import classify
from axiom_bills.jurisdictions.us_sc.bill.scrape import (
    intro_page_urls,
    parse_actions,
    parse_billsearch,
    parse_intro_page,
    parse_versions,
)


INDEX_HTML = """
<b><a href="/sess126_2025-2026/hintro26/20260518.htm">Monday, May 18, 2026</a></b><br>
<b><a href="/sess126_2025-2026/hintro25/20250114.htm">Tuesday, January 14, 2025</a></b><br>
"""

INTRO_HTML = """
<center>Legislation Introduced into the Senate</center>
<a href="/billsearch.php?billnumbers=1201&amp;session=126&amp;summary=B">S. 1201</a></a>
(<a href="/sess126_2025-2026/bills/1201.docx">Word</a> version) -- Senator Grooms:
A CONCURRENT RESOLUTION TO REQUEST THAT THE DEPARTMENT OF TRANSPORTATION NAME A BRIDGE.
"""

BILLSEARCH_HTML = """
<div class="bill-list-item" data-bhmastkey="1263843"><a name="3843"></a>
<span style="font-weight:bold;">H 3843 General Bill, By <a href="/member.php?code=103409079&amp;chamber=H">Bannister</a><br></span>
&nbsp;&nbsp;A BILL TO AMEND THE SOUTH CAROLINA CODE OF LAWS BY ADDING SECTION 59-17-170 SO AS TO CODIFY CERTAIN PROVISOS.
<br><A class="nodisplay" HREF="/sess126_2025-2026/bills/3843.htm">View full text</A>
<table>
<tr><td>01/30/25</td><td>House</td><td>Introduced and read first time</td></tr>
<tr><td>01/30/25</td><td>House</td><td>Referred to Committee on Ways and Means</td></tr>
<tr><td>02/21/25</td><td>House</td><td>Read third time and sent to Senate</td></tr>
</table>
</div>
"""


def test_intro_index_and_page_parsing() -> None:
    urls = intro_page_urls(INDEX_HTML)
    items = parse_intro_page(INTRO_HTML)

    assert urls == [
        "https://www.scstatehouse.gov/sess126_2025-2026/hintro26/20260518.htm",
        "https://www.scstatehouse.gov/sess126_2025-2026/hintro25/20250114.htm",
    ]
    assert items[0].number == "S 1201"
    assert items[0].compact_number == "s1201"


def test_billsearch_parsing() -> None:
    session = Session(name="2025-2026 South Carolina Legislative Session")
    bill = parse_billsearch(BILLSEARCH_HTML, session=session)[0]

    assert bill.number == "H 3843"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Bannister"
    assert bill.title.startswith("A BILL TO AMEND")
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.versions[0].format == "html"


def test_south_carolina_kind_status_and_citations() -> None:
    session = Session(name="2025-2026 South Carolina Legislative Session")
    bill = parse_billsearch(BILLSEARCH_HTML, session=session)[0]
    item = HTMLParser(BILLSEARCH_HTML).css_first(".bill-list-item")

    assert item is not None
    assert parse_actions(item)[0].chamber == Chamber.LOWER
    assert parse_versions(item)[0].label == "View full text"
    assert classify("A BILL MAKING APPROPRIATIONS FOR STATE GOVERNMENT") == BillKind.APPROPRIATIONS
    assert classify("A RESOLUTION TO HONOR A CHAMPION") == BillKind.CEREMONIAL
    assert extract(bill.title) == [("SECTION 59-17-170", "SECTION 59-17-170")]
