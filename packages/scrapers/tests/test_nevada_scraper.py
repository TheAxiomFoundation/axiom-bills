from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nv.bill.citations import extract
from axiom_bills.jurisdictions.us_nv.bill.kind import classify
from axiom_bills.jurisdictions.us_nv.bill.scrape import (
    NevadaListItem,
    parse_actions,
    parse_bill,
    parse_bill_list,
    parse_versions,
    session_from_html,
    session_slugs,
)


SESSION_HTML = """
<div class="text-right font-weight-bold session-text">83rd (2025) Session</div>
<p>The 83rd (2025) Session convened on February 3, 2025 at 11:15 AM and adjourned sine die on June 3, 2025 at 12:35 AM.</p>
"""

LIST_HTML = """
<input id="ListItems_0__ContentKey" name="ListItems[0].ContentKey" type="hidden" value="11742" />
<div class="row">
  <div class="col-md-1 text-center"><a id="AB1" href="/App/NELIS/REL/83rd2025/Bill/11742/Overview">AB1</a></div>
  <div class="col-md-10">Voids certain regulations relating to land. (BDR&nbsp;S-299)</div>
</div>
"""

OVERVIEW_HTML = """
<div>
  <div class="row mt-2">
    <div class="col-md-2 font-weight-bold">Summary</div>
    <div class="col">Revises provisions relating to parole. (BDR&nbsp;16-500)</div>
  </div>
  <div class="row mt-2">
    <div class="col-md-2 font-weight-bold">Primary Sponsor</div>
    <div class="col"><a href="/App/NELIS/REL/83rd2025/Committee/447/Overview">Assembly Committee on Judiciary</a></div>
  </div>
  <div id="digest">Existing law cites NRS 213.12155 and chapter 281A of NRS.</div>
  <table class="table">
    <caption class="sr-only">Bill History</caption>
    <tbody>
      <tr class="row">
        <td data-th="Date">Jan 06, 2025</td>
        <td data-th="Action">Prefiled. Referred to Committee on Judiciary. To printer.</td>
      </tr>
      <tr class="row">
        <td data-th="Date">May 29, 2025</td>
        <td data-th="Action">Read third time. Passed, as amended. To Senate.</td>
      </tr>
    </tbody>
  </table>
</div>
"""

TEXT_HTML = """
<div class="d-md-none">
  <a href="https://www.leg.state.nv.us/Session/83rd2025/Bills/AB/AB91.pdf">As Introduced</a>
  <a href="https://www.leg.state.nv.us/Session/83rd2025/Bills/AB/AB91_R1.pdf">Reprint 1</a>
  <a href="https://www.leg.state.nv.us/Session/83rd2025/Bills/Amendments/A_AB91_397.pdf">Amendment 397</a>
</div>
"""


def test_session_and_list_parsing() -> None:
    assert session_slugs('<a href="/App/NELIS/REL/84th2027">84th</a><a href="/App/NELIS/REL/83rd2025">83rd</a>')[:2] == [
        "84th2027",
        "83rd2025",
    ]
    session = session_from_html("83rd2025", SESSION_HTML)
    items = parse_bill_list(LIST_HTML)

    assert session.name == "83rd (2025) Session Nevada Legislature"
    assert session.start_date.isoformat() == "2025-02-03"
    assert session.end_date.isoformat() == "2025-06-03"
    assert items[0].number == "AB 1"
    assert items[0].bill_key == "11742"
    assert items[0].title == "Voids certain regulations relating to land. (BDR S-299)"


def test_bill_actions_and_versions() -> None:
    session = session_from_html("83rd2025", SESSION_HTML)
    item = NevadaListItem(
        number="AB 91",
        title="Revises provisions relating to parole. (BDR 16-500)",
        bill_key="11955",
        source_url="https://www.leg.state.nv.us/App/NELIS/REL/83rd2025/Bill/11955/Overview",
    )
    bill = parse_bill(item, overview_html=OVERVIEW_HTML, text_html=TEXT_HTML, session=session)

    assert bill.chamber == Chamber.LOWER
    assert bill.title == "Revises provisions relating to parole. (BDR 16-500)"
    assert bill.sponsors[0].name == "Assembly Committee on Judiciary"
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert [version.label for version in bill.versions] == ["As Introduced", "Reprint 1", "Amendment 397"]


def test_nevada_kind_status_and_citations() -> None:
    actions = parse_actions(OVERVIEW_HTML)

    assert actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert classify("Makes an appropriation to the Legislative Fund") == BillKind.APPROPRIATIONS
    assert classify("Urges Congress to recognize Nevada") == BillKind.CEREMONIAL
    assert parse_versions(TEXT_HTML)[0].format == "pdf"
    assert extract("Existing law cites NRS 213.12155 and chapter 281A of NRS.") == [
        ("NRS 213.12155", "NRS 213.12155"),
        ("chapter 281A of NRS", "chapter 281A of NRS"),
    ]
