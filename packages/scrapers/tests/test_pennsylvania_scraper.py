from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_pa.bill.citations import extract
from axiom_bills.jurisdictions.us_pa.bill.kind import classify
from axiom_bills.jurisdictions.us_pa.bill.scrape import (
    bill_elements,
    parse_actions,
    parse_bill,
    parse_versions,
    session_from_xml,
)


XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<historyExport exportDate="June 1, 2026 7:30:06 PM EDT" totalDocuments="1">
  <session year="2025" session="0">
    <bill id="20250HB0017" lastUpdate="May 13, 2026 12:05:00 PM EDT">
      <sessionYear>2025</sessionYear>
      <session>0</session>
      <body>H</body>
      <type description="House Bill">B</type>
      <subType>B</subType>
      <number>0017</number>
      <shortTitle>An Act amending Title 35 (Health and Safety) of the Pennsylvania Consolidated Statutes.</shortTitle>
      <sponsors>
        <sponsor sequenceNumber="01" fillSequence="0" party="R" body="H" districtNumber="116">WATRO</sponsor>
        <sponsor sequenceNumber="02" fillSequence="0" party="D" body="H" districtNumber="136">FREEMAN</sponsor>
      </sponsors>
      <printersNumberHistory>
        <number sequence="01" billTextPdfUrl="https://www.palegis.us/legislation/bills/text/PDF/2025/0/HB0017/PN0002">0002</number>
      </printersNumberHistory>
      <actionHistory>
        <action sequence="01" actionChamber="H">
          <date>01/08/25</date>
          <fullAction>Referred to EDUCATION, Jan. 8, 2025</fullAction>
        </action>
        <action sequence="02" actionChamber="H">
          <date>06/24/25</date>
          <fullAction>Third consideration and final passage, June 24, 2025 (195-8)</fullAction>
        </action>
        <action sequence="03" actionChamber="E">
          <date>02/11/26</date>
          <fullAction>Act No. 2 of 2026, Feb. 11, 2026</fullAction>
        </action>
      </actionHistory>
      <amendments/>
    </bill>
  </session>
</historyExport>
"""


def test_session_and_bill_parsing() -> None:
    session = session_from_xml(XML)
    elem = bill_elements(XML)[0]
    bill = parse_bill(elem, session=session)

    assert session.name == "2025-2026 Pennsylvania Regular Session"
    assert bill.jurisdiction == "us-pa"
    assert bill.number == "HB 17"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "WATRO"
    assert bill.sponsors[1].role == "cosponsor"
    assert bill.source_url == "https://www.palegis.us/legislation/bills/2025/hb17"


def test_actions_and_versions() -> None:
    elem = bill_elements(XML)[0]
    actions = parse_actions(elem)
    versions = parse_versions(elem)

    assert actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert actions[1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert actions[2].normalized_status == NormalizedStatus.ENACTED
    assert actions[2].chamber == Chamber.EXECUTIVE
    assert versions[0].label == "PN 0002"
    assert versions[0].format == "pdf"


def test_pennsylvania_kind_and_citations() -> None:
    assert classify("An Act making an appropriation from the General Fund") == BillKind.APPROPRIATIONS
    assert classify("A Resolution honoring emergency responders") == BillKind.CEREMONIAL
    assert extract(
        "Amends Title 35 (Health and Safety) of the Pennsylvania Consolidated Statutes and the act of March 10, 1949 (P.L.30, No.14)."
    ) == [
        (
            "Title 35 (Health and Safety) of the Pennsylvania Consolidated Statutes",
            "Title 35 (Health and Safety) of the Pennsylvania Consolidated Statutes",
        ),
        ("act of March 10, 1949 (P.L.30, No.14)", "act of March 10, 1949 (P.L.30, No.14)"),
        ("P.L.30, No.14", "P.L.30, No.14"),
    ]
