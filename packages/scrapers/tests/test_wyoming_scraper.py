from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_wy.bill.scrape import (
    parse_bill,
    session_for_year,
)
from axiom_bills.jurisdictions.us_wy.bill.citations import extract


BILL_ROW = {
    "year": 2026,
    "billNum": "HB0002",
    "shortTitle": "Fast Track Permits Act. ",
    "chapterNo": "0042",
    "signedDate": "2026-03-05T00:00:00Z",
    "effectiveDate": "2026-07-01T00:00:00Z",
    "sponsor": "Filer",
    "enrolledNo": "16",
    "lastActionDate": "2026-03-05T00:00:00Z",
    "lastAction": "Assigned Chapter Number 42",
    "billType": "HB",
    "specialSessionValue": None,
    "billStatus": "enrolled",
}

DETAIL = {
    "bill": "HB0002",
    "catchTitle": "Fast Track Permits Act.",
    "sponsor": "Representative Filer",
    "billTitle": "AN ACT relating to city, county, state and local powers.",
    "introduced": "2026/Introduced/HB0002.pdf",
    "digest": "2026/Digest/HB0002.pdf",
    "engrossedVersion": "2026/Engross/HB0002.pdf",
    "enrolledAct": "2026/Enroll/HB0002.pdf",
    "summary": "2026/Summaries/HB0002.pdf",
    "billType": "HB",
    "signedDate": "3/5/2026",
    "effectiveDate": "7/1/2026",
    "enrolledNumber": "HEA0016",
    "billStatus": "enrolled",
    "sponsors": [
        {
            "name": "Filer",
            "primarySponsor": True,
            "house": "H",
            "sponsorTitle": "Representative",
        },
        {
            "name": "Love",
            "primarySponsor": False,
            "house": "S",
            "sponsorTitle": "Senator",
        },
    ],
    "billActions": [
        {
            "statusDate": "2026-03-05T20:08:04Z",
            "statusMessage": "Assigned Chapter Number 42",
            "voteId": "",
            "location": "LSO",
        },
        {
            "statusDate": "2026-03-05T20:07:43Z",
            "statusMessage": "Governor Signed HEA No. 0016",
            "voteId": "",
            "location": "Governor",
        },
        {
            "statusDate": "2026-03-02T18:53:01Z",
            "statusMessage": "S President Signed HEA No. 0016",
            "voteId": "",
            "location": "Senate",
        },
        {
            "statusDate": "2026-03-02T15:29:34Z",
            "statusMessage": "S 3rd Reading:Passed 31-0-0-0-0",
            "voteId": "452",
            "location": "Senate",
        },
        {
            "statusDate": "2026-02-10T14:45:40Z",
            "statusMessage": "H Introduced and Referred to H09 - Minerals 59-2-1-0-0",
            "voteId": "5077",
            "location": "House",
        },
        {
            "statusDate": "2025-12-01T09:55:06Z",
            "statusMessage": "Bill Number Assigned",
            "voteId": "",
            "location": "LSO",
        },
    ],
    "substituteBills": [],
    "vetoes": [],
    "amendments": [],
}


def test_session_for_year() -> None:
    session = session_for_year(2026)

    assert session.name == "2026 Wyoming Budget Session"
    assert session.start_date is not None
    assert session.start_date.isoformat() == "2026-01-01"


def test_parse_bill_extracts_core_fields() -> None:
    bill = parse_bill(BILL_ROW, DETAIL, session=session_for_year(2026))

    assert bill is not None
    assert bill.jurisdiction == "us-wy"
    assert bill.chamber == Chamber.LOWER
    assert bill.number == "HB0002"
    assert bill.title == "Fast Track Permits Act."
    assert bill.summary == "AN ACT relating to city, county, state and local powers."
    assert bill.source_url == "https://wyoleg.gov/Legislation/2026/HB0002"
    assert bill.kind == BillKind.SUBSTANTIVE


def test_parse_bill_extracts_sponsors_and_versions() -> None:
    bill = parse_bill(BILL_ROW, DETAIL, session=session_for_year(2026))

    assert bill is not None
    assert bill.sponsors[0].name == "Filer"
    assert bill.sponsors[0].role == "primary Representative"
    assert bill.sponsors[1].name == "Love"
    assert bill.versions[0].label == "introduced"
    assert bill.versions[0].source_url == "https://wyoleg.gov/2026/Introduced/HB0002.pdf"
    assert bill.versions[-1].label == "digest"


def test_parse_bill_builds_actions() -> None:
    bill = parse_bill(BILL_ROW, DETAIL, session=session_for_year(2026))

    assert bill is not None
    assert bill.actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert bill.actions[1].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert bill.actions[2].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert bill.actions[2].chamber == Chamber.UPPER
    assert bill.actions[-3].normalized_status == NormalizedStatus.ENROLLED
    assert bill.actions[-2].normalized_status == NormalizedStatus.SIGNED
    assert bill.actions[-1].normalized_status == NormalizedStatus.ENACTED
    assert bill.actions[-1].occurred_at.isoformat() == "2026-03-05T20:08:04+00:00"


def test_extracts_wyoming_citations() -> None:
    citations = extract("Amending W.S. 35-11-302(a) and Wyoming Statutes Section 9-2-101.")

    assert citations == [
        ("W.S. 35-11-302(a)", "WY Stat. § 35-11-302(a)"),
        ("Wyoming Statutes Section 9-2-101", "WY Stat. § 9-2-101"),
    ]
