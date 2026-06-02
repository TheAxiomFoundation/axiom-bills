"""Montana bill scraper.

Montana's public Bill Explorer is a React app backed by the official
bearbeta.legmt.gov API. This scraper uses the same session, bill search,
legislator, and document endpoints exposed by that app.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillVersion,
    Chamber,
    ScrapeResult,
    Session,
    Sponsor,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

API_ROOT = "https://bearbeta.legmt.gov"
APP_ROOT = "https://bills.legmt.gov"
PAGE_SIZE = 100
ALLOWED_TYPES = {"HB", "HR", "HJ", "SB", "SR", "SJ"}


class MontanaScraper(BillScraper):
    jurisdiction = "us-mt"
    source_name = "bearbeta.legmt.gov official Montana Bill Explorer API"
    min_interval_per_host = 0.15

    def scrape(self) -> ScrapeResult:
        session_data = self._active_session_data()
        session = session_from_api(session_data)
        legislature_ordinal = _legislature_ordinal(session_data)
        session_ordinal = str(session_data.get("ordinals") or "")
        sponsor_cache: dict[int, Sponsor | None] = {}

        bills: list[Bill] = []
        for raw_bill in self._bill_pages(int(session_data["id"])):
            if self.limit is not None and len(bills) >= self.limit:
                break
            bill_type = _bill_type_code(raw_bill)
            if bill_type not in ALLOWED_TYPES:
                continue
            bills.append(parse_bill(
                raw_bill,
                session=session,
                session_ordinal=session_ordinal,
                sponsor=self._sponsor_for(raw_bill.get("sponsorId"), sponsor_cache),
                versions=self._versions_for(raw_bill, legislature_ordinal, session_ordinal),
            ))

        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _active_session_data(self) -> dict[str, Any]:
        active = self.http.get(f"{API_ROOT}/bills/v1/activeSessions/getActiveSession").json()
        session_id = active["sessionId"]
        return self.http.get(f"{API_ROOT}/legislators/v1/sessions/{session_id}").json()

    def _bill_pages(self, session_id: int) -> list[dict[str, Any]]:
        bills: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_limit = PAGE_SIZE if self.limit is None else min(PAGE_SIZE, max(self.limit - len(bills), 1))
            url = (
                f"{API_ROOT}/bills/v1/bills/search?includeCounts=false"
                "&sort=billType.sortOrder,desc&sort=billNumber,asc"
                f"&sort=draft.draftNumber,asc&limit={page_limit}&offset={offset}"
            )
            response = self.http.post(url, json={"sessionIds": [session_id]}).json()
            content = response.get("content") or []
            bills.extend(content)
            if not content or (self.limit is not None and len(bills) >= self.limit):
                break
            offset += len(content)
        return bills

    def _sponsor_for(self, sponsor_id: object, cache: dict[int, Sponsor | None]) -> Sponsor | None:
        if not isinstance(sponsor_id, int):
            return None
        if sponsor_id in cache:
            return cache[sponsor_id]
        data = self.http.get(f"{API_ROOT}/legislators/v1/legislators/{sponsor_id}").json()
        cache[sponsor_id] = sponsor_from_api(data)
        return cache[sponsor_id]

    def _versions_for(
        self,
        raw_bill: dict[str, Any],
        legislature_ordinal: str,
        session_ordinal: str,
    ) -> list[BillVersion]:
        bill_type = _bill_type_code(raw_bill)
        bill_number = raw_bill.get("billNumber")
        if not legislature_ordinal or not session_ordinal or not bill_type or bill_number is None:
            return []
        url = (
            f"{API_ROOT}/docs/v1/documents/getBillVersions?"
            f"legislatureOrdinal={legislature_ordinal}&sessionOrdinal={session_ordinal}"
            f"&billType={bill_type}&billNumber={bill_number}"
        )
        return parse_versions(self.http.get(url).json())


def session_from_api(data: dict[str, Any]) -> Session:
    ordinal = str(data.get("ordinals") or "")
    legislature = data.get("legislature") or {}
    return Session(
        name=f"{ordinal} Montana Regular Session" if ordinal else "Montana Regular Session",
        start_date=_parse_date(data.get("startDate")),
        end_date=_parse_date(data.get("sineDieDate") or legislature.get("endDate")),
        is_current=bool(data.get("active")),
    )


def parse_bill(
    raw_bill: dict[str, Any],
    *,
    session: Session,
    session_ordinal: str,
    sponsor: Sponsor | None = None,
    versions: list[BillVersion] | None = None,
) -> Bill:
    draft = raw_bill.get("draft") or {}
    number = _format_number(raw_bill)
    title = _clean_text(draft.get("shortTitle")) or _clean_text(draft.get("description")) or number
    summary = _clean_text(draft.get("description")) or title
    return Bill(
        jurisdiction=MontanaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_bill(raw_bill),
        number=number,
        title=title,
        summary=summary,
        subjects=parse_subjects(draft),
        sponsors=[sponsor] if sponsor else [],
        source_url=_source_url(session_ordinal, number),
        actions=parse_actions(draft.get("billStatuses") or []),
        versions=versions or [],
        kind=classify_kind(" ".join(part for part in (title, summary) if part)),
    )


def parse_actions(statuses: list[dict[str, Any]]) -> list[BillAction]:
    actions: list[BillAction] = []
    for status in statuses:
        occurred_at = _parse_datetime(status.get("timeStamp"))
        if occurred_at is None:
            continue
        status_code = status.get("billStatusCode") or {}
        name = _clean_text(status_code.get("name"))
        category = _clean_text((status.get("billProgressCategory") or {}).get("description"))
        if not name:
            continue
        text_for_match = " ".join(part for part in (name, category) if part)
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_text(status_code.get("chamber")),
            action_text=name,
            normalized_status=match_first(text_for_match, PATTERNS),
            source_url=None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_subjects(draft: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    seen: set[str] = set()
    for subject in draft.get("subjects") or []:
        subject_code = subject.get("subjectCode") or {}
        value = _clean_text(subject_code.get("description"))
        if value and value not in seen:
            seen.add(value)
            subjects.append(value)
    return subjects


def sponsor_from_api(data: dict[str, Any]) -> Sponsor | None:
    first = _clean_text(data.get("firstName"))
    last = _clean_text(data.get("lastName"))
    name = " ".join(part for part in (first, last) if part)
    if not name:
        return None
    party = (data.get("politicalParty") or {}).get("code")
    district = (data.get("district") or {}).get("name")
    return Sponsor(name=name, role="primary", party=party, district=district)


def parse_versions(documents: list[dict[str, Any]]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for document in documents:
        source_url = _document_url(document)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        filename = _clean_text(document.get("fileName"))
        versions.append(BillVersion(
            label=filename or f"Document {document.get('id')}",
            source_url=source_url,
            format=_format_for_filename(filename),
        ))
    versions.sort(key=lambda version: version.label)
    return versions


def _bill_type_code(raw_bill: dict[str, Any]) -> str:
    return _clean_text((raw_bill.get("billType") or {}).get("code")).upper()


def _chamber_for_bill(raw_bill: dict[str, Any]) -> Chamber:
    return _chamber_from_text((raw_bill.get("billType") or {}).get("chamber")) or Chamber.JOINT


def _chamber_from_text(value: object) -> Chamber | None:
    text = _clean_text(value).upper()
    if text in {"HOUSE", "H"}:
        return Chamber.LOWER
    if text in {"SENATE", "S"}:
        return Chamber.UPPER
    return None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _document_url(document: dict[str, Any]) -> str | None:
    for attribute in document.get("attributes") or []:
        if attribute.get("name") == "DocumentLink" and attribute.get("stringValue"):
            return str(attribute["stringValue"])
    document_id = document.get("id")
    return f"{API_ROOT}/docs/v1/documents/getContent?documentId={document_id}" if document_id else None


def _format_for_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith((".html", ".htm")):
        return "html"
    return "txt"


def _format_number(raw_bill: dict[str, Any]) -> str:
    bill_type = _bill_type_code(raw_bill)
    number = raw_bill.get("billNumber")
    return f"{bill_type} {number}" if bill_type and number is not None else str(number or "")


def _legislature_ordinal(session_data: dict[str, Any]) -> str:
    return str((session_data.get("legislature") or {}).get("ordinals") or "")


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "HR": 1, "HJ": 2, "SB": 3, "SR": 4, "SJ": 5}.get(prefix, 9)
    digits = "".join(char for char in number if char.isdigit())
    return (order, int(digits) if digits else 0, number)


def _parse_date(value: object) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else None


def _parse_datetime(value: object) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _source_url(session_ordinal: str, number: str) -> str:
    compact_number = number.replace(" ", "")
    return f"{APP_ROOT}/#/bill/{session_ordinal}/{compact_number}"
