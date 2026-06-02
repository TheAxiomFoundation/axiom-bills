from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ct.bill.citations import extract
from axiom_bills.jurisdictions.us_ct.bill.scrape import (
    display_number_for,
    parse_actions,
    parse_bill,
    parse_page,
    parse_sponsors,
    parse_versions,
    query_number_for,
    session_for_year,
)


PUBLIC_ACT_HTML = """
<html><body>
<h3 class="text-center">
  <strong>S.B. No. 298 </strong><br>Session Year 2026<br />
</h3>
<div class="large-12 columns">
  <h4>AN ACT CONCERNING THE REALLOCATION OF CERTAIN STATE FUNDS.</h4>
  <p class="text-justify"></p>
  <h5>Introduced by: </h5>
  <a href="/asp/CGABillStatus/CGAMemberBills.asp?dist_code='S11'">Sen. Martin M. Looney, 11th Dist.</a><br>
  <a href="/asp/CGABillStatus/CGAMemberBills.asp?dist_code='001'">Rep. Matthew Ritter, 1st Dist.</a><br>
</div>
<table summary='Status of bills' class='footable table'>
  <thead><tr><td>&nbsp;</td><td>&nbsp;&nbsp;Text of Bill</td></tr></thead>
  <tbody>
    <tr><td>&nbsp;</td><td><a href="/2026/ACT/PA/PDF/2026PA-00001-R00SB-00298-PA.PDF">Public Act No. 26-1</a>&nbsp;<a href="https://search.cga.state.ct.us/dl2026/PA/DOC/2026PA-00001-R00SB-00298-PA.DOCX">[doc]</a></td></tr>
    <tr><td>&nbsp;</td><td><a href="/2026/TOB/S/PDF/2026SB-00298-R00-SB.PDF">New Bill</a><a href="https://search.cga.state.ct.us/dl2026/tob/doc/2026SB-00298-R00-SB.docx"> [doc]</a></td></tr>
  </tbody>
</table>
<table summary='Status of bills' class='footable table'>
  <thead><tr><td>&nbsp;</td><td>&nbsp;&nbsp;Called Amendments</td></tr></thead>
  <tbody>
    <tr><td>&nbsp;</td><td><a href="/2026/amd/S/pdf/2026SB-00298-R00HD-AMD.pdf">House Schedule D LCO# 2413 (R)</a></td></tr>
  </tbody>
</table>
<h4 style="padding-left:10px">Bill History</h4>
<table summary='Bill history' class='footable table'>
  <thead><tr><th>&nbsp;</th><th>Date</th><th>&nbsp;</th><th>Action Taken</th></tr></thead>
  <tbody>
    <tr><td>&nbsp;</td><td>5/15/2026</td><td></td><td>Transmitted to the Secretary of State</td></tr>
    <tr><td>&nbsp;</td><td>3/5/2026</td><td>(LCO)</td><td>Public Act 26-1</td></tr>
    <tr><td>&nbsp;</td><td>3/3/2026</td><td></td><td>Signed by Governor in Original</td></tr>
    <tr><td>&nbsp;</td><td>2/27/2026</td><td></td><td>Rules Suspended, Transmitted to the Governor</td></tr>
    <tr><td>&nbsp;</td><td>2/26/2026</td><td></td><td>In Concurrence</td></tr>
    <tr><td>&nbsp;</td><td>2/26/2026</td><td></td><td>House Passed</td></tr>
    <tr><td>&nbsp;</td><td>2/25/2026</td><td></td><td>Senate Passed</td></tr>
  </tbody>
</table>
</body></html>
"""

COMMITTEE_HTML = """
<html><body>
<h3 class="text-center">
  <strong>Substitute for Raised H.B. No. 5001 </strong><br>Session Year 2026<br />
</h3>
<div class="large-12 columns">
  <h4>AN ACT CONCERNING ABSENTEE VOTING FOR ALL.</h4>
  <p class="text-justify">To remove the statutory restrictions on eligibility for absentee voting.</p>
  <h5>Introduced by: </h5>
  Government Administration and Elections Committee
</div>
<table summary='Status of bills' class='footable table'>
  <thead><tr><td>&nbsp;</td><td>&nbsp;&nbsp;Text of Bill</td></tr></thead>
  <tbody>
    <tr><td>&nbsp;</td><td><a href="/2026/TOB/H/PDF/2026HB-05001-R00-HB.PDF">Raised Bill</a></td></tr>
  </tbody>
</table>
<table summary='Bill history' class='footable table'>
  <thead><tr><th>&nbsp;</th><th>Date</th><th>&nbsp;</th><th>Action Taken</th></tr></thead>
  <tbody>
    <tr><td>&nbsp;</td><td>3/6/2026</td><td></td><td>Referred to Joint Committee on Government Administration and Elections</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_number_helpers_and_session() -> None:
    session = session_for_year(2026)

    assert query_number_for("HB", 5001) == "HB05001"
    assert display_number_for("SB00298") == "SB-298"
    assert session.name == "2026 Connecticut Regular Session"
    assert session.start_date.isoformat() == "2026-02-01"


def test_parse_versions_sponsors_and_actions() -> None:
    sponsors = parse_sponsors(PUBLIC_ACT_HTML)
    versions = parse_versions(PUBLIC_ACT_HTML)
    actions = parse_actions(PUBLIC_ACT_HTML)

    assert [sponsor.name for sponsor in sponsors] == [
        "Sen. Martin M. Looney",
        "Rep. Matthew Ritter",
    ]
    assert [version.label for version in versions] == [
        "public act",
        "new bill",
        "house schedule d lco# 2413 (r)",
    ]
    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.PASSED_BOTH,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.SIGNED,
        NormalizedStatus.ENACTED,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.UPPER


def test_parse_bill_core_fields() -> None:
    page = parse_page("HB05001", COMMITTEE_HTML)
    assert page is not None

    bill = parse_bill(page, session=session_for_year(2026))

    assert bill.jurisdiction == "us-ct"
    assert bill.number == "HB-5001"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Government Administration and Elections Committee"
    assert bill.summary == "To remove the statutory restrictions on eligibility for absentee voting."
    assert bill.actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE


def test_connecticut_kind_and_citations() -> None:
    from axiom_bills.jurisdictions.us_ct.bill.kind import classify

    assert classify("AN ACT MAKING ADJUSTMENTS TO THE STATE BUDGET.") == BillKind.APPROPRIATIONS
    assert extract("Amend section 9-140 of the general statutes and Public Act 26-42.") == [
        ("section 9-140 of the general statutes", "section 9-140 of the general statutes"),
        ("Public Act 26-42", "Public Act 26-42"),
    ]
