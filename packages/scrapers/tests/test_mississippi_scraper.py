from __future__ import annotations

import xml.etree.ElementTree as ET

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_ms.bill.citations import extract
from axiom_bills.jurisdictions.us_ms.bill.kind import classify
from axiom_bills.jurisdictions.us_ms.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_listing,
    parse_subjects,
    parse_versions,
    session_for_year,
)


LIST_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<LASTACTION>
  <MSRGROUP>
    <MEASURE>HB   1</MEASURE>
    <MEASURELINK>../../../documents/2026/pdf/HB/0001-0099/HB0001SG.pdf</MEASURELINK>
    <SHORTTITLE>Third Chancery Court District; revise number of chancellors.</SHORTTITLE>
    <AUTHOR>Horan</AUTHOR>
    <ACTION>03/17 Approved by Governor</ACTION>
    <ACTIONLINK>../history/HB/HB0001.xml</ACTIONLINK>
  </MSRGROUP>
</LASTACTION>
"""

HISTORY_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<HISTORY>
  <YEAR>2026</YEAR>
  <SHORTTITLE>Third Chancery Court District; revise number of chancellors.</SHORTTITLE>
  <LONGTITLE>AN ACT TO AMEND SECTION 9-5-13, MISSISSIPPI CODE OF 1972.</LONGTITLE>
  <MEASURE><SHORT_MSRID>HB 1</SHORT_MSRID></MEASURE>
  <AUTHORS><PRINCIPAL><P_NAME>Horan</P_NAME></PRINCIPAL></AUTHORS>
  <CODESECTIONS><SECTION>009-0005-0013</SECTION></CODESECTIONS>
  <ACTION><ACT_DESC>01/06 (H) Referred To Judiciary B</ACT_DESC></ACTION>
  <ACTION><ACT_DESC>01/08 (H) Passed As Amended</ACT_DESC></ACTION>
  <ACTION><ACT_DESC>03/17 Approved by Governor</ACT_DESC></ACTION>
  <DOCUMENTS>
    <CURRENT><CURRENT_PDF>../../../../documents/2026/pdf/HB/0001-0099/HB0001SG.pdf</CURRENT_PDF></CURRENT>
    <INTRO><INTRO_OTHER>../../../../documents/2026/html/HB/0001-0099/HB0001IN.htm</INTRO_OTHER></INTRO>
  </DOCUMENTS>
</HISTORY>
"""


def test_session_and_listing_parsing() -> None:
    session = session_for_year(2026)
    items = parse_listing(LIST_XML)

    assert session.name == "2026 Mississippi Regular Session"
    assert items[0].number == "HB 1"
    assert items[0].history_url == "https://billstatus.ls.state.ms.us/2026/pdf/history/HB/HB0001.xml"


def test_history_actions_subjects_and_versions() -> None:
    root = ET.fromstring(HISTORY_XML)
    actions = parse_actions(root)
    versions = parse_versions(root)
    subjects = parse_subjects(root)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENACTED,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert [version.format for version in versions] == ["pdf", "html"]
    assert subjects == ["009-0005-0013"]


def test_parse_bill_core_fields() -> None:
    item = parse_listing(LIST_XML)[0]
    bill = parse_bill(item, HISTORY_XML, session=session_for_year(2026))

    assert bill.jurisdiction == "us-ms"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Horan"
    assert "SECTION 9-5-13" in (bill.summary or "")


def test_mississippi_kind_and_citations() -> None:
    assert classify("Budget; direct disbursements from certain special funds") == BillKind.APPROPRIATIONS
    assert classify("Commending a championship team") == BillKind.CEREMONIAL
    assert extract("Amend Section 9-5-13, Mississippi Code of 1972.") == [
        ("Section 9-5-13", "Section 9-5-13"),
        ("Mississippi Code of 1972", "Mississippi Code of 1972"),
    ]
