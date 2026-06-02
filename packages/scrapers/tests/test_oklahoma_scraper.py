from __future__ import annotations

from selectolax.parser import HTMLParser

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ok.bill.citations import extract
from axiom_bills.jurisdictions.us_ok.bill.kind import classify
from axiom_bills.jurisdictions.us_ok.bill.scrape import (
    OklahomaListItem,
    OklahomaSessionInfo,
    parse_actions,
    parse_bill,
    parse_status_report,
    parse_versions,
    session_from_info,
)


STATUS_HTML = """
<HTML><BODY><TABLE>
<TR><TD><B>Measure</TD><TD><B>Flags</TD><td><b>Chamber</b></td><TD><B>Status</TD><TD>Date</TD><TD>Title</TD></TR>
<TR>
  <TD><a href='http://www.oklegislature.gov/BillInfo.aspx?Bill=SB60&amp;session=2600'>SB60</a></TD>
  <TD>@d</TD><TD>S</TD><TD>GENERAL ORDER</TD><TD>03/10/2025</TD>
  <TD>Income tax; modifying certain apportionment factors. Effective date.</TD>
</TR>
</TABLE></BODY></HTML>
"""

DETAIL_HTML = """
<span id="ctl00_ContentPlaceHolder1_txtST">Income tax; modifying certain apportionment factors.</span>
<a id="ctl00_ContentPlaceHolder1_lnkAuth" href="https://www.oksenate.gov/Senators/dave-rader">Rader</a>
<a id="ctl00_ContentPlaceHolder1_lnkOtherAuth" href="https://www.okhouse.gov/representatives/Cody-maynard">Maynard</a>
<table id="ctl00_ContentPlaceHolder1_TabContainer1_TabPanel1_tblHouseActions">
  <tr><td>Action</td><td>Journal Page</td><td>Date</td><td>Chamber</td></tr>
  <tr><td>First Reading</td><td>75</td><td>02/03/2025</td><td>S</td></tr>
  <tr><td>Second Reading referred to Revenue and Taxation</td><td>291</td><td>02/04/2025</td><td>S</td></tr>
  <tr><td>Placed on General Order</td><td></td><td>03/10/2025</td><td>S</td></tr>
</table>
<table id="ctl00_ContentPlaceHolder1_TabContainer1_TabPanel4_tblVersions">
  <tr><td><a href='https://www.oklegislature.gov/cf_pdf/2025-26 INT/SB/SB60 INT.PDF'>Introduced</a></td><td>12/18/2024</td></tr>
  <tr><td><a href='https://www.oklegislature.gov/cf_pdf/2025-26 FLR/SFLR/SB60 SFLR.PDF'>Floor (Senate)</a></td><td>3/6/2025</td></tr>
</table>
"""


def test_status_report_and_session_parsing() -> None:
    session = session_from_info(OklahomaSessionInfo("2600", "2026 Regular Session"))
    item = parse_status_report(STATUS_HTML)[0]

    assert session.name == "2026 Oklahoma Regular Session"
    assert item.number == "SB 60"
    assert item.status == "GENERAL ORDER"
    assert item.status_date is not None
    assert item.status_date.date().isoformat() == "2025-03-10"
    assert item.source_url == "https://www.oklegislature.gov/BillInfo.aspx?Bill=SB60&Session=2600"


def test_bill_actions_versions_and_sponsors() -> None:
    item = OklahomaListItem(
        number="SB 60",
        title="Income tax; modifying certain apportionment factors. Effective date.",
        status="GENERAL ORDER",
        status_date=None,
        chamber_code="S",
        source_url="https://www.oklegislature.gov/BillInfo.aspx?Bill=SB60&Session=2600",
    )
    session = session_from_info(OklahomaSessionInfo("2600", "2026 Regular Session"))
    bill = parse_bill(item, detail_html=DETAIL_HTML, session=session)

    assert bill.chamber == Chamber.UPPER
    assert bill.sponsors[0].name == "Rader"
    assert bill.sponsors[1].role == "cosponsor"
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[-1].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert [version.label for version in bill.versions] == ["Introduced", "Floor (Senate)"]


def test_oklahoma_kind_status_and_citations() -> None:
    assert parse_actions(HTMLParser(DETAIL_HTML))[1].chamber == Chamber.UPPER
    assert parse_versions(HTMLParser(DETAIL_HTML))[0].format == "pdf"
    assert classify("Appropriation; Oklahoma Military Department; effective date.") == BillKind.APPROPRIATIONS
    assert classify("Commending citizens for service") == BillKind.CEREMONIAL
    assert extract(
        "Amends 47 O.S. 2021, Section 11-902 and Section 1-102 of Title 47 of the Oklahoma Statutes."
    ) == [
        ("47 O.S. 2021, Section 11-902", "47 O.S. 2021, Section 11-902"),
        (
            "Section 1-102 of Title 47 of the Oklahoma Statutes",
            "Section 1-102 of Title 47 of the Oklahoma Statutes",
        ),
    ]
