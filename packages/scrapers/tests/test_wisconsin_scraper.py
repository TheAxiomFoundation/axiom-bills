from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_wi.bill.scrape import (
    parse_bill_page,
    parse_list_bill_urls,
    session_for_biennium,
)


LIST_HTML = """
<html><body>
  <a href="/2025/proposals/reg/sen/bill/sb1">2025 Senate Bill 1</a>
  <a href="/2025/proposals/reg/asm/bill/ab2">2025 Assembly Bill 2</a>
  <a href="/2025/proposals/reg/sen/res/sr1">Not a bill</a>
</body></html>
"""


BILL_HTML = """
<html><head><title>2025 Senate Bill 1</title></head>
<body>
  <p>An Act Relating to: onetime individual income tax rebates.</p>
  <table>
    <tr class="historyRow">
      <td class="date">2/11/2026 <abbr class="house" title="Senate">Sen.</abbr></td>
      <td class="entry">Introduced by Senators LeMahieu, Bradley and Felzkowski</td>
    </tr>
    <tr class="historyRow">
      <td class="date">2/11/2026 <abbr class="house" title="Senate">Sen.</abbr></td>
      <td class="entry">Read first time and referred to Committee on Agriculture and Revenue</td>
    </tr>
    <tr class="historyRow">
      <td class="date">3/23/2026 <abbr class="house" title="Senate">Sen.</abbr></td>
      <td class="entry">Failed to pass pursuant to Senate Joint Resolution 1</td>
    </tr>
  </table>
  <a href="/document/proposaltext/2025/REG/SB1">Bill Text</a>
  <a href="/document/proposaltext/2025/REG/SB1.pdf">Bill Text PDF</a>
</body></html>
"""


def test_session_for_biennium() -> None:
    session = session_for_biennium(2025)

    assert session.name == "2025-2026 Wisconsin Legislature"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2025-01-01"


def test_parse_list_bill_urls() -> None:
    assert parse_list_bill_urls(LIST_HTML) == [
        "https://docs.legis.wisconsin.gov/2025/proposals/reg/sen/bill/sb1",
        "https://docs.legis.wisconsin.gov/2025/proposals/reg/asm/bill/ab2",
    ]


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://docs.legis.wisconsin.gov/2025/proposals/reg/sen/bill/sb1",
    )

    assert bill is not None
    assert bill.jurisdiction == "us-wi"
    assert bill.chamber == Chamber.UPPER
    assert bill.number == "SB1"
    assert bill.title == "Relating to: onetime individual income tax rebates."
    assert bill.sponsors[0].name == "LeMahieu"
    assert bill.source_url.endswith("/2025/proposals/reg/sen/bill/sb1")


def test_parse_bill_page_extracts_actions_and_versions() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://docs.legis.wisconsin.gov/2025/proposals/reg/sen/bill/sb1",
    )

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[-1].normalized_status == NormalizedStatus.FAILED
    assert bill.versions[0].source_url == (
        "https://docs.legis.wisconsin.gov/document/proposaltext/2025/REG/SB1"
    )
