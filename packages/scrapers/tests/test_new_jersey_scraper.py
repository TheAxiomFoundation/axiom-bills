from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nj.bill.citations import extract
from axiom_bills.jurisdictions.us_nj.bill.kind import classify
from axiom_bills.jurisdictions.us_nj.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_sponsors,
    parse_versions,
    session_for_year,
)


RAW_BILL = {
    "BillType": "A  ",
    "BillNumber": 101,
    "Bill": "A101   ",
    "Synopsis": "Requires NJT to equip trains with defibrillators.",
}

DESCRIPTION = [{
    "Synopsis": "Requires NJT to equip trains with defibrillators.",
    "ActualBillNumber": "A101",
    "Code_Description": "Transportation and Independent Authorities",
    "FiscalNote": "This bill has been certified by OLS for a fiscal note.",
    "CurrentStatus": "ATR",
}]

HISTORY = [
    {
        "ActionDate": "1/13/2026",
        "HistoryAction": "Introduced, Referred to Assembly Transportation and Independent Authorities Committee",
    },
    {
        "ActionDate": "2/2/2026",
        "HistoryAction": "Reported out of Assembly Committee, 2nd Reading",
    },
]

SPONSORS = [
    [
        {
            "Full_Name": "Barlas, Al",
            "SponsorDescription": " as Primary Sponsor",
            "BioLink": "/legislative-roster/494/assemblyman-barlas",
        }
    ],
    [
        {
            "Full_Name": "Dunn, Aura K.",
            "SponsorDescription": " as Co-Sponsor",
            "BioLink": "/legislative-roster/428/assemblywoman-dunn",
        }
    ],
]

TEXTS = [{
    "Description": "Introduced",
    "DocumentComment": "",
    "Number_Of_Pages": 3,
    "HTML_Link": "/Bills/2026/A0500/101_I1.HTM",
    "PDFLink": "/Bills/2026/A0500/101_I1.PDF",
}]


def test_new_jersey_session_and_bill_parsing() -> None:
    session = session_for_year(2026)
    bill = parse_bill(
        RAW_BILL,
        description=DESCRIPTION,
        history=HISTORY,
        sponsors=SPONSORS,
        texts=TEXTS,
        session=session,
        session_year=2026,
    )

    assert session.name == "2026-2027 New Jersey Legislature"
    assert bill.jurisdiction == "us-nj"
    assert bill.number == "A101"
    assert bill.chamber == Chamber.LOWER
    assert bill.subjects == ["Transportation and Independent Authorities"]
    assert bill.source_url == "https://www.njleg.state.nj.us/bill-search/2026/A101"


def test_actions_sponsors_and_versions() -> None:
    actions = parse_actions(HISTORY)
    sponsors = parse_sponsors(SPONSORS)
    versions = parse_versions(TEXTS)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.IN_COMMITTEE,
    ]
    assert actions[0].chamber == Chamber.LOWER
    assert sponsors[0].name == "Barlas, Al"
    assert sponsors[0].role == "primary"
    assert sponsors[1].role == "cosponsor"
    assert [version.format for version in versions] == ["pdf", "html"]
    assert versions[0].source_url == "https://pub.njleg.gov/Bills/2026/A0500/101_I1.PDF"


def test_new_jersey_kind_and_citations() -> None:
    assert classify("Makes FY2027 budget appropriations") == BillKind.APPROPRIATIONS
    assert classify("Designates New Jersey Defibrillator Awareness Day") == BillKind.CEREMONIAL
    assert extract("Amends N.J.S.A. 2C:35-5 and P.L.1995, c.123.") == [
        ("N.J.S.A. 2C:35-5", "N.J.S.A. 2C:35-5"),
        ("P.L.1995, c.123", "P.L.1995, c.123"),
    ]
