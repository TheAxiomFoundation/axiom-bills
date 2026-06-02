from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_wa.bill.citations import extract
from axiom_bills.jurisdictions.us_wa.bill.kind import classify
from axiom_bills.jurisdictions.us_wa.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_legislation,
    parse_legislation_info,
    parse_sponsors,
    parse_versions,
    session_from_biennium,
)


INFO_XML = """<?xml version="1.0" encoding="utf-8"?>
<ArrayOfLegislationInfo xmlns="http://WSLWebServices.leg.wa.gov/">
  <LegislationInfo>
    <Biennium>2025-26</Biennium>
    <BillId>HB 2196</BillId>
    <BillNumber>2196</BillNumber>
    <OriginalAgency>House</OriginalAgency>
    <Active>true</Active>
  </LegislationInfo>
</ArrayOfLegislationInfo>
"""

LEGISLATION_XML = """<?xml version="1.0" encoding="utf-8"?>
<ArrayOfLegislation xmlns="http://WSLWebServices.leg.wa.gov/">
  <Legislation>
    <Biennium>2025-26</Biennium>
    <BillId>ESHB 2196</BillId>
    <BillNumber>2196</BillNumber>
    <OriginalAgency>House</OriginalAgency>
    <Active>true</Active>
    <Appropriations>false</Appropriations>
    <ShortDescription>PANDAS, pediatric treatment</ShortDescription>
    <LongDescription>Expanding access to PANDA PANS treatment.</LongDescription>
    <LegalTitle>AN ACT Relating to expanding access to treatment of pediatric autoimmune neuropsychiatric disorders;</LegalTitle>
  </Legislation>
</ArrayOfLegislation>
"""

SPONSORS_XML = """<?xml version="1.0" encoding="utf-8"?>
<ArrayOfSponsor xmlns="http://WSLWebServices.leg.wa.gov/">
  <Sponsor>
    <FirstName>Tarra</FirstName>
    <LastName>Simmons</LastName>
    <Type>Primary</Type>
  </Sponsor>
  <Sponsor>
    <FirstName>Sam</FirstName>
    <LastName>Low</LastName>
    <Type>Secondary</Type>
  </Sponsor>
</ArrayOfSponsor>
"""

ACTIONS_XML = """<?xml version="1.0" encoding="utf-8"?>
<ArrayOfLegislativeStatus xmlns="http://WSLWebServices.leg.wa.gov/">
  <LegislativeStatus>
    <BillId>HB 2196</BillId>
    <HistoryLine>Prefiled for introduction.</HistoryLine>
    <ActionDate>2025-12-24T00:00:00</ActionDate>
    <Status>Hsubst for</Status>
  </LegislativeStatus>
  <LegislativeStatus>
    <BillId>ESHB 2196</BillId>
    <HistoryLine>Third reading, passed; yeas, 83; nays, 13; absent, 0; excused, 2.</HistoryLine>
    <ActionDate>2026-02-16T00:00:00</ActionDate>
    <Status>HRules 3C</Status>
  </LegislativeStatus>
</ArrayOfLegislativeStatus>
"""

DOCUMENTS_XML = """<?xml version="1.0" encoding="utf-8"?>
<ArrayOfLegislativeDocument xmlns="http://WSLWebServices.leg.wa.gov/">
  <LegislativeDocument>
    <ShortFriendlyName>Original Bill</ShortFriendlyName>
    <Class>Bills</Class>
    <HtmUrl>http://lawfilesext.leg.wa.gov/biennium/2025-26/Htm/Bills/House Bills/2196.htm</HtmUrl>
    <PdfUrl>http://lawfilesext.leg.wa.gov/biennium/2025-26/Pdf/Bills/House Bills/2196.pdf</PdfUrl>
    <BillId>HB 2196</BillId>
  </LegislativeDocument>
  <LegislativeDocument>
    <ShortFriendlyName>House Bill Report</ShortFriendlyName>
    <Class>Bill Reports</Class>
    <PdfUrl>http://example.test/report.pdf</PdfUrl>
  </LegislativeDocument>
</ArrayOfLegislativeDocument>
"""


def test_washington_session_and_bill_parsing() -> None:
    session = session_from_biennium("2025-26")
    info = parse_legislation_info(INFO_XML)[0]
    raw = parse_legislation(LEGISLATION_XML)[0]
    sponsors = parse_sponsors(SPONSORS_XML)
    actions = parse_actions(ACTIONS_XML)
    versions = parse_versions(DOCUMENTS_XML)
    bill = parse_bill(raw, sponsors=sponsors, actions=actions, versions=versions, session=session)

    assert info["BillId"] == "HB 2196"
    assert session.name == "2025-2026 Washington Regular Session"
    assert bill.number == "HB 2196"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Tarra Simmons"
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert len(bill.versions) == 2
    assert bill.versions[0].source_url.startswith("https://lawfilesext.leg.wa.gov")


def test_washington_actions_versions_kind_and_citations() -> None:
    assert parse_actions(ACTIONS_XML)[0].normalized_status == NormalizedStatus.INTRODUCED
    assert parse_versions(DOCUMENTS_XML)[1].format == "html"
    assert classify("Making appropriations for the operating budget") == BillKind.APPROPRIATIONS
    assert classify("A resolution recognizing a championship team") == BillKind.CEREMONIAL
    assert extract("This bill amends RCW 43.20A.890 and chapter 70.02 RCW.") == [
        ("RCW 43.20A.890", "RCW 43.20A.890"),
        ("chapter 70.02 RCW", "chapter 70.02 RCW"),
    ]
