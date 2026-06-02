from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_dc.bill.citations import extract
from axiom_bills.jurisdictions.us_dc.bill.scrape import (
    bill_number_for,
    parse_bill,
    session_for_period,
)


DETAIL = {
    "legislationId": 56820,
    "legislationNumber": "B26-0001",
    "title": "Rent Stabilized Housing Inflation Protection Continuation Emergency Amendment Act of 2025",
    "shortDescription": None,
    "legislationTracker": [
        {"statusDescription": "Introduced", "statusCode": 2, "status": "Completed", "displayOrder": 1},
        {"statusDescription": "Final Reading", "statusCode": 2, "status": "Completed", "displayOrder": 3},
        {"statusDescription": "Enacted", "statusCode": 2, "status": "Completed", "displayOrder": 5},
    ],
    "introducerSummary": {
        "legislationNumber": "B26-0001",
        "summaryDataList": [
            {
                "label": "Introduced by",
                "content": 'Councilmember <a href="/introducerDetail/198/26" target="_blank">R. White</a>',
                "url": None,
            },
            {"label": "Act Number", "content": "A26-0003, Expires on May 04, 2025", "url": None},
        ],
    },
    "legislationHistory": [
        {
            "legislationId": 56820,
            "date": "Jan 06, 2025",
            "sortDate": "2025-01-06T00:00:00",
            "type": "Introduction",
            "data": {
                "introducers": [
                    {
                        "id": 198,
                        "name": "White, Robert C. Jr.",
                        "title": "Councilmember",
                        "formalName": "R. White",
                        "introducerTypeId": 1,
                    }
                ],
                "introductionPlace": "Office of the Secretary",
                "documentURL": "/downloads/LIMS/56820/Introduction/B26-0001-Introduction.pdf?Id=203761",
            },
            "actionText": "B26-0001 Introduced by Councilmember R. White at Office of the Secretary",
            "actionURL": "/downloads/LIMS/56820/Introduction/B26-0001-Introduction.pdf?Id=203761",
            "legislationNumber": "B26-0001",
            "sortOrder": 1,
        },
        {
            "legislationId": 56820,
            "date": "Jan 07, 2025",
            "sortDate": "2025-01-07T00:00:00",
            "type": "CommitteeReferral",
            "data": {"referredToCommittee": [{"id": 49, "name": "Retained by the Council"}]},
            "actionText": "Retained by the Council",
            "actionURL": None,
            "legislationNumber": "B26-0001",
            "sortOrder": 2,
        },
        {
            "legislationId": 56820,
            "date": "Jan 07, 2025",
            "sortDate": "2025-01-07T00:00:00",
            "type": "MeetingVoting",
            "data": {
                "meetingDescription": "Legislative Meeting",
                "meetingActions": [
                    {
                        "meetingAction": "Final Reading",
                        "documentType": "Enrollment",
                        "documentUrl": "/downloads/LIMS/56820/Meeting1/Enrollment/B26-0001-Enrollment1.pdf?Id=204336",
                        "voteResult": "Approved",
                        "additionalInformation": "",
                    }
                ],
            },
            "actionText": "Legislative Meeting",
            "actionURL": None,
            "legislationNumber": "B26-0001",
            "sortOrder": 3,
        },
        {
            "legislationId": 56820,
            "date": "Jan 23, 2025",
            "sortDate": "2025-01-23T00:00:00",
            "type": "TransmittedToMayor",
            "data": {"transmittedDate": "2025-01-23T00:00:00", "responseDate": "2025-02-06T00:00:00"},
            "actionText": "Transmitted to Mayor, Response Due on Feb 06, 2025",
            "actionURL": None,
            "legislationNumber": "B26-0001",
            "sortOrder": 4,
        },
        {
            "legislationId": 56820,
            "date": "Feb 03, 2025",
            "sortDate": "2025-02-03T00:00:00",
            "type": "SignedEnacted",
            "data": {"documentURL": "/downloads/LIMS/56820/Signed_Act/B26-0001-Signed_Act.pdf?Id=205769"},
            "actionText": "Signed by the Mayor and Enacted with Act Number A26-0003, Expires on May 04, 2025",
            "actionURL": "/downloads/LIMS/56820/Signed_Act/B26-0001-Signed_Act.pdf?Id=205769",
            "legislationNumber": "B26-0001",
            "sortOrder": 5,
        },
        {
            "legislationId": 56820,
            "date": "Feb 07, 2025",
            "sortDate": "2025-02-07T00:00:00",
            "type": "ActPublished",
            "data": {"actNumber": "A26-0003", "dCRegisterURL": "https://www.dcregs.dc.gov/Common/DCMR/NoticeDetail.aspx?NoticeId=N150834"},
            "actionText": "Act A26-0003 Published in DC Register Vol 72 and Page 001133, Expires on May 04, 2025",
            "actionURL": None,
            "legislationNumber": "B26-0001",
            "sortOrder": 6,
        },
    ],
    "otherDocuments": [
        {
            "legislationDocumentId": 171498,
            "documentTypeId": 2,
            "documentTypeName": "Memorandum",
            "documentTitle": "B26-0001_Memorandum",
            "url": "/downloads/LIMS/56820/Memo/B26-0001_Memorandum.pdf?Id=203762",
        }
    ],
    "relatedLegislation": [],
    "statusId": 15,
    "status": "Act Published",
    "tag": "Law",
    "legislationTextUrl": "/downloads/LIMS/56820/Introduction/B26-0001-Introduction.pdf?Id=203761",
    "additionalInformation": None,
    "lawNumber": None,
    "resolutionNumber": None,
    "actNumber": "A26-0003",
}


def test_period_and_number_helpers() -> None:
    session = session_for_period(26)

    assert bill_number_for(26, 1) == "B26-0001"
    assert session.name == "Council Period 26 (2025-2026)"
    assert session.start_date.isoformat() == "2025-01-01"
    assert session.end_date.isoformat() == "2026-12-31"


def test_parse_bill_core_fields_actions_and_versions() -> None:
    bill = parse_bill(DETAIL, session=session_for_period(26))

    assert bill.jurisdiction == "us-dc"
    assert bill.number == "B26-0001"
    assert bill.chamber == Chamber.JOINT
    assert bill.sponsors[0].name == "White, Robert C. Jr."
    assert bill.source_url == "https://lims.dccouncil.gov/Legislation/B26-0001"
    assert [action.normalized_status for action in bill.actions] == [
        NormalizedStatus.INTRODUCED,
        NormalizedStatus.IN_COMMITTEE,
        NormalizedStatus.PASSED_CHAMBER,
        NormalizedStatus.ENROLLED,
        NormalizedStatus.SIGNED,
        NormalizedStatus.ENACTED,
    ]
    assert bill.actions[4].chamber == Chamber.EXECUTIVE
    assert [version.label for version in bill.versions] == [
        "legislation text",
        "Enrollment",
        "SignedEnacted",
        "DC Register",
        "B26-0001_Memorandum",
    ]


def test_dc_kind_and_citations() -> None:
    from axiom_bills.jurisdictions.us_dc.bill.kind import classify

    assert classify("Fiscal Year 2027 Budget Support Act of 2026") == BillKind.APPROPRIATIONS
    assert extract("Amend D.C. Official Code § 42-3502.08 and D.C. Law 25-50. Act A26-0003 applies.") == [
        ("D.C. Official Code § 42-3502.08", "D.C. Official Code § 42-3502.08"),
        ("D.C. Law 25-50", "D.C. Law 25-50"),
        ("Act A26-0003", "Act A26-0003"),
    ]
