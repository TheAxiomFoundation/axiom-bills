"""Idaho bill scraper.

Idaho publishes current session bill lists, bill detail pages, history
rows, sponsors, and official PDFs under legislature.idaho.gov.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
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

ROOT = "https://legislature.idaho.gov"
MT = ZoneInfo("America/Boise")


@dataclass(frozen=True)
class BillListItem:
    number: str
    title: str
    url: str
    status: str | None = None


class IdahoScraper(BillScraper):
    jurisdiction = "us-id"
    source_name = "legislature.idaho.gov"
    min_interval_per_host = 0.25

    def __init__(self, *, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year or datetime.now(tz=MT).year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        bills: list[Bill] = []
        for item in self._list_bill_items():
            html = self.http.get(item.url).text
            bill = parse_bill_page(html, item=item, session=session)
            if bill is not None:
                bills.append(bill)
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: bill.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session,
            bills=bills,
        )

    def _list_bill_items(self) -> list[BillListItem]:
        html = self.http.get(f"{ROOT}/sessioninfo/{self.year}/legislation/").text
        items = parse_list_items(html)
        return items[:self.limit] if self.limit is not None else items


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year} Idaho Legislature",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=True,
    )


def parse_list_items(html: str) -> list[BillListItem]:
    tree = HTMLParser(html)
    items: list[BillListItem] = []
    seen: set[str] = set()
    for table in tree.css("table.mini-data-table"):
        cells = table.css("td")
        if len(cells) < 2:
            continue
        link = cells[0].css_first("a")
        href = link.attributes.get("href") if link else None
        number = _clean_number(_clean_text(link.text() if link else cells[0].text()))
        title = _clean_text(cells[1].text())
        if not href or not number or not title or not _looks_like_bill(number):
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        status = _clean_text(cells[3].text()) if len(cells) > 3 else None
        items.append(BillListItem(number=number, title=title, url=url, status=status))
    return items


def parse_bill_page(html: str, *, item: BillListItem, session: Session) -> Bill | None:
    tree = HTMLParser(html)
    title = _title(tree) or item.title
    actions = _actions(tree, _year(session))
    return Bill(
        jurisdiction=IdahoScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=_sponsors(tree),
        source_url=item.url,
        actions=actions,
        versions=_versions(tree),
        kind=classify_kind(title),
    )


def _title(tree: HTMLParser) -> str | None:
    tables = tree.css("table.bill-table")
    if len(tables) < 2:
        return None
    return _clean_text(tables[1].text())


def _sponsors(tree: HTMLParser) -> list[Sponsor]:
    table = tree.css_first("table.bill-table")
    if table is None:
        return []
    cells = table.css("td")
    if len(cells) < 3:
        return []
    sponsor = _clean_text(cells[2].text())
    if sponsor and sponsor.lower().startswith("by "):
        sponsor = sponsor[3:].strip()
    return [Sponsor(name=sponsor, role="sponsor")] if sponsor else []


def _actions(tree: HTMLParser, year: int) -> list[BillAction]:
    tables = tree.css("table.bill-table")
    if len(tables) < 3:
        return []
    actions: list[BillAction] = []
    current_date: datetime | None = None
    for row in tables[2].css("tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        parsed_date = _parse_legislative_date(_clean_text(cells[1].text()), year)
        if parsed_date is not None:
            current_date = parsed_date
        text = _clean_text(cells[2].text())
        if current_date is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=current_date,
            chamber=_chamber_for_action(text) or _chamber_for_number(_clean_text(cells[0].text()) or ""),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css("a.plain"):
        href = link.attributes.get("href")
        label = _clean_text(link.text())
        if not href or not label or not href.lower().endswith(".pdf"):
            continue
        if label != "Bill Text":
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(label=label, source_url=source_url, format="pdf"))
    return versions


def _parse_legislative_date(raw: str | None, year: int) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.strptime(f"{year}/{raw}", "%Y/%m/%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=MT)


def _chamber_for_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "to senate" in lowered or "from senate" in lowered or "senate" in lowered:
        return Chamber.UPPER
    if "to house" in lowered or "from house" in lowered or "house" in lowered:
        return Chamber.LOWER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _year(session: Session) -> int:
    if session.start_date is not None:
        return session.start_date.year
    match = re.search(r"\d{4}", session.name)
    return int(match.group(0)) if match else datetime.now(tz=MT).year


def _clean_number(raw: str | None) -> str | None:
    if raw is None:
        return None
    return re.sub(r"[a-z]+$", "", raw.strip(), flags=re.IGNORECASE)


def _looks_like_bill(number: str) -> bool:
    return bool(re.match(r"^(H|S|HCR|SCR|HJM|SJM|HR|SR)\d+", number, re.IGNORECASE))


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
