from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_al.bill.citations import extract
from axiom_bills.jurisdictions.us_al.bill.scrape import parse_bill, session_from_row


SESSION_ROW = {
    "name": "2026 Regular Session",
    "abbreviation": "2026RS",
    "startDate": "2026-01-13T06:00:00.000Z",
    "endDate": "2026-04-10T00:30:00.000Z",
}

SUMMARY_ROW = {
    "sessionAbbreviation": "2026RS",
    "sessionYear": 2026,
    "sessionName": "2026 Regular Session",
    "instrumentNbr": "HB2",
    "instrumentType": "B",
    "sponsor": "Standridge",
    "body": "House",
    "subject": "State Government",
    "shortTitle": "Gulf of Mexico, renamed, observation and implementation by state and local entities required",
    "assignedCommittee": "State Government",
    "firstReadDate": "2026-01-13",
    "currentStatus": "Enacted",
    "lastAction": "Enacted",
    "lastActionDate": "2026-04-07",
    "actSummary": "This act is the Gulf of America Act.",
    "actNbr": "2026-364",
}

DETAIL_DATA = {
    "instrument": {
        "id": "22163531",
        "instrumentNbr": "HB2",
        "sessionName": "2026 Regular Session",
        "currentStatus": "Enacted",
        "shortTitle": "Gulf of Mexico, renamed, observation and implementation by state and local entities required",
        "introducedFileUrl": "https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB2-int.pdf",
        "engrossedFileUrl": "https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB2-eng.pdf",
        "enrolledFileUrl": "https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB2-enr.pdf",
        "reenrolledFileUrl": None,
        "viewEnacted": "https://arc-sos.state.al.us/cgi/actdetail.mbr/detail?page=act&year=2026&act=364",
        "actNbr": "2026-364",
    },
    "histories": {
        "data": [
            {
                "instrumentNbr": "HB2",
                "sessionName": "2026 Regular Session",
                "sessionYear": 2026,
                "calendarDate": "2026-04-07",
                "body": "House",
                "matter": "Enacted",
                "committee": None,
                "amdSub": None,
                "amdSubFileUrl": None,
                "rollCallNbr": None,
                "yeas": None,
                "nays": None,
            },
            {
                "instrumentNbr": "HB2",
                "sessionName": "2026 Regular Session",
                "sessionYear": 2026,
                "calendarDate": "2026-01-13",
                "body": "House",
                "matter": "Read for the first time and referred to the House Committee on State Government",
                "committee": None,
                "amdSub": None,
                "amdSubFileUrl": None,
                "rollCallNbr": None,
                "yeas": None,
                "nays": None,
            },
            {
                "instrumentNbr": "HB2",
                "sessionName": "2026 Regular Session",
                "sessionYear": 2026,
                "calendarDate": "2026-02-24",
                "body": "House",
                "matter": "Motion to Read a Third Time and Pass as Amended - Adopted Roll Call 536",
                "committee": None,
                "amdSub": None,
                "amdSubFileUrl": None,
                "rollCallNbr": 536,
                "yeas": 74,
                "nays": 30,
            },
        ]
    },
}


def test_session_from_row() -> None:
    session = session_from_row(SESSION_ROW)

    assert session.name == "2026 Regular Session"
    assert session.start_date.isoformat() == "2026-01-13"
    assert session.end_date.isoformat() == "2026-04-10"


def test_parse_bill_builds_core_fields_actions_and_versions() -> None:
    bill = parse_bill(SUMMARY_ROW, DETAIL_DATA, session=session_from_row(SESSION_ROW))

    assert bill is not None
    assert bill.jurisdiction == "us-al"
    assert bill.number == "HB2"
    assert bill.chamber == Chamber.LOWER
    assert bill.sponsors[0].name == "Standridge"
    assert bill.subjects == ["State Government"]
    assert bill.kind == BillKind.SUBSTANTIVE
    assert bill.actions[0].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.actions[1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert bill.versions[0].label == "introduced"
    assert bill.versions[-1].label == "enacted"


def test_extracts_alabama_citations() -> None:
    assert extract("Amend Ala. Code 1975 § 32-5A-191 and Section 41-9-297.") == [
        ("Ala. Code 1975 § 32-5A-191", "Ala. Code 1975 § 32-5A-191"),
        ("Section 41-9-297", "Section 41-9-297"),
    ]
