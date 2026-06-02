"""Kansas bill scraper.

Kansas publishes the KLISS RESTian Interface. The public v5/rev-1
endpoints expose a bill listing and a bill_status feed with full action
history for the current biennium.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    Chamber,
    ScrapeResult,
    Session,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

ROOT = "https://www.kslegislature.gov"
API = f"{ROOT}/li/api/v5/rev-1"
CT = ZoneInfo("America/Chicago")


class KansasScraper(BillScraper):
    jurisdiction = "us-ks"
    source_name = "Kansas KLISS REST API"
    min_interval_per_host = 0.5

    def scrape(self) -> ScrapeResult:
        listing = self.http.get_json(f"{API}/bill_listing/").get("content") or []
        statuses = self.http.get_json(f"{API}/bill_status/").get("content") or []
        history_by_bill = {
            str(row.get("BILLNO") or "").upper(): row.get("HISTORY") or []
            for row in statuses
        }
        bills = [
            parse_listing_row(row, history_by_bill.get(str(row.get("BILLNO") or "").upper(), []))
            for row in listing
        ]
        bills = [bill for bill in bills if bill is not None]
        bills.sort(key=lambda bill: bill.number)
        if self.limit is not None:
            bills = bills[:self.limit]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=current_session(), bills=bills)


def current_session() -> Session:
    return Session(
        name="2025-2026 Legislature",
        start_date=date(2025, 1, 13),
        end_date=date(2026, 5, 31),
        is_current=True,
    )


def parse_listing_row(row: dict, history_rows: list[dict]) -> Bill | None:
    number = str(row.get("BILLNO") or "").upper()
    if not number:
        return None
    title = _clean_text(row.get("SHORTTITLE")) or number
    return Bill(
        jurisdiction=KansasScraper.jurisdiction,
        session_name=current_session().name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=[],
        source_url=f"{ROOT}/li/b2025_26/measures/{number}/",
        actions=_actions(history_rows, number),
        versions=[],
        kind=classify_kind(title),
    )


def _actions(rows: list[dict], number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        text = _clean_text(row.get("status"))
        when = _parse_datetime(row.get("occurred_datetime"))
        if not text or when is None:
            continue
        actions.append(BillAction(
            occurred_at=when,
            chamber=_chamber(row.get("chamber")) or _chamber_for_number(number),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "Senate":
        return Chamber.UPPER
    if raw == "House":
        return Chamber.LOWER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.startswith("SB") else Chamber.LOWER


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=CT)
    except ValueError:
        return None


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    return " ".join(str(raw).split())
