"""Delaware bill scraper.

Delaware publishes official JSON feeds for major bill states. We merge
those feeds by BillDetail URL and emit a minimal action for every feed
event, letting the shared writer roll up current status.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    Chamber,
    NormalizedStatus,
    ScrapeResult,
    Session,
    Sponsor,
)

from .kind import classify as classify_kind

ROOT = "https://legis.delaware.gov"
JSON_ROOT = f"{ROOT}/json/JsonFeed"
ET = ZoneInfo("America/New_York")

BILL_NUMBER_RE = re.compile(r"\b([HS])(?:B|R|CR|JR)?\s*(\d+)\b", re.IGNORECASE)

FEEDS: tuple[tuple[str, NormalizedStatus, str], ...] = (
    ("IntroducedLegislation", NormalizedStatus.INTRODUCED, "Introduced"),
    ("CommitteeLegislation", NormalizedStatus.IN_COMMITTEE, "In committee"),
    ("OutOfCommitteeLegislation", NormalizedStatus.IN_COMMITTEE, "Out of committee"),
    ("HousePassedLegislation", NormalizedStatus.PASSED_CHAMBER, "House passed"),
    ("SenatePassedLegislation", NormalizedStatus.PASSED_CHAMBER, "Senate passed"),
    ("GovernorSignedLegislation", NormalizedStatus.SIGNED, "Governor signed"),
    ("StrickenLegislation", NormalizedStatus.FAILED, "Stricken"),
)


class DelawareScraper(BillScraper):
    jurisdiction = "us-de"
    source_name = "legis.delaware.gov JSON feeds"
    min_interval_per_host = 0.5

    def scrape(self) -> ScrapeResult:
        bills_by_link: dict[str, dict] = {}
        for feed_name, status, action_text in FEEDS:
            payload = self.http.get_json(f"{JSON_ROOT}/{feed_name}")
            for item in payload.get("Items", []) or []:
                link = item.get("Link")
                if not link:
                    continue
                row = bills_by_link.setdefault(link, dict(item, Actions=[]))
                row.update({k: v for k, v in item.items() if v not in (None, "")})
                row["Actions"].append((status, action_text, _item_date(item)))

        session = _session_for_rows(bills_by_link.values())
        bills = [parse_feed_item(row, session.name) for row in bills_by_link.values()]
        bills = [b for b in bills if b is not None]
        bills.sort(key=lambda b: b.number)
        if self.limit is not None:
            bills = bills[:self.limit]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def parse_feed_item(item: dict, session_name: str) -> Bill | None:
    title = item.get("Title") or ""
    number = _number(title)
    if number is None:
        return None
    long_title = item.get("LongTitle") or title
    actions = [
        BillAction(
            occurred_at=when or datetime.now(tz=ET),
            chamber=_chamber_for_number(number),
            action_text=text,
            normalized_status=status,
        )
        for status, text, when in item.get("Actions", [])
    ]
    return Bill(
        jurisdiction=DelawareScraper.jurisdiction,
        session_name=session_name,
        chamber=_chamber_for_number(number),
        number=number,
        title=long_title,
        summary=item.get("Synopsis"),
        subjects=[],
        sponsors=_sponsors(item),
        source_url=item["Link"],
        actions=actions,
        versions=[],
        kind=classify_kind(long_title),
    )


def _number(raw: str) -> str | None:
    compact = " ".join(raw.split())
    if re.match(r"^[HS]A\s+\d+\s+to\s+", compact, re.IGNORECASE):
        return None
    match = re.search(r"\b((?:H|S)(?:B|R|CR|JR)\s*\d+)\b", compact, re.IGNORECASE)
    if match:
        return re.sub(r"\s+", "", match.group(1)).upper()
    match = BILL_NUMBER_RE.search(compact)
    if match:
        return f"{match.group(1).upper()}B{int(match.group(2))}"
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _sponsors(item: dict) -> list[Sponsor]:
    sponsor = item.get("Sponsor") or item.get("PrimarySponsor")
    if not sponsor:
        return []
    return [Sponsor(name=str(sponsor), role="primary")]


def _item_date(item: dict) -> datetime | None:
    for key in ("IntroducedDate", "ActionDate", "Date"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw)).replace(tzinfo=ET)
        except ValueError:
            continue
    return None


def _session_for_rows(rows) -> Session:
    sessions = [
        int(row["GeneralAssemblySession"])
        for row in rows
        if str(row.get("GeneralAssemblySession") or "").isdigit()
    ]
    assembly = max(sessions) if sessions else 153
    # Delaware General Assemblies are biennial. 153rd maps to 2025-2026.
    start_year = 2025 + (assembly - 153) * 2
    return Session(
        name=f"{assembly}th General Assembly ({start_year}-{start_year + 1})",
        start_date=date(start_year, 1, 1),
        end_date=date(start_year + 1, 12, 31),
        is_current=True,
    )
