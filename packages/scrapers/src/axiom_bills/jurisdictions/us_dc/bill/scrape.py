"""District of Columbia bill scraper.

The Council publishes official legislation detail JSON through LIMS under
`/api/Search/GetLegislationDetails/{number}`.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

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

ROOT = "https://lims.dccouncil.gov"
DEFAULT_COUNCIL_PERIOD = 26
DEFAULT_START_YEAR = 2025


class DistrictOfColumbiaScraper(BillScraper):
    jurisdiction = "us-dc"
    source_name = "lims.dccouncil.gov official JSON API"
    min_interval_per_host = 0.2

    def __init__(self, *, council_period: int = DEFAULT_COUNCIL_PERIOD, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.council_period = council_period

    def scrape(self) -> ScrapeResult:
        session = session_for_period(self.council_period)
        bills: list[Bill] = []
        misses = 0
        number = 1
        miss_limit = 100 if self.limit is None else 25
        while misses < miss_limit:
            bill_number = bill_number_for(self.council_period, number)
            response = self.http.get(_detail_url(bill_number))
            if response.status_code == 204 or not response.content:
                misses += 1
            else:
                misses = 0
                detail = response.json()
                if detail:
                    bills.append(parse_bill(detail, session=session))
                    if self.limit is not None and len(bills) >= self.limit:
                        break
            number += 1
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_period(period: int) -> Session:
    start_year = DEFAULT_START_YEAR + ((period - DEFAULT_COUNCIL_PERIOD) * 2)
    return Session(
        name=f"Council Period {period} ({start_year}-{start_year + 1})",
        start_date=date(start_year, 1, 1),
        end_date=date(start_year + 1, 12, 31),
        is_current=start_year <= datetime.now().year <= start_year + 1,
    )


def bill_number_for(period: int, number: int) -> str:
    return f"B{period}-{number:04d}"


def parse_bill(detail: dict[str, Any], *, session: Session) -> Bill:
    number = _clean_text(detail.get("legislationNumber"))
    title = _clean_text(detail.get("title")) or number
    summary = _clean_text(detail.get("shortDescription")) or _clean_text(detail.get("additionalInformation"))
    return Bill(
        jurisdiction=DistrictOfColumbiaScraper.jurisdiction,
        session_name=session.name,
        chamber=Chamber.JOINT,
        number=number,
        title=title,
        summary=summary or title,
        subjects=[_clean_text(detail.get("tag"))] if _clean_text(detail.get("tag")) else [],
        sponsors=_sponsors(detail),
        source_url=f"{ROOT}/Legislation/{number}",
        actions=_actions(detail),
        versions=_versions(detail),
        kind=classify_kind(title),
    )


def _actions(detail: dict[str, Any]) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in detail.get("legislationHistory") or []:
        if not isinstance(row, dict):
            continue
        text = _clean_text(row.get("actionText")) or _clean_text(row.get("type"))
        occurred_at = _parse_datetime(row.get("sortDate")) or _parse_date(row.get("date"))
        if occurred_at is None:
            continue
        data = row.get("data")
        meeting_actions = data.get("meetingActions") if isinstance(data, dict) else None
        if meeting_actions:
            for meeting_action in meeting_actions:
                if not isinstance(meeting_action, dict):
                    continue
                action_text = _meeting_action_text(row, meeting_action)
                if not action_text:
                    continue
                actions.append(BillAction(
                    occurred_at=occurred_at,
                    chamber=Chamber.JOINT,
                    action_text=action_text,
                    normalized_status=match_first(action_text, PATTERNS),
                    source_url=_absolute_url(_clean_text(meeting_action.get("documentUrl"))) if meeting_action.get("documentUrl") else None,
                ))
            continue
        if not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_action(text),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=_absolute_url(_clean_text(row.get("actionURL"))) if row.get("actionURL") else None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _meeting_action_text(row: dict[str, Any], meeting_action: dict[str, Any]) -> str:
    parts = [
        _clean_text(row.get("data", {}).get("meetingDescription")) if isinstance(row.get("data"), dict) else "",
        _clean_text(meeting_action.get("meetingAction")),
        _clean_text(meeting_action.get("voteResult")),
        _clean_text(meeting_action.get("additionalInformation")),
    ]
    return _clean_text(" ".join(part for part in parts if part))


def _versions(detail: dict[str, Any]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()

    def add(label: str, url: str | None) -> None:
        source_url = _absolute_url(_clean_text(url))
        if not source_url or source_url in seen:
            return
        seen.add(source_url)
        versions.append(BillVersion(label=_clean_text(label) or "document", source_url=source_url, format=_format_for_url(source_url)))

    add("legislation text", detail.get("legislationTextUrl"))
    for row in detail.get("legislationHistory") or []:
        if not isinstance(row, dict):
            continue
        add(_clean_text(row.get("type")) or _clean_text(row.get("actionText")) or "history document", row.get("actionURL"))
        data = row.get("data")
        if isinstance(data, dict):
            add(_clean_text(row.get("type")) or "history document", data.get("documentURL"))
            for meeting_action in data.get("meetingActions") or []:
                if isinstance(meeting_action, dict):
                    add(
                        _clean_text(meeting_action.get("documentType")) or _clean_text(meeting_action.get("meetingAction")) or "meeting document",
                        meeting_action.get("documentUrl"),
                    )
            dc_register = data.get("dCRegisterURL")
            if dc_register:
                add("DC Register", dc_register)
    for document in detail.get("otherDocuments") or []:
        if isinstance(document, dict):
            add(_clean_text(document.get("documentTitle")) or _clean_text(document.get("documentTypeName")) or "other document", document.get("url"))
    return versions


def _sponsors(detail: dict[str, Any]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for row in detail.get("legislationHistory") or []:
        data = row.get("data") if isinstance(row, dict) else None
        if not isinstance(data, dict):
            continue
        for introducer in data.get("introducers") or []:
            if isinstance(introducer, dict):
                _add_sponsor(sponsors, seen, introducer, role="primary")
    summary = detail.get("introducerSummary") or {}
    for item in summary.get("summaryDataList") or []:
        if not isinstance(item, dict) or _clean_text(item.get("label")).lower() != "introduced by":
            continue
        for name in _names_from_html(_clean_text(item.get("content"))):
            if name and name not in seen:
                seen.add(name)
                sponsors.append(Sponsor(name=name, role="primary"))
    return sponsors


def _add_sponsor(sponsors: list[Sponsor], seen: set[str], introducer: dict[str, Any], *, role: str) -> None:
    name = _clean_text(introducer.get("name")) or _clean_text(introducer.get("formalName"))
    if not name or name in seen:
        return
    seen.add(name)
    sponsors.append(Sponsor(name=name, role=role))


def _names_from_html(value: str) -> list[str]:
    if not value:
        return []
    tree = HTMLParser(value)
    names = [_clean_text(anchor.text()) for anchor in tree.css("a")]
    if names:
        return [name for name in names if name]
    text = _clean_text(tree.text(separator=" ", strip=True))
    return [text] if text else []


def _detail_url(number: str) -> str:
    return f"{ROOT}/api/Search/GetLegislationDetails/{number}"


def _absolute_url(url: str | None) -> str:
    if not url:
        return ""
    return urljoin(ROOT, url)


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _chamber_from_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "mayor" in lowered:
        return Chamber.EXECUTIVE
    return Chamber.JOINT


def _format_for_url(url: str) -> str:
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".docx"):
        return "docx"
    if lowered.endswith(".doc"):
        return "doc"
    return "html"


def _number_sort_key(number: str) -> tuple[str, int]:
    match = re.match(r"([A-Z]+\d+)-(\d+)", number.upper())
    if match is None:
        return (number, 0)
    return (match.group(1), int(match.group(2)))


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())
