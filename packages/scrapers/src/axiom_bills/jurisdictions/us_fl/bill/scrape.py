"""Florida bill scraper.

The Florida Senate publishes current-session House and Senate bill lists,
detail pages, history rows, bill text links, and citations as official
server-rendered HTML under flsenate.gov.
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

ROOT = "https://www.flsenate.gov"
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BillListItem:
    number: str
    title: str
    sponsor: str | None
    url: str


class FloridaScraper(BillScraper):
    jurisdiction = "us-fl"
    source_name = "flsenate.gov"
    min_interval_per_host = 0.3

    def __init__(self, *, session_year: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_year = session_year

    def scrape(self) -> ScrapeResult:
        session_year = self.session_year or self._selected_session_year()
        session = session_for_year(session_year)
        bills: list[Bill] = []
        for item in self._list_bill_items(session_year):
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

    def _selected_session_year(self) -> str:
        html = self.http.get(f"{ROOT}/Session/Bills").text
        selected = selected_session_year(html)
        return selected or str(datetime.now(tz=ET).year)

    def _list_bill_items(self, session_year: str) -> list[BillListItem]:
        items: list[BillListItem] = []
        seen: set[str] = set()
        for chamber in ("senate", "house"):
            next_url: str | None = (
                f"{ROOT}/Session/Bills/{session_year}?Chamber={chamber}&PageNumber=1"
            )
            while next_url:
                html = self.http.get(next_url).text
                for item in parse_list_items(html):
                    if item.url in seen:
                        continue
                    seen.add(item.url)
                    items.append(item)
                    if self.limit is not None and len(items) >= self.limit:
                        return items
                next_url = parse_next_url(html)
        return items


def selected_session_year(html: str) -> str | None:
    tree = HTMLParser(html)
    for selector in (
        "select[name=LegislativeSessionTitle] option",
        "select[name=SessionYear] option",
    ):
        for option in tree.css(selector):
            if option.attributes.get("selected"):
                value = option.attributes.get("value")
                if value:
                    return value
    return None


def session_for_year(session_year: str) -> Session:
    year = _year(session_year)
    return Session(
        name=f"{session_year} Florida Legislature",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=True,
    )


def parse_list_items(html: str) -> list[BillListItem]:
    tree = HTMLParser(html)
    items: list[BillListItem] = []
    for row in tree.css("#billListDiv tbody tr"):
        cells = row.css("th,td")
        if len(cells) < 4:
            continue
        link = cells[0].css_first("a")
        href = link.attributes.get("href") if link else None
        number = _clean_text(link.text() if link else cells[0].text())
        title = _clean_text(cells[1].text())
        if not href or not number or not title:
            continue
        items.append(BillListItem(
            number=number,
            title=title,
            sponsor=_clean_text(cells[2].text()),
            url=urljoin(ROOT, href),
        ))
    return items


def parse_next_url(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first("a.next")
    href = node.attributes.get("href") if node else None
    return urljoin(ROOT, href) if href else None


def parse_bill_page(html: str, *, item: BillListItem, session: Session) -> Bill | None:
    tree = HTMLParser(html)
    title = _page_title(tree) or item.title
    return Bill(
        jurisdiction=FloridaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=_summary(tree),
        subjects=_citations(tree),
        sponsors=_sponsors(item),
        source_url=item.url,
        actions=_actions(tree, item.number),
        versions=_versions(tree),
        kind=classify_kind(title),
    )


def _page_title(tree: HTMLParser) -> str | None:
    node = tree.css_first("h2")
    text = _clean_text(node.text()) if node else None
    if not text:
        return None
    return text.split(":", 1)[1].strip() if ":" in text else text


def _summary(tree: HTMLParser) -> str | None:
    node = tree.css_first("p.width80")
    return _clean_text(node.text()) if node else None


def _sponsors(item: BillListItem) -> list[Sponsor]:
    return [Sponsor(name=item.sponsor, role="sponsor")] if item.sponsor else []


def _actions(tree: HTMLParser, number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in tree.css("#tabBodyBillHistory table tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        when = _parse_date(_clean_text(cells[0].text()))
        chamber = _chamber(_clean_text(cells[1].text())) or _chamber_for_number(number)
        if when is None:
            continue
        for text in _split_actions(cells[2].text()):
            actions.append(BillAction(
                occurred_at=when,
                chamber=chamber,
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _split_actions(raw: str) -> list[str]:
    return [
        text.strip()
        for text in re.split(r"\s*•\s*", raw)
        if text.strip()
    ]


def _versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for row in tree.css("#tabBodyBillText table tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        label = _clean_text(cells[0].text()) or "Bill Text"
        links = cells[2].css("a")
        preferred = _preferred_version_link(links)
        if preferred is None:
            continue
        href, fmt = preferred
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(label=label, source_url=source_url, format=fmt))
    return versions


def _preferred_version_link(links) -> tuple[str, str] | None:
    html_link: str | None = None
    for link in links:
        href = link.attributes.get("href")
        text = _clean_text(link.text()) or ""
        if not href:
            continue
        if "pdf" in text.lower() or href.lower().endswith("/pdf"):
            return href, "pdf"
        if html_link is None:
            html_link = href
    return (html_link, "html") if html_link else None


def _citations(tree: HTMLParser) -> list[str]:
    citations: list[str] = []
    for row in tree.css("#tabBodyCitations table tr"):
        cells = row.css("td")
        if not cells:
            continue
        citation = _clean_text(cells[0].text())
        if citation and citation not in citations:
            citations.append(f"Florida Statutes {citation}")
    return citations


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "Senate":
        return Chamber.UPPER
    if raw == "House":
        return Chamber.LOWER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.LOWER if number.upper().startswith("H") else Chamber.UPPER


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%m/%d/%Y")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ET)


def _year(session_year: str) -> int:
    match = re.search(r"\d{4}", session_year)
    return int(match.group(0)) if match else datetime.now(tz=ET).year


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None
