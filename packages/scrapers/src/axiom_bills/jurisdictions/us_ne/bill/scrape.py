"""Nebraska bill scraper.

Nebraska publishes official CSV search results by introduction date and
bill detail pages with official PDFs and action histories.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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

ROOT = "https://nebraskalegislature.gov"
CT = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class BillListItem:
    number: str
    title: str
    sponsor: str
    status: str
    document_id: str


class NebraskaScraper(BillScraper):
    jurisdiction = "us-ne"
    source_name = "nebraskalegislature.gov"
    min_interval_per_host = 3.5

    def __init__(self, *, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year or datetime.now(tz=CT).year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        bills: list[Bill] = []
        seen: set[str] = set()
        for day in self._session_days():
            for item in self._list_for_day(day):
                if item.document_id in seen:
                    continue
                seen.add(item.document_id)
                detail = self.http.get(_detail_url(item.document_id)).text
                bills.append(parse_bill_page(detail, item=item, session=session))
                if self.limit is not None and len(bills) >= self.limit:
                    bills.sort(key=lambda bill: (_number_sort_key(bill.number), bill.number))
                    return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)
        bills.sort(key=lambda bill: (_number_sort_key(bill.number), bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session_days(self) -> list[str]:
        html = self.http.get(f"{ROOT}/bills/").text
        return parse_session_days(html, year=self.year)

    def _list_for_day(self, day: str) -> list[BillListItem]:
        csv_text = self.http.get(f"{ROOT}/bills/search_by_date.php?SessionDay={day}&print=csv").text
        return parse_date_csv(csv_text)


def session_for_year(year: int) -> Session:
    legislature = legislature_for_year(year)
    return Session(
        name=f"{legislature}th Nebraska Legislature ({year})",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now(tz=CT).year,
    )


def legislature_for_year(year: int) -> int:
    return 109 + ((year - 2025) // 2)


def parse_session_days(html: str, *, year: int) -> list[str]:
    tree = HTMLParser(html)
    days: list[str] = []
    for option in tree.css("#SessionDay option"):
        value = option.attributes.get("value")
        if value and value.startswith(f"{year}-"):
            days.append(value)
    return days


def parse_date_csv(csv_text: str) -> list[BillListItem]:
    rows = csv.DictReader(StringIO(csv_text.lstrip()))
    items: list[BillListItem] = []
    for row in rows:
        number = _clean_text(row.get("Document"))
        document_id = _clean_text(row.get("Document ID"))
        title = _clean_text(row.get("Description"))
        if not number or not document_id or not title:
            continue
        items.append(BillListItem(
            number=number,
            title=title,
            sponsor=_clean_text(row.get("Primary Introducer")) or "",
            status=_clean_text(row.get("Status")) or "",
            document_id=document_id,
        ))
    return items


def parse_bill_page(html: str, *, item: BillListItem, session: Session) -> Bill:
    tree = HTMLParser(html)
    title = _title(tree, item.number) or item.title
    return Bill(
        jurisdiction=NebraskaScraper.jurisdiction,
        session_name=session.name,
        chamber=Chamber.JOINT,
        number=item.number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=[Sponsor(name=item.sponsor, role="sponsor")] if item.sponsor else [],
        source_url=_detail_url(item.document_id),
        actions=_actions(tree),
        versions=_versions(tree),
        kind=classify_kind(title),
    )


def _title(tree: HTMLParser, number: str) -> str | None:
    for heading in tree.css("h2"):
        text = _clean_text(heading.text())
        if not text or not text.upper().startswith(number.upper()):
            continue
        if " - " not in text:
            return text
        return text.split(" - ", 1)[1]
    return None


def _versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    allowed_labels = {"introduced", "final reading", "slip law", "engrossed"}
    for link in tree.css("a"):
        href = link.attributes.get("href")
        label = _clean_text(link.text())
        if not href or not label or "/PDF/" not in href or not href.lower().endswith(".pdf"):
            continue
        normalized_label = label.lower()
        if normalized_label not in allowed_labels:
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(label=normalized_label, source_url=source_url, format="pdf"))
    return versions


def _actions(tree: HTMLParser) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in tree.css("table tbody tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        occurred_at = _parse_action_date(_clean_text(cells[0].text()))
        text = _clean_text(cells[1].text())
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=Chamber.JOINT,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _parse_action_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%b %d, %Y").replace(tzinfo=CT)
    except ValueError:
        return None


def _detail_url(document_id: str) -> str:
    return f"{ROOT}/bills/view_bill.php?DocumentID={document_id}"


def _number_sort_key(number: str) -> int:
    digits = "".join(ch for ch in number if ch.isdigit())
    return int(digits) if digits else 0


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
