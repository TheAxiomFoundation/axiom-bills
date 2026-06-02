"""North Carolina bill scraper.

North Carolina publishes official RSS feeds for all bills and per-bill
history under ncleg.gov/webservices.ncleg.gov. Bill text PDFs are served
from predictable official session URLs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillVersion,
    Chamber,
    ScrapeResult,
    Session,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

ROOT = "https://www.ncleg.gov"
HISTORY_ROOT = "https://webservices.ncleg.gov"


@dataclass(frozen=True)
class BillListItem:
    number: str
    compact_number: str
    title: str
    source_url: str
    last_action: str
    last_action_at: datetime | None


class NorthCarolinaScraper(BillScraper):
    jurisdiction = "us-nc"
    source_name = "ncleg.gov official RSS/webservices"
    min_interval_per_host = 0.25

    def __init__(self, *, session_year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_year = session_year or session_year_for_date(datetime.now())

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.session_year)
        items = parse_bill_feed(self.http.get(_all_bills_url(self.session_year)).text)
        if self.limit is not None:
            items = items[:self.limit]
        bills: list[Bill] = []
        for item in items:
            actions = parse_history_feed(
                self.http.get(_history_url(self.session_year, item.compact_number)).text,
                fallback=item,
            )
            bills.append(parse_bill(item, actions, session=session, session_year=self.session_year))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_year_for_date(now: datetime) -> int:
    return now.year if now.year % 2 == 1 else now.year - 1


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year}-{year + 1} North Carolina General Assembly",
        start_date=date(year, 1, 1),
        end_date=date(year + 1, 12, 31),
        is_current=year <= datetime.now().year <= year + 1,
    )


def parse_bill_feed(xml_text: str) -> list[BillListItem]:
    root = ET.fromstring(xml_text)
    items: list[BillListItem] = []
    for node in root.findall("./channel/item"):
        raw_title = _text(node, "title")
        source_url = _text(node, "link")
        if not raw_title or not source_url:
            continue
        number, title = _split_title(raw_title)
        compact = source_url.rstrip("/").split("/")[-1]
        if not number or not title or not compact:
            continue
        items.append(BillListItem(
            number=number,
            compact_number=compact,
            title=title,
            source_url=source_url,
            last_action=_last_action(_text(node, "description")),
            last_action_at=_parse_pub_date(_text(node, "pubDate")),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_history_feed(xml_text: str, *, fallback: BillListItem) -> list[BillAction]:
    root = ET.fromstring(xml_text)
    actions: list[BillAction] = []
    for node in root.findall("./channel/item"):
        title = _text(node, "title")
        occurred_at = _parse_pub_date(_text(node, "pubDate"))
        if not title or occurred_at is None:
            continue
        chamber, text = _history_action(title, fallback.number)
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    if not actions and fallback.last_action and fallback.last_action_at is not None:
        actions.append(BillAction(
            occurred_at=fallback.last_action_at,
            chamber=_chamber_for_number(fallback.number),
            action_text=fallback.last_action,
            normalized_status=match_first(fallback.last_action, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_bill(item: BillListItem, actions: list[BillAction], *, session: Session, session_year: int) -> Bill:
    return Bill(
        jurisdiction=NorthCarolinaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=item.title,
        summary=item.title,
        subjects=[],
        sponsors=[],
        source_url=item.source_url,
        actions=actions,
        versions=[BillVersion(label="introduced", source_url=_pdf_url(session_year, item.compact_number), format="pdf")],
        kind=classify_kind(item.title),
    )


def _split_title(raw: str) -> tuple[str | None, str | None]:
    if " - " not in raw:
        return None, None
    number, title = raw.split(" - ", 1)
    return _clean_text(number), _clean_text(title.rstrip("."))


def _history_action(raw: str, number: str) -> tuple[Chamber, str]:
    if ":" not in raw:
        return _chamber_for_number(number), _clean_text(raw) or raw
    branch, text = raw.split(":", 1)
    return _chamber(branch), _clean_text(text) or text


def _last_action(description: str | None) -> str:
    text = _clean_text(description)
    if not text:
        return ""
    return text.removeprefix("Last action: ").strip()


def _chamber(raw: str | None) -> Chamber:
    text = raw or ""
    if "Senate" in text:
        return Chamber.UPPER
    if "House" in text:
        return Chamber.LOWER
    return Chamber.JOINT


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _all_bills_url(year: int) -> str:
    return f"{ROOT}/Legislation/Bills/LastActionByYear/{year}/All/RSS"


def _history_url(year: int, compact_number: str) -> str:
    return f"{HISTORY_ROOT}/BillHistory/{year}/{compact_number}/RSS"


def _pdf_url(year: int, compact_number: str) -> str:
    body = "Senate" if compact_number.upper().startswith("S") else "House"
    return f"{ROOT}/Sessions/{year}/Bills/{body}/PDF/{compact_number}v1.pdf"


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _text(node: ET.Element, tag: str) -> str | None:
    child = node.find(tag)
    return _clean_text(child.text) if child is not None else None


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
