"""North Dakota bill scraper.

North Dakota publishes official static JSON files by legislative assembly.
The bills dataset includes core bill metadata, action history, sponsors,
and official PDF version URLs in one response.
"""
from __future__ import annotations

from datetime import date, datetime

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

ROOT = "https://ndlegis.gov"


class NorthDakotaScraper(BillScraper):
    jurisdiction = "us-nd"
    source_name = "ndlegis.gov official static JSON API"
    min_interval_per_host = 0.2

    def __init__(self, *, assembly: str | None = None, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.assembly = assembly or assembly_for_year(year or datetime.now().year)

    def scrape(self) -> ScrapeResult:
        payload = self.http.get_json(f"{ROOT}/api/assembly/{self.assembly}/data/bills.json")
        session = session_from_payload(payload)
        rows = list((payload.get("bills") or {}).values())
        rows.sort(key=lambda row: _number_sort_key(_clean_text(row.get("name")) or ""))
        if self.limit is not None:
            rows = rows[:self.limit]
        bills = [parse_bill(row, session=session) for row in rows]
        bills = [bill for bill in bills if bill is not None]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def assembly_for_year(year: int) -> str:
    start_year = year if year % 2 == 1 else year - 1
    assembly_number = 69 + ((start_year - 2025) // 2)
    return f"{assembly_number}-{start_year}"


def session_from_payload(payload: dict) -> Session:
    start_year = int(payload.get("biennium_start") or datetime.now().year)
    end_year = int(payload.get("biennium_end") or start_year + 2)
    name = _clean_text(payload.get("assembly_name")) or f"{assembly_for_year(start_year)} North Dakota Assembly"
    return Session(
        name=f"{name} ({start_year}-{end_year})",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=start_year <= datetime.now().year <= end_year,
    )


def parse_bill(row: dict, *, session: Session) -> Bill | None:
    number = _clean_text(row.get("name"))
    if not number:
        return None
    title = _clean_text(row.get("title") or row.get("summary")) or number
    return Bill(
        jurisdiction=NorthDakotaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(row.get("chamber"), number),
        number=number,
        title=title,
        summary=_clean_text(row.get("summary")) or title,
        subjects=[],
        sponsors=_sponsors(row),
        source_url=_clean_text(row.get("url")) or f"{ROOT}/assembly/{session.name}/bill-overview/{number}",
        actions=_actions(row),
        versions=_versions(row),
        kind=classify_kind(title),
    )


def _sponsors(row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for sponsor in row.get("sponsors") or []:
        name = _clean_text(sponsor.get("name"))
        if not name:
            continue
        role = "primary sponsor" if sponsor.get("primary") else "sponsor"
        if _clean_text(sponsor.get("type")) == "committee":
            role = "committee"
        sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def _actions(row: dict) -> list[BillAction]:
    actions: list[BillAction] = []
    bill_chamber = _chamber(row.get("chamber"), _clean_text(row.get("name")) or "")
    for action in row.get("actions") or []:
        text = _clean_text(action.get("description") or action.get("category"))
        occurred_at = _parse_datetime(action.get("date"))
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber(action.get("chamber"), "") or bill_chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(row: dict) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for version in row.get("versions") or []:
        source_url = _clean_text(version.get("document_url"))
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        label_parts = [
            _clean_text(version.get("description")) or "Bill Text",
            _clean_text(version.get("lc_number")),
        ]
        versions.append(BillVersion(
            label=" - ".join(part for part in label_parts if part),
            source_url=source_url,
            format="pdf",
        ))
    return versions


def _chamber(raw: str | None, number: str) -> Chamber:
    text = _clean_text(raw)
    if text == "House" or number.upper().startswith("HB") or number.upper().startswith("HCR"):
        return Chamber.LOWER
    if text == "Senate" or number.upper().startswith("SB") or number.upper().startswith("SCR"):
        return Chamber.UPPER
    return Chamber.JOINT


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
