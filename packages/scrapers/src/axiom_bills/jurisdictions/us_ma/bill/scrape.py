"""Massachusetts bill scraper.

The Massachusetts Legislature publishes a public Swagger-documented API.
Document summaries, details, and history actions are available under
malegislature.gov/api/GeneralCourts/{generalCourt}/Documents.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

import httpx

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

ROOT = "https://malegislature.gov"


class MassachusettsScraper(BillScraper):
    jurisdiction = "us-ma"
    source_name = "malegislature.gov public API"
    min_interval_per_host = 0.2

    def __init__(self, *, general_court: int | None = None, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.general_court = general_court or general_court_for_year(year or datetime.now().year)

    def scrape(self) -> ScrapeResult:
        session = session_for_general_court(self.general_court)
        rows = self.http.get_json(f"{ROOT}/api/GeneralCourts/{self.general_court}/Documents")
        rows = [row for row in rows if _clean_text(_get(row, "BillNumber")) and not _get(row, "IsDocketBookOnly")]
        rows.sort(key=lambda row: _number_sort_key(_clean_text(_get(row, "BillNumber")) or ""))
        if self.limit is not None:
            rows = rows[:self.limit]
        bills: list[Bill] = []
        for row in rows:
            number = _clean_text(_get(row, "BillNumber"))
            if not number:
                continue
            try:
                detail = self.http.get_json(
                    f"{ROOT}/api/GeneralCourts/{self.general_court}/Documents/{number}"
                )
            except httpx.HTTPError:
                continue
            try:
                actions = self.http.get_json(
                    f"{ROOT}/api/GeneralCourts/{self.general_court}/Documents/{number}/DocumentHistoryActions"
                )
            except httpx.HTTPError:
                actions = []
            bill = parse_bill(detail, actions, summary=row, session=session)
            if bill is not None:
                bills.append(bill)
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def general_court_for_year(year: int) -> int:
    start_year = year if year % 2 == 1 else year - 1
    return 194 + ((start_year - 2025) // 2)


def session_for_general_court(general_court: int) -> Session:
    start_year = 2025 + ((general_court - 194) * 2)
    return Session(
        name=f"{general_court}th Massachusetts General Court ({start_year}-{start_year + 1})",
        start_date=date(start_year, 1, 1),
        end_date=date(start_year + 1, 12, 31),
        is_current=start_year <= datetime.now().year <= start_year + 1,
    )


def parse_bill(detail: dict, action_rows: list[dict], *, summary: dict, session: Session) -> Bill | None:
    number = _clean_text(_get(detail, "BillNumber") or _get(summary, "BillNumber"))
    if not number:
        return None
    title = _clean_text(_get(detail, "Title") or _get(summary, "Title")) or number
    actions = _actions(action_rows, number)
    if not actions:
        actions.append(BillAction(
            occurred_at=_filed_at(detail, summary, session),
            chamber=_chamber_for_number(number),
            action_text="Filed",
            normalized_status=match_first("Filed", PATTERNS),
        ))
    return Bill(
        jurisdiction=MassachusettsScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=_clean_text(_get(detail, "Pinslip")),
        subjects=[],
        sponsors=_sponsors(detail or summary),
        source_url=f"{ROOT}/Bills/{_get(detail, 'GeneralCourtNumber') or _get(summary, 'GeneralCourtNumber')}/{number}",
        actions=actions,
        versions=_versions(detail, number),
        kind=classify_kind(title),
    )


def _sponsors(row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    primary = _get(row, "PrimarySponsor")
    if isinstance(primary, dict):
        name = _clean_text(_get(primary, "Name"))
        if name:
            sponsors.append(Sponsor(name=name, role=_sponsor_role(primary, primary=True)))
    for sponsor in _get(row, "Cosponsors") or []:
        if not isinstance(sponsor, dict):
            continue
        name = _clean_text(_get(sponsor, "Name"))
        if name and not any(existing.name == name for existing in sponsors):
            sponsors.append(Sponsor(name=name, role=_sponsor_role(sponsor, primary=False)))
    joint = _get(row, "JointSponsor")
    if isinstance(joint, dict):
        name = _clean_text(_get(joint, "Name"))
        if name and not any(existing.name == name for existing in sponsors):
            sponsors.append(Sponsor(name=name, role="joint sponsor"))
    return sponsors


def _sponsor_role(sponsor: dict, *, primary: bool) -> str:
    sponsor_type = _get(sponsor, "Type")
    if sponsor_type == 2:
        return "committee"
    return "primary sponsor" if primary else "cosponsor"


def _actions(rows: list[dict], number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    fallback_chamber = _chamber_for_number(number)
    for row in rows:
        if _get(row, "IsStricken"):
            continue
        text = _clean_text(_strip_tags(_get(row, "Action")))
        occurred_at = _parse_datetime(_get(row, "Date"))
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber(_get(row, "Branch")) or fallback_chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(detail: dict, number: str) -> list[BillVersion]:
    general_court = _get(detail, "GeneralCourtNumber")
    versions = [
        BillVersion(
            label="current text",
            source_url=f"{ROOT}/Bills/{general_court}/{number}.Html",
            format="html",
        )
    ]
    seen = {versions[0].source_url}
    for attachment in _get(detail, "Attachments") or []:
        if not isinstance(attachment, dict):
            continue
        source_url = _clean_text(_get(attachment, "DownloadUrl"))
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(
            label=_clean_text(_get(attachment, "Description")) or "attachment",
            source_url=source_url,
            format=_format_for_url(source_url),
        ))
    return versions


def _filed_at(detail: dict, summary: dict, session: Session) -> datetime:
    primary = _get(detail, "PrimarySponsor") or _get(summary, "PrimarySponsor")
    if isinstance(primary, dict):
        response_date = _parse_datetime(_get(primary, "ResponseDate"))
        if response_date is not None:
            return response_date
    if session.start_date is not None:
        return datetime.combine(session.start_date, time.min)
    return datetime.now()


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "House":
        return Chamber.LOWER
    if raw == "Senate":
        return Chamber.UPPER
    if raw == "Joint":
        return Chamber.JOINT
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _get(row: dict, key: str):
    if key in row:
        return row[key]
    lowered = key[:1].lower() + key[1:]
    return row.get(lowered)


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _format_for_url(url: str) -> str:
    lower = url.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "html"
    return "txt"


def _strip_tags(raw) -> str | None:
    if raw is None:
        return None
    return re.sub(r"<[^>]+>", " ", str(raw))


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
