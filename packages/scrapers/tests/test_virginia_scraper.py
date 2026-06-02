from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_va.bill.citations import extract
from axiom_bills.jurisdictions.us_va.bill.kind import classify
from axiom_bills.jurisdictions.us_va.bill.scrape import (
    parse_actions,
    parse_bill,
    parse_versions,
    session_from_api,
)


SESSION = {
    "SessionID": 59,
    "SessionCode": "20261",
    "DisplayName": "Regular Session",
    "SessionYear": 2026,
    "IsDefault": True,
    "SessionEvents": [
        {"DisplayName": "Session Start", "ActualDate": "2026-01-14T00:00:00"},
        {"DisplayName": "Reconvene", "ActualDate": "2026-04-22T15:12:47"},
    ],
}

RAW_BILL = {
    "LegislationID": 98525,
    "SessionCode": "20261",
    "LegislationNumber": "HB1",
    "Description": "Minimum wage; increases incrementally to $15.00 per hour by January 1, 2028.",
    "LegislationSummary": "<p><b>Minimum wage.</b> Increases the minimum wage.</p>",
    "LegislationTitle": "An Act to amend and reenact § 40.1-28.10 of the Code of Virginia.",
    "LegislationClass": "Legislation",
    "ChamberCode": "H",
    "Patrons": [
        {"MemberDisplayName": "Jeion A. Ward", "Name": "Chief Patron", "Sequence": 1},
        {"MemberDisplayName": "A. N. Other", "Name": "Co-Patron", "Sequence": 2},
    ],
}

EVENTS = [
    {
        "EventDate": "2025-11-17T07:28:00",
        "Description": "Prefiled and ordered printed",
        "Status": "Introduced",
        "ChamberCode": "H",
        "LegislationNumber": "HB1",
        "SessionCode": "20261",
    },
    {
        "EventDate": "2026-03-11T04:00:00",
        "Description": "Passed House",
        "Status": "Passed",
        "ChamberCode": "H",
        "LegislationNumber": "HB1",
        "SessionCode": "20261",
    },
]

VERSIONS = [
    {
        "Description": "Introduced",
        "PdfFile": [{"FileURL": "https://lis.blob.core.windows.net/files/1081188.PDF"}],
        "HtmlFile": [{"FileURL": "https://lis.blob.core.windows.net/files/1081189.HTML"}],
    }
]


def test_virginia_session_and_bill_parsing() -> None:
    session = session_from_api(SESSION)
    bill = parse_bill(RAW_BILL, events=EVENTS, versions=VERSIONS, session=session)

    assert session.name == "2026 Virginia Regular Session"
    assert bill.number == "HB 1"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Jeion A. Ward"
    assert bill.summary == "Minimum wage. Increases the minimum wage."
    assert bill.actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert len(bill.versions) == 2


def test_virginia_actions_versions_kind_and_citations() -> None:
    assert parse_actions(EVENTS)[0].normalized_status == NormalizedStatus.INTRODUCED
    assert parse_versions(VERSIONS)[1].format == "html"
    assert classify("A bill making appropriations for state government") == BillKind.APPROPRIATIONS
    assert classify("A resolution commending a champion") == BillKind.CEREMONIAL
    assert extract("An Act to amend and reenact § 40.1-28.10 of the Code of Virginia.") == [
        ("§ 40.1-28.10", "§ 40.1-28.10"),
        ("Code of Virginia", "Code of Virginia"),
    ]
