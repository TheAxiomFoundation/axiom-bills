"""South Carolina bill scraper.

South Carolina's official site is HTML-based. The current-session House
and Senate introduction indexes provide the roster, and billsearch.php
returns batched bill details with title, sponsors, text links, and
history tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser, Node

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

ROOT = "https://www.scstatehouse.gov"
SESSION_ID = "126"
SESSION_LABEL = "2025-2026"
INTRO_INDEXES = ("/sessphp/hintros.php", "/sessphp/sintros.php")


@dataclass(frozen=True)
class SouthCarolinaIntroItem:
    compact_number: str
    number: str
    source_url: str


class SouthCarolinaScraper(BillScraper):
    jurisdiction = "us-sc"
    source_name = "scstatehouse.gov official South Carolina Legislature Online"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session = Session(
            name=f"{SESSION_LABEL} South Carolina Legislative Session",
            start_date=date(2025, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=datetime.now().year in {2025, 2026},
        )
        items = self._intro_items()
        bills: list[Bill] = []
        for batch in _chunks(items, 20):
            html = self.http.get(_billsearch_url([item.compact_number for item in batch])).text
            bills.extend(parse_billsearch(html, session=session))
            if self.limit is not None and len(bills) >= self.limit:
                bills = bills[:self.limit]
                break
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _intro_items(self) -> list[SouthCarolinaIntroItem]:
        items: list[SouthCarolinaIntroItem] = []
        seen: set[str] = set()
        for index_path in INTRO_INDEXES:
            index_html = self.http.get(urljoin(ROOT, index_path)).text
            for page_url in intro_page_urls(index_html):
                page_html = self.http.get(page_url).text
                for item in parse_intro_page(page_html):
                    if item.compact_number in seen:
                        continue
                    seen.add(item.compact_number)
                    items.append(item)
                    if self.limit is not None and len(items) >= self.limit:
                        return items
        return items


def intro_page_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    urls: list[str] = []
    seen: set[str] = set()
    for link in tree.css("a[href*='/sess126_2025-2026/'][href$='.htm']"):
        href = link.attributes.get("href") or ""
        if "/hintro" not in href and "/sintro" not in href:
            continue
        url = urljoin(ROOT, href)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_intro_page(html: str) -> list[SouthCarolinaIntroItem]:
    tree = HTMLParser(html)
    items: list[SouthCarolinaIntroItem] = []
    for link in tree.css("a[href*='billsearch.php'][href*='billnumbers=']"):
        href = link.attributes.get("href") or ""
        text = _clean_text(link.text())
        number = _format_number(text)
        if not number:
            continue
        compact = number.replace(" ", "").lower()
        items.append(SouthCarolinaIntroItem(
            compact_number=compact,
            number=number,
            source_url=urljoin(ROOT, href),
        ))
    return items


def parse_billsearch(html: str, *, session: Session) -> list[Bill]:
    tree = HTMLParser(html)
    bills: list[Bill] = []
    for item in tree.css(".bill-list-item"):
        bill = parse_bill_item(item, session=session)
        if bill is not None:
            bills.append(bill)
    return bills


def parse_bill_item(item: Node, *, session: Session) -> Bill | None:
    header = _clean_text(_node_text(item.css_first("span")))
    match = re.match(r"([HS])\*?\s*(\d+)\s+(.+?),\s+By\b", header)
    if match is None:
        return None
    number = f"{match.group(1)} {int(match.group(2))}"
    title = _title_from_item(item) or number
    source_url = _source_url(number)
    return Bill(
        jurisdiction=SouthCarolinaScraper.jurisdiction,
        session_name=session.name,
        chamber=Chamber.LOWER if number.startswith("H ") else Chamber.UPPER,
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=parse_sponsors(item),
        source_url=source_url,
        actions=parse_actions(item, source_url=source_url),
        versions=parse_versions(item),
        kind=classify_kind(title),
    )


def parse_sponsors(item: Node) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in item.css("span a[href*='member.php']"):
        name = _clean_text(link.text())
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary" if not sponsors else "cosponsor"))
    return sponsors


def parse_actions(item: Node, *, source_url: str | None = None) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in item.css("tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        occurred_at = _parse_date(_clean_text(cells[0].text()))
        action_text = _clean_text(cells[2].text())
        if occurred_at is None or not action_text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_text(_clean_text(cells[1].text())),
            action_text=action_text,
            normalized_status=match_first(action_text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(item: Node) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in item.css("a[href]"):
        href = link.attributes.get("href") or ""
        label = _clean_text(link.text())
        if "View full text" not in label and not re.search(r"/bills/\d+\.(?:htm|docx)$", href, re.IGNORECASE):
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        fmt = "docx" if source_url.lower().endswith(".docx") else "html"
        versions.append(BillVersion(label=label or "Bill text", source_url=source_url, format=fmt))
    return versions


def _billsearch_url(compact_numbers: list[str]) -> str:
    params = urlencode({
        "billnumbers": ",".join(compact_numbers),
        "session": SESSION_ID,
        "summary": "B",
    })
    return f"{ROOT}/billsearch.php?{params}"


def _title_from_item(item: Node) -> str:
    html = item.html or ""
    match = re.search(r"</span>(.*?)(?:<br><A\s+class=\"nodisplay\"\s+HREF=\"/sess126_2025-2026/bills/)", html, re.IGNORECASE | re.DOTALL)
    if match is None:
        return ""
    fragment = re.sub(r"<[^>]+>", " ", match.group(1))
    return _clean_text(unescape(fragment))


def _source_url(number: str) -> str:
    compact = number.replace(" ", "").lower()
    return _billsearch_url([compact])


def _format_number(text: str) -> str:
    match = re.search(r"\b([HS])\.\s*(\d+)\b", text.upper())
    if match is None:
        match = re.search(r"\b([HS])\s*(\d+)\b", text.upper())
    if match is None:
        return ""
    return f"{match.group(1)} {int(match.group(2))}"


def _parse_date(text: str) -> datetime | None:
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _chamber_from_text(text: str) -> Chamber | None:
    lowered = text.lower()
    if "house" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _node_text(node: Node | None) -> str:
    return node.text() if node is not None else ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())


def _chunks[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]
