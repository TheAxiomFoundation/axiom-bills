from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_vt.bill.citations import extract
from axiom_bills.jurisdictions.us_vt.bill.kind import classify
from axiom_bills.jurisdictions.us_vt.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_detail_page,
    parse_versions,
    session_from_biennium,
)


ROW = {
    "Body": "H",
    "BillNumber": "H.812",
    "Title": "An act relating to data loyalty",
    "Title1": "An act relating to data loyalty",
    "ActNo": "",
    "ActLink": "",
}

DETAIL_HTML = """
<div class="bill-title">
  <h1>H.812</h1>
  <h4 class="charge">An act relating to data loyalty</h4>
</div>
<div id="bill-sponsors" class="sr-only">
Rep. Monique Priestley
Rep. Another Sponsor
</div>
<div id="bill-location" class="sr-only">House Committee on Commerce and Economic Development</div>
<script>
  var detailed_status_table = $('#bill-detailed-status-table').DataTable({
    "ajax": {"url": "bill/loadBillDetailedStatus/2026/1460"}
  });
</script>
"""

ACTIONS = [
    {
        "StatusDate": "1/29/2026",
        "ChamberCode": "H",
        "FullStatus": "Read first time and referred to the Committee on <strong>Commerce and Economic Development</strong>",
        "keywords": ";Introduced;Comin;billassign;",
        "Location": "In Committee",
        "Url": "Documents/2026/Docs/JOURNAL/hj260129.pdf#page=1",
    },
    {
        "StatusDate": "5/14/2026",
        "ChamberCode": "S",
        "FullStatus": "House message: Governor approved bill on May 13, 2026",
        "keywords": "",
        "Location": "",
        "Url": "",
    },
]

VERSIONS = {
    "Introduced": {
        "Url": "/Documents/2026/Docs/BILLS/H-0812/H-0812 As Introduced.pdf",
        "DisplayName": "As Introduced",
    }
}


def test_vermont_session_detail_and_bill_parsing() -> None:
    session = session_from_biennium("2026")
    detail = parse_detail_page(DETAIL_HTML)
    bill = parse_bill(
        ROW,
        detail=detail,
        status_rows=ACTIONS,
        version_rows=VERSIONS,
        session=session,
        biennium="2026",
    )

    assert session.name == "2025-2026 Vermont Regular Session"
    assert detail["status_id"] == "1460"
    assert bill.number == "H.812"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Rep. Monique Priestley"
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert bill.versions[0].format == "pdf"


def test_vermont_actions_versions_kind_and_citations() -> None:
    actions = parse_actions(ACTIONS)
    versions = parse_versions(VERSIONS)

    assert actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert actions[0].source_url == "https://legislature.vermont.gov/Documents/2026/Docs/JOURNAL/hj260129.pdf#page=1"
    assert versions[0].label == "As Introduced"
    assert classify("An act relating to making appropriations for State government") == BillKind.APPROPRIATIONS
    assert classify("A resolution congratulating a championship team") == BillKind.CEREMONIAL
    assert extract("This bill amends 13 V.S.A. § 7554 and the Vermont Statutes Annotated.") == [
        ("13 V.S.A. § 7554", "13 V.S.A. § 7554"),
        ("Vermont Statutes Annotated", "Vermont Statutes Annotated"),
    ]
