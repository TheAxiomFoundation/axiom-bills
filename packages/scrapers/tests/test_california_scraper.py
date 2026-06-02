from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ca.bill.citations import extract
from axiom_bills.jurisdictions.us_ca.bill.scrape import (
    CaliforniaBillPage,
    bill_id_for,
    parse_bill,
    parse_history_actions,
    parse_status_fields,
    parse_versions,
    session_for_year,
)


STATUS_HTML = """
<html><body>
<span id="measureNum">AB-1</span>
<span id="leadAuthors">Connolly (A)</span>
<span id="principalAuthors">-</span>
<span id="coAuthors">Addis (A) , Allen (S)</span>
<span id="subject">Residential property insurance: wildfire risk.</span>
<span id="title">An act to add Article 5 (commencing with Section 2095) to Chapter 2 of Part 1 of Division 2 of the Insurance Code, relating to insurance.</span>
<span id="houseLoc">Secretary of State</span>
<span id="lastAction">10/09/25</span>
<select id="version" name="version">
  <option value="20250AB197CHP">10/09/25 - Chaptered</option>
  <option value="20250AB198ENR">09/15/25 - Enrolled</option>
  <option value="20250AB199INT">12/02/24 - Introduced</option>
</select>
</body></html>
"""

HISTORY_HTML = """
<html><body>
<table id="billhistory">
  <tr><th>Date</th><th>Action</th></tr>
  <tr><td>10/09/25</td><td>Chaptered by Secretary of State - Chapter 472, Statutes of 2025.</td></tr>
  <tr><td>10/09/25</td><td>Approved by the Governor.</td></tr>
  <tr><td>09/23/25</td><td>Enrolled and presented to the Governor at 4 p.m.</td></tr>
  <tr><td>09/11/25</td><td>Read third time. Passed. Ordered to the Assembly. (Ayes 40. Noes 0.)</td></tr>
  <tr><td>06/11/25</td><td>Referred to Com. on INS.</td></tr>
  <tr><td>06/03/25</td><td>In Senate. Read first time. To Com. on RLS. for assignment.</td></tr>
</table>
</body></html>
"""


def test_session_and_bill_id() -> None:
    session = session_for_year("20252026")

    assert bill_id_for("20252026", "AB", 1) == "202520260AB1"
    assert session.name == "2025-2026 California Regular Session"
    assert session.start_date.isoformat() == "2025-01-01"
    assert session.end_date.isoformat() == "2026-12-31"


def test_parse_status_fields_versions_and_actions() -> None:
    fields = parse_status_fields(STATUS_HTML)
    versions = parse_versions(STATUS_HTML, bill_id="202520260AB1")
    actions = parse_history_actions(HISTORY_HTML)

    assert fields["Measure"] == "AB-1"
    assert fields["Lead Authors"] == "Connolly (A)"
    assert fields["Topic"] == "Residential property insurance: wildfire risk."
    assert [version.label for version in versions] == [
        "chaptered",
        "chaptered pdf",
        "enrolled",
        "enrolled pdf",
        "introduced",
        "introduced pdf",
    ]
    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.ENACTED,
        NormalizedStatus.SIGNED,
    ]
    assert actions[0].chamber == Chamber.UPPER


def test_parse_bill_core_fields() -> None:
    bill = parse_bill(
        CaliforniaBillPage(
            bill_id="202520260AB1",
            number="AB-1",
            status_html=STATUS_HTML,
            history_html=HISTORY_HTML,
        ),
        session=session_for_year("20252026"),
    )

    assert bill.jurisdiction == "us-ca"
    assert bill.number == "AB-1"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Connolly (A)"
    assert bill.sponsors[0].role == "primary"
    assert bill.kind == BillKind.SUBSTANTIVE
    assert len(bill.actions) == 6
    assert len(bill.versions) == 6


def test_california_kind_and_citations() -> None:
    from axiom_bills.jurisdictions.us_ca.bill.kind import classify

    assert classify("budget act of 2026") == BillKind.APPROPRIATIONS
    assert extract("Amend Section 2095 of the Insurance Code and Chapter 472, Statutes of 2025.") == [
        ("Section 2095 of the Insurance Code", "Section 2095 of the Insurance Code"),
        ("Chapter 472, Statutes of 2025", "Chapter 472, Statutes of 2025"),
    ]
