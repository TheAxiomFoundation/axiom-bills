"""Kentucky bill scraper.

Kentucky publishes official per-session legislative record pages at
apps.legislature.ky.gov/record/{session}/. The title listings enumerate bills,
and each bill page contains metadata, action history, and document links.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

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

ROOT = "https://apps.legislature.ky.gov"
DEFAULT_SESSION_CODE = "26RS"
DEFAULT_SESSION_NAME = "2026 Kentucky Regular Session"
DEFAULT_LISTINGS = ("house_bills_title.html", "senate_bills_title.html")


@dataclass(frozen=True)
class KentuckyListItem:
    number: str
    title: str
    detail_url: str
    prime_sponsor: str | None = None


class KentuckyScraper(BillScraper):
    jurisdiction = "us-ky"
    source_name = "apps.legislature.ky.gov official legislative record pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        session_code: str = DEFAULT_SESSION_CODE,
        listings: tuple[str, ...] = DEFAULT_LISTINGS,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.session_code = session_code
        self.listings = listings

    def scrape(self) -> ScrapeResult:
        session = session_for_code(self.session_code)
        items: list[KentuckyListItem] = []
        for listing in self.listings:
            html = self.http.get(_session_url(self.session_code, listing)).text
            items.extend(parse_listing(html, session_code=self.session_code))
        items.sort(key=lambda item: _number_sort_key(item.number))
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            bills.append(parse_bill(item, detail_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_code(session_code: str) -> Session:
    match = re.match(r"(\d{2})RS", session_code, re.IGNORECASE)
    year = 2000 + int(match.group(1)) if match else datetime.now().year
    return Session(
        name=f"{year} Kentucky Regular Session",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=datetime.now().year == year,
    )


def parse_listing(html: str, *, session_code: str = DEFAULT_SESSION_CODE) -> list[KentuckyListItem]:
    tree = HTMLParser(html)
    items: list[KentuckyListItem] = []
    for row in tree.css("table tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        bill_link = _first_link(cells[0])
        if bill_link is None:
            continue
        raw_number = _clean_text(bill_link.text())
        href = bill_link.attributes.get("href")
        if not raw_number or not href:
            continue
        items.append(KentuckyListItem(
            number=_format_number(raw_number),
            prime_sponsor=_clean_text(cells[1].text(separator=" ")) or None,
            title=_clean_text(cells[2].text(separator=" ")) or raw_number,
            detail_url=urljoin(_session_url(session_code, ""), href),
        ))
    return items


def parse_bill(item: KentuckyListItem, html: str, *, session: Session) -> Bill:
    fields = _metadata_fields(html)
    title = fields.get("Title") or item.title or item.number
    summary = fields.get("Summary of Original Version") or title
    sponsors = parse_sponsors(fields.get("Sponsors"), fallback=item.prime_sponsor)
    return Bill(
        jurisdiction=KentuckyScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=summary,
        subjects=parse_subjects(html),
        sponsors=sponsors,
        source_url=item.detail_url,
        actions=parse_actions(html, source_url=item.detail_url),
        versions=parse_versions(html),
        kind=classify_kind(" ".join(part for part in (title, summary) if part)),
    )


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for table in tree.css("table.table-striped"):
        rows = table.css("tr")
        if not rows:
            continue
        first_cells = rows[0].css("th,td")
        if len(first_cells) < 2:
            continue
        if _parse_date(_clean_text(first_cells[0].text())) is None and _parse_date(_clean_text(first_cells[1].text())) is None:
            continue
        for row in rows:
            cells = row.css("th,td")
            if len(cells) < 2:
                continue
            first = _clean_text(cells[0].text())
            second = _clean_text(cells[1].text(separator=" "))
            occurred_on = _parse_date(first)
            text = second
            if occurred_on is None:
                occurred_on = _parse_date(second)
                text = first
            if occurred_on is None or not text:
                continue
            actions.append(BillAction(
                occurred_at=datetime.combine(occurred_on, datetime.min.time()),
                chamber=_chamber_from_text(text),
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
                source_url=source_url,
            ))
        break
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(value: str | None, *, fallback: str | None = None) -> list[Sponsor]:
    source = value or fallback or ""
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for raw in re.split(r",|;", source):
        name = _clean_text(raw)
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary"))
    return sponsors


def parse_subjects(html: str) -> list[str]:
    tree = HTMLParser(html)
    subjects: list[str] = []
    seen: set[str] = set()
    for row in _metadata_table(tree).css("tr") if _metadata_table(tree) else []:
        cells = row.css("th,td")
        if len(cells) < 2 or "Index Headings" not in _clean_text(cells[0].text()):
            continue
        for link in cells[1].css("a"):
            text = _clean_text(link.text())
            if text and text not in seen:
                seen.add(text)
                subjects.append(text)
        break
    return subjects


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css('a[href$=".pdf"], a[href*=".pdf#"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        lower = url.lower()
        if "/recorddocuments/" not in lower and "/law/acts/" not in lower:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_clean_text(link.text(separator=" ")) or _label_from_url(url),
            source_url=url,
            format="pdf",
        ))
    return versions


def _metadata_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    fields: dict[str, str] = {}
    table = _metadata_table(tree)
    if table is None:
        return fields
    for row in table.css("tr"):
        cells = row.css("th,td")
        if len(cells) < 2:
            continue
        label = _clean_text(cells[0].text(separator=" ")).rstrip(":")
        value = _clean_text(cells[1].text(separator=" "))
        if label and value:
            fields[label] = value
    return fields


def _metadata_table(tree: HTMLParser) -> Node | None:
    for table in tree.css("table.table-striped"):
        text = _clean_text(table.text(separator=" "))
        if "Last Action" in text and "Bill Documents" in text:
            return table
    return None


def _session_url(session_code: str, path: str) -> str:
    return f"{ROOT}/record/{session_code.lower()}/{path}"


def _first_link(node: Node) -> Node | None:
    return node.css_first("a[href]")


def _format_number(value: str) -> str:
    lowered = value.lower()
    prefix = "HB" if "house" in lowered or lowered.startswith("hb") else "SB"
    number = re.search(r"(\d+)", value)
    return f"{prefix} {int(number.group(1))}" if number else _clean_text(value)


def _chamber_for_number(number: str) -> Chamber:
    if number.upper().startswith("HB"):
        return Chamber.LOWER
    if number.upper().startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(text: str) -> Chamber | None:
    if re.search(r"\(H\)|\bHouse\b", text, re.IGNORECASE):
        return Chamber.LOWER
    if re.search(r"\(S\)|\bSenate\b", text, re.IGNORECASE):
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "SB": 1}.get(prefix, 9)
    match = re.search(r"(\d+)", number)
    return (order, int(match.group(1)) if match else 0, number)


def _parse_date(value: str | None) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _label_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
