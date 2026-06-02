from __future__ import annotations

from axiom_bills._common.models import Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_mn.bill.scrape import (
    parse_bill_page,
    parse_search_bill_urls,
)


SEARCH_HTML = """
<html>
  <body>
    <table>
      <tr><th>Session</th><th>House Bill</th><th>Senate Bill</th></tr>
      <tr>
        <td>2025 Regular</td>
        <td><a href="/revisor/pages/search_status/status_detail.php?b=house&f=HF169&ssn=0&y=2025">HF169</a></td>
        <td><a href="/revisor/pages/search_status/status_detail.php?b=senate&f=SF1941&ssn=0&y=2025">SF1941</a></td>
      </tr>
      <tr>
        <td>2026 Regular</td>
        <td><a href="/bills/94/2026/0/HF/3459/">HF3459</a></td>
        <td><a href="/bills/94/2026/0/HF/3459/versions/0/pdf/">PDF ignored</a></td>
      </tr>
    </table>
  </body>
</html>
"""


BILL_HTML = """
<html>
  <body>
    <h1>HF 169</h1>
    <p>Status in the House - 94th Legislature (2025 - 2026)</p>
    <p>Current bill text: As Introduced</p>
    <p>Revisor number: 25-01431</p>
    <h2>Bill Text Versions</h2>
    <table>
      <tr>
        <td><a href="/bills/94/2025/0/HF/169/versions/0/pdf/">Introduction PDF</a></td>
        <td>Posted on 02/10/2025</td>
      </tr>
    </table>
    <h2>Description</h2>
    <p>All lawful gambling receipts subjected to a flat rate tax, and combined net receipts tax repealed.</p>
    <h2>Authors (2)</h2>
    <ul>
      <li>Robbins;</li>
      <li>Harder;</li>
    </ul>
    <h2>Actions</h2>
    <h3>House</h3>
    <table>
      <tr><td>02/10/2025</td><td>Introduction and first reading, referred to Taxes pg. 81 Intro</td></tr>
      <tr><td>03/20/2025</td><td>Third reading Passed</td></tr>
    </table>
    <h3>House Actions</h3>
  </body>
</html>
"""


def test_parse_search_bill_urls_handles_revisor_url_shapes() -> None:
    assert parse_search_bill_urls(SEARCH_HTML) == [
        "https://www.revisor.mn.gov/revisor/pages/search_status/status_detail.php?b=house&f=HF169&ssn=0&y=2025",
        "https://www.revisor.mn.gov/revisor/pages/search_status/status_detail.php?b=senate&f=SF1941&ssn=0&y=2025",
        "https://www.revisor.mn.gov/bills/94/2026/0/HF/3459/",
    ]


def test_parse_bill_page_extracts_core_fields() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://www.revisor.mn.gov/revisor/pages/search_status/status_detail.php?b=house&f=HF169&ssn=0&y=2025",
    )

    assert bill is not None
    assert bill.jurisdiction == "us-mn"
    assert bill.session_name == "94th Legislature (2025 - 2026)"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HF169"
    assert bill.title == (
        "All lawful gambling receipts subjected to a flat rate tax, and "
        "combined net receipts tax repealed."
    )
    assert [s.name for s in bill.sponsors] == ["Robbins", "Harder"]
    assert bill.versions[0].source_url == (
        "https://www.revisor.mn.gov/bills/94/2025/0/HF/169/versions/0/pdf/"
    )


def test_parse_bill_page_extracts_actions_with_statuses() -> None:
    bill = parse_bill_page(
        BILL_HTML,
        url="https://www.revisor.mn.gov/revisor/pages/search_status/status_detail.php?b=house&f=HF169&ssn=0&y=2025",
    )

    assert bill is not None
    assert len(bill.actions) == 2
    assert bill.actions[0].chamber == Chamber.LOWER
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.PASSED_CHAMBER
