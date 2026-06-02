from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_az.bill.citations import extract
from axiom_bills.jurisdictions.us_az.bill.scrape import (
    parse_actions,
    parse_sponsors,
    parse_versions,
    session_from_row,
)


SESSION_ROW = {
    "SessionId": 130,
    "Code": "2R",
    "Name": "2026 - Fifty-seventh Legislature - Second Regular Session",
    "Legislature": "57",
}

BILL_ROW = {
    "BillId": 83698,
    "SessionId": 130,
    "Number": "SB1071",
    "ShortTitle": "Arizona rangers; repeal",
    "Description": "SB1071 - Arizona rangers; repeal",
    "DateIntroduced": "11/17/2025",
    "PreFileDate": "2025-11-17T00:00:00",
}

OVERVIEW_ROWS = [
    {
        "SortedDate": "2026-01-12T11:27:10.267",
        "DateType": "FIRST",
        "Body": "S",
    },
    {
        "SortedDate": "2026-01-12T11:27:11.043",
        "DateType": "_STANDING",
        "Body": "S",
        "col4": "DP",
        "col5": "4-3-0-0",
        "col6": "Public Safety",
        "col7": "do pass",
    },
    {
        "SortedDate": "2026-03-23T13:06:30",
        "DateType": "THIRD",
        "Body": "S",
        "Action": "PASSED",
        "col1": "17",
        "col2": "11",
        "col3": "2",
        "col4": "0",
    },
    {
        "SortedDate": "2026-03-23T13:22:00",
        "DateType": "TRANSMIT",
        "Body": "H",
    },
]

SPONSOR_ROWS = [
    {
        "SponsorType": "Prime",
        "Legislator": {
            "FullName": "Mark Finchem",
            "Party": "R",
        },
    },
    {
        "SponsorType": "Co-Sponsor",
        "Legislator": {
            "FullName": "Wendy Rogers",
            "Party": "R",
        },
    },
]

DOC_GROUPS = [
    {
        "DocumentGroupCode": "BillDocuments",
        "DocumentGroupName": "Bill Versions",
        "Documents": [
            {
                "DocumentName": "Introduced Version",
                "PdfPath": "/BillStatus/GetDocumentPdf/533593",
                "HtmlPath": "https://www.azleg.gov/legtext/57leg/2R/bills/SB1071P.htm",
            },
            {
                "DocumentName": "Senate Engrossed Version",
                "PdfPath": "/BillStatus/GetDocumentPdf/540278",
                "HtmlPath": "https://www.azleg.gov/legtext/57leg/2R/bills/SB1071S.htm",
            },
        ],
    }
]


def test_session_from_row() -> None:
    session = session_from_row(SESSION_ROW)

    assert session.name == "2026 - Fifty-seventh Legislature - Second Regular Session"
    assert session.start_date.isoformat() == "2026-01-01"
    assert session.end_date.isoformat() == "2026-12-31"


def test_parse_actions_from_overview_rows_and_bill_row() -> None:
    actions = parse_actions(OVERVIEW_ROWS, row=BILL_ROW)

    assert [action.normalized_status for action in actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.PASSED_CHAMBER,
    ]
    assert actions[-1].action_text == "Transmitted to House"
    assert actions[-1].chamber == Chamber.LOWER


def test_parse_sponsors_and_versions() -> None:
    sponsors = parse_sponsors(SPONSOR_ROWS)
    versions = parse_versions(DOC_GROUPS)

    assert sponsors[0].name == "Mark Finchem"
    assert sponsors[0].role == "primary"
    assert sponsors[1].role == "cosponsor"
    assert [version.label for version in versions] == ["introduced", "engrossed"]
    assert versions[0].format == "html"
    assert versions[0].source_url.endswith("SB1071P.htm")


def test_arizona_kind_and_citations() -> None:
    from axiom_bills.jurisdictions.us_az.bill.kind import classify

    assert classify("general appropriations act") == BillKind.APPROPRIATIONS
    assert extract("Amend A.R.S. § 32-2606 and Arizona Revised Statutes section 41-121.") == [
        ("A.R.S. § 32-2606", "A.R.S. § 32-2606"),
        ("Arizona Revised Statutes section 41-121", "Arizona Revised Statutes section 41-121"),
    ]
