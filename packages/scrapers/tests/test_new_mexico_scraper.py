from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nm.bill.citations import extract
from axiom_bills.jurisdictions.us_nm.bill.kind import classify
from axiom_bills.jurisdictions.us_nm.bill.scrape import (
    NewMexicoLocatorItem,
    NewMexicoSession,
    parse_actions,
    parse_bill,
    parse_directory_versions,
    parse_locator,
    session_from_info,
)


LOCATOR_HTML = """
<table id="MainContent_gridViewLegislation">
  <tr><th>Bill ID</th><th>Title</th><th>Sponsor</th><th>Actions</th><th>Session</th></tr>
  <tr>
    <td><a href="Legislation?chamber=H&amp;legType=B&amp;legNo=1&amp;year=26">*HB 1</a></td>
    <td><span>FEED BILL</span></td>
    <td><a>Reena Szczepanski</a></td>
    <td><span>[1] HAFC-HAFC- DP - PASSED/H (54-2)- SFC-SFC- DP [3] PASSED/S (39-0) [2] SGND BY GOV (Jan. 27) Ch. 1.</span></td>
    <td>2026 Regular</td>
  </tr>
</table>
"""

DIRECTORY_HTML = """
<html><body><pre>
<A HREF="/Sessions/26%20Regular/bills/house/HB0001.HTML">HB0001.HTML</A>
<A HREF="/Sessions/26%20Regular/bills/house/HB0001.PDF">HB0001.PDF</A>
<A HREF="/Sessions/26%20Regular/bills/house/HB0001AF1.HTML">HB0001AF1.HTML</A>
</pre></body></html>
"""


def test_locator_and_bill_parsing() -> None:
    session = session_from_info(NewMexicoSession("26", "72", "2026 Regular", "26 Regular"))
    item = parse_locator(LOCATOR_HTML)[0]
    bill = parse_bill(item, session=session, versions=[])

    assert session.name == "2026 New Mexico Regular Session"
    assert item.number == "HB 1"
    assert item.sponsors == ["Reena Szczepanski"]
    assert bill.jurisdiction == "us-nm"
    assert bill.chamber == Chamber.LOWER
    assert bill.kind == BillKind.APPROPRIATIONS
    assert bill.source_url == "https://www.nmlegis.gov/Legislation?chamber=H&legType=B&legNo=1&year=26"


def test_actions_and_versions() -> None:
    session = session_from_info(NewMexicoSession("26", "72", "2026 Regular", "26 Regular"))
    item = NewMexicoLocatorItem(
        number="HB 1",
        title="FEED BILL",
        sponsors=["Reena Szczepanski"],
        actions="[1] HAFC-HAFC- DP - PASSED/H (54-2)- SFC-SFC- DP [3] PASSED/S (39-0) [2] SGND BY GOV (Jan. 27) Ch. 1.",
        detail_url="https://www.nmlegis.gov/Legislation/Legislation?chamber=H&legType=B&legNo=1&year=26",
    )
    actions = parse_actions(item.actions, session=session)
    versions = parse_directory_versions(DIRECTORY_HTML)

    assert actions[0].normalized_status == NormalizedStatus.ENACTED
    assert actions[0].occurred_at.date().isoformat() == "2026-01-27"
    assert [version.format for version in versions] == ["html", "pdf", "html"]


def test_new_mexico_kind_and_citations() -> None:
    assert classify("General Appropriation Act of 2026") == BillKind.APPROPRIATIONS
    assert classify("Memorial recognizing a champion") == BillKind.CEREMONIAL
    assert extract("Amends Section 30-31-6 NMSA 1978 and 10-7-3 NMSA 1978.") == [
        ("Section 30-31-6 NMSA 1978", "Section 30-31-6 NMSA 1978"),
        ("10-7-3 NMSA 1978", "10-7-3 NMSA 1978"),
    ]
