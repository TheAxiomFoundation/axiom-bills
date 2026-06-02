"""Arkansas bill scraper.

Arkansas publishes official bill lists and per-bill detail/history pages
as server-rendered HTML under arkleg.state.ar.us.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

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

ROOT = "https://www.arkleg.state.ar.us"
DEFAULT_BIENNIUM_SESSION = "2025/2025R"
PAGE_SIZE = 20


@dataclass(frozen=True)
class BillListItem:
    number: str
    title: str
    sponsor: str | None
    detail_url: str
    bill_url: str | None
    act_url: str | None


class ArkansasScraper(BillScraper):
    jurisdiction = "us-ar"
    source_name = "arkleg.state.ar.us official bill pages"
    min_interval_per_host = 0.25

    def __init__(
        self,
        *,
        biennium_session: str = DEFAULT_BIENNIUM_SESSION,
        bill_types: tuple[str, ...] = ("HB", "SB"),
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.biennium_session = biennium_session
        self.bill_types = bill_types

    def scrape(self) -> ScrapeResult:
        session = self._session()
        items = self._bill_items()
        if self.limit is not None:
            items = items[:self.limit]
        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            previous_html = self._previous_versions_html(item.number)
            bills.append(parse_bill(item, detail_html, previous_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session(self) -> Session:
        html = self.http.get(_list_url(self.biennium_session, "HB", 0)).text
        return parse_session(html, biennium_session=self.biennium_session)

    def _bill_items(self) -> list[BillListItem]:
        items_by_number: dict[str, BillListItem] = {}
        for bill_type in self.bill_types:
            start = 0
            while True:
                html = self.http.get(_list_url(self.biennium_session, bill_type, start)).text
                batch = parse_bill_list(html)
                for item in batch:
                    items_by_number.setdefault(item.number, item)
                if self.limit is not None and len(items_by_number) >= self.limit:
                    break
                next_start = _next_start(html, current_start=start)
                if next_start is None:
                    break
                start = next_start
        items = list(items_by_number.values())
        items.sort(key=lambda item: _number_sort_key(item.number))
        return items

    def _previous_versions_html(self, number: str) -> str | None:
        url = f"{ROOT}/Bills/PreviousVersions?{urlencode({'id': number, 'ddBienniumSession': self.biennium_session})}"
        response = self.http.get(url)
        if response.status_code >= 400:
            return None
        return response.text


def parse_session(html: str, *, biennium_session: str = DEFAULT_BIENNIUM_SESSION) -> Session:
    tree = HTMLParser(html)
    heading = _clean_text((tree.css_first("h1") or tree.css_first("title")).text() if tree.css_first("h1") or tree.css_first("title") else None)
    body = _clean_text(tree.body.text() if tree.body else tree.text()) or ""
    match = re.search(r"(\d+)(?:st|nd|rd|th)\s+General Assembly\s+-\s+([^,\n]+),\s*(\d{4})", body, re.IGNORECASE)
    if match:
        name = f"{match.group(1)}th General Assembly - {match.group(2).strip()}, {match.group(3)}"
        year = int(match.group(3))
    else:
        year_match = re.search(r"(\d{4})", biennium_session)
        year = int(year_match.group(1)) if year_match else datetime.now().year
        name = heading or f"{year} Arkansas General Assembly"
    return Session(
        name=name,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=True,
    )


def parse_bill_list(html: str) -> list[BillListItem]:
    tree = HTMLParser(html)
    items: list[BillListItem] = []
    seen: set[str] = set()
    for row in tree.css(".tableRow, .tableRowAlt"):
        cells = row.css('[role="gridcell"]')
        if len(cells) < 4:
            continue
        number_anchor = row.css_first('a[aria-label^="Bill Number"]')
        if number_anchor is None:
            continue
        number = _clean_text(number_anchor.text())
        href = number_anchor.attributes.get("href")
        if not number or not href or number in seen:
            continue
        title = _clean_text(cells[1].text()) or number
        sponsor = _clean_text(cells[2].text())
        doc_links = cells[3].css("a")
        bill_url = _document_url(doc_links, "Bill")
        act_url = _document_url(doc_links, "Act")
        items.append(BillListItem(
            number=number,
            title=title,
            sponsor=sponsor,
            detail_url=urljoin(ROOT, href),
            bill_url=bill_url,
            act_url=act_url,
        ))
        seen.add(number)
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: BillListItem, detail_html: str, previous_versions_html: str | None, *, session: Session) -> Bill:
    details = parse_detail_fields(detail_html)
    number = details.get("Bill Number") or item.number
    title = item.title
    sponsor = details.get("Lead Sponsor") or item.sponsor
    actions = parse_actions(detail_html, source_url=item.detail_url)
    if not actions:
        actions = _fallback_actions(details, number, item.detail_url)
    versions = parse_versions(detail_html, previous_versions_html, item=item)
    return Bill(
        jurisdiction=ArkansasScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(details.get("Originating Chamber")) or _chamber_for_number(number),
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=[Sponsor(name=sponsor, role="sponsor")] if sponsor else [],
        source_url=item.detail_url,
        actions=actions,
        versions=versions,
        kind=classify_kind(title),
    )


def parse_detail_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    fields: dict[str, str] = {}
    for row in tree.css(".tableRow, .tableRowAlt"):
        cells = row.css('[role="gridcell"]')
        if len(cells) != 2:
            continue
        label = (_clean_text(cells[0].text()) or "").rstrip(":")
        if label in {
            "Bill Number",
            "Act Number",
            "Status",
            "Originating Chamber",
            "Lead Sponsor",
            "Introduction Date",
            "Act Date",
        }:
            value = _clean_text(cells[1].text())
            if value:
                if label == "Bill Number":
                    value = value.replace("PDF ", "").strip()
                fields[label] = value
    return fields


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css(".tableRow, .tableRowAlt"):
        cells = row.css('[role="gridcell"]')
        if len(cells) != 4:
            continue
        chamber = _chamber(_clean_text(cells[0].text()))
        occurred_at = _parse_datetime(_clean_text(cells[1].text()))
        text = _clean_text(cells[2].text())
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(detail_html: str, previous_versions_html: str | None, *, item: BillListItem) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()

    def add(label: str, source_url: str | None) -> None:
        if not source_url or source_url in seen:
            return
        seen.add(source_url)
        versions.append(BillVersion(label=label, source_url=source_url, format=_format_for_url(source_url)))

    add("current", item.bill_url)
    add("act", item.act_url)
    for label, url in _detail_document_links(detail_html):
        add(label, url)
    if previous_versions_html:
        for label, url in _previous_version_links(previous_versions_html, item.number):
            add(label, url)
    return versions


def _detail_document_links(html: str) -> list[tuple[str, str]]:
    tree = HTMLParser(html)
    links: list[tuple[str, str]] = []
    for anchor in tree.css("a"):
        href = anchor.attributes.get("href") or ""
        decoded_href = unquote(href)
        if "FTPDocument" not in href:
            continue
        aria = _clean_text(anchor.attributes.get("aria-label")) or ""
        text = _clean_text(anchor.text()) or ""
        if "VetoBook" in decoded_href or "Important Dates" in decoded_href:
            continue
        label = "amendment" if "/AMEND/" in decoded_href else "document"
        if aria.lower().startswith("act"):
            label = "act"
        elif text.upper() == "PDF":
            alt = anchor.css_first("img")
            img_alt = _clean_text(alt.attributes.get("alt")) if alt is not None else None
            if img_alt:
                label = "amendment" if "-" in img_alt else "current"
        links.append((label, urljoin(ROOT, href)))
    return links


def _previous_version_links(html: str, number: str) -> list[tuple[str, str]]:
    tree = HTMLParser(html)
    links: list[tuple[str, str]] = []
    for anchor in tree.css("a"):
        href = anchor.attributes.get("href") or ""
        text = _clean_text(anchor.text()) or ""
        if "FTPDocument" not in href or not text.startswith(number):
            continue
        label = text.replace(number, "", 1).strip().lower() or "previous"
        links.append((label, urljoin(ROOT, href)))
    return links


def _fallback_actions(details: dict[str, str], number: str, source_url: str) -> list[BillAction]:
    text = details.get("Status")
    occurred_at = _parse_datetime(details.get("Act Date") or details.get("Introduction Date"))
    if not text or occurred_at is None:
        return []
    if "--" in text:
        chamber_text, action_text = text.split("--", 1)
        chamber = _chamber(chamber_text)
        text = action_text.strip()
    else:
        chamber = _chamber_for_number(number)
    return [BillAction(
        occurred_at=occurred_at,
        chamber=chamber,
        action_text=text,
        normalized_status=match_first(text, PATTERNS),
        source_url=source_url,
    )]


def _document_url(anchors: list[Node], label: str) -> str | None:
    for anchor in anchors:
        aria = _clean_text(anchor.attributes.get("aria-label")) or ""
        text = _clean_text(anchor.text()) or ""
        if label.lower() in aria.lower() or text == label:
            href = anchor.attributes.get("href")
            if href:
                return urljoin(ROOT, href)
    return None


def _next_start(html: str, *, current_start: int) -> int | None:
    tree = HTMLParser(html)
    target = current_start + PAGE_SIZE
    for anchor in tree.css(".tableSectionFooter a"):
        href = anchor.attributes.get("href") or ""
        query = parse_qs(urlsplit(href).query)
        raw_start = query.get("start", [None])[0]
        if raw_start is None:
            continue
        try:
            start = int(raw_start)
        except ValueError:
            continue
        if start == target:
            return start
    return None


def _list_url(biennium_session: str, bill_type: str, start: int) -> str:
    return f"{ROOT}/Bills/ViewBills?{urlencode({'ddBienniumSession': biennium_session, 'start': start, 'type': bill_type})}"


def _format_for_url(url: str) -> str:
    lower = url.lower()
    if ".pdf" in lower:
        return "pdf"
    if ".html" in lower:
        return "html"
    return "txt"


def _chamber(raw: str | None) -> Chamber | None:
    text = _clean_text(raw) or ""
    if text.startswith("Chamber:"):
        text = text.removeprefix("Chamber:").strip()
    if text.lower().startswith("house"):
        return Chamber.LOWER
    if text.lower().startswith("senate"):
        return Chamber.UPPER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw: str | None) -> datetime | None:
    text = _clean_text(raw)
    if not text:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
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
