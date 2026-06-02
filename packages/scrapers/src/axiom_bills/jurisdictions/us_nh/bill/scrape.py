"""New Hampshire bill scraper.

New Hampshire publishes current legislation through official ASP.NET
Bill Status pages. Search results are reachable by bill number, and each
result links to a billinfo.aspx detail page with the bill docket.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
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

ROOT = "https://gc.nh.gov/bill_status/"
DEFAULT_YEAR_START = 2025
DEFAULT_YEAR_END = 2026
DEFAULT_ID_START = 1
DEFAULT_ID_END = 2600


@dataclass(frozen=True)
class NewHampshireListItem:
    number: str
    title: str | None
    status: str | None
    detail_url: str


class NewHampshireScraper(BillScraper):
    jurisdiction = "us-nh"
    source_name = "gc.nh.gov official New Hampshire Bill Status pages"
    min_interval_per_host = 0.25

    def __init__(
        self,
        *,
        id_start: int = DEFAULT_ID_START,
        id_end: int = DEFAULT_ID_END,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.id_start = id_start
        self.id_end = id_end

    def scrape(self) -> ScrapeResult:
        session = session_for_years(DEFAULT_YEAR_START, DEFAULT_YEAR_END)
        bills: list[Bill] = []
        for bill_id in range(self.id_start, self.id_end + 1):
            if self.limit is not None and len(bills) >= self.limit:
                break
            detail_url = _detail_url(bill_id)
            try:
                detail_html = self.http.get(detail_url).text
            except httpx.HTTPError:
                continue
            item = list_item_from_detail(detail_html, detail_url)
            if item is None:
                continue
            bills.append(parse_bill(item, detail_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_years(start_year: int, end_year: int) -> Session:
    return Session(
        name=f"{start_year}-{end_year} New Hampshire General Court",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=start_year <= datetime.now().year <= end_year,
    )


def parse_listing(html: str) -> list[NewHampshireListItem]:
    tree = HTMLParser(html)
    items: list[NewHampshireListItem] = []
    for link in tree.css("a[href*='billinfo.aspx']"):
        href = link.attributes.get("href")
        number = _clean_text(link.text())
        if not href or not _looks_like_bill_number(number):
            continue
        container = _result_container(link)
        items.append(NewHampshireListItem(
            number=_format_number(number),
            title=_result_field(container, "Title:") if container else None,
            status=_result_field(container, "General Status:") if container else None,
            detail_url=urljoin(ROOT, href),
        ))
    return items


def list_item_from_detail(html: str, detail_url: str) -> NewHampshireListItem | None:
    tree = HTMLParser(html)
    number = _detail_number(tree)
    if number is None:
        return None
    title = _label_text(tree, "#dvTitle", "Title:")
    status = _label_text(tree, ".dBarBodyStatus", "General Status:")
    return NewHampshireListItem(number=number, title=title, status=status, detail_url=detail_url)


def parse_bill(item: NewHampshireListItem, html: str, *, session: Session) -> Bill:
    tree = HTMLParser(html)
    title = _label_text(tree, "#dvTitle", "Title:") or item.title or item.number
    summary = title
    return Bill(
        jurisdiction=NewHampshireScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=_detail_number(tree) or item.number,
        title=title,
        summary=summary,
        subjects=parse_subjects(tree),
        sponsors=parse_sponsors(tree),
        source_url=item.detail_url,
        actions=parse_actions(tree, source_url=item.detail_url),
        versions=parse_versions(tree),
        kind=classify_kind(title),
    )


def parse_actions(tree: HTMLParser, *, source_url: str | None = None) -> list[BillAction]:
    actions: list[BillAction] = []
    panel = tree.css_first("#pageBody_pnlDocket")
    if panel is None:
        return actions
    seen_rows: set[tuple[str, str]] = set()
    for row in panel.css("div"):
        chamber_cell = row.css_first(".dvDocketC1")
        text_cell = row.css_first(".dvDocketC2")
        if chamber_cell is None or text_cell is None:
            continue
        chamber = _chamber_from_text(_clean_text(chamber_cell.text()))
        text = _clean_text(text_cell.text(separator=" "))
        key = (_clean_text(chamber_cell.text()), text)
        if key in seen_rows:
            continue
        seen_rows.add(key)
        occurred_on = _date_from_text(text)
        if occurred_on is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=_first_link(text_cell) or source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(tree: HTMLParser) -> list[Sponsor]:
    node = tree.css_first("#dvSponosrs")
    if node is None:
        return []
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in node.css("a"):
        title = _clean_text(link.attributes.get("title"))
        text = _clean_text(link.text())
        role = "primary" if "prime" in text.lower() else None
        name = _sponsor_name(title, text)
        party = _party_from_text(title or text)
        if name and name not in seen:
            seen.add(name)
            sponsors.append(Sponsor(name=name, role=role, party=party))
    return sponsors


def parse_subjects(tree: HTMLParser) -> list[str]:
    subjects: list[str] = []
    seen: set[str] = set()
    for selector in ("#pageBody_dvHouseStat .dBarBodyComm", "#pageBody_dvSenStat .sdBarBodyComm"):
        text = _label_text(tree, selector, "Committee:")
        if text and text not in seen:
            seen.add(text)
            subjects.append(text)
    return subjects


def parse_versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    for option in tree.css("#pageBody_ddlBillVersions option"):
        value = _clean_text(option.attributes.get("value"))
        label = _clean_text(option.text())
        if not value.isdigit() or "select" in label.lower():
            continue
        versions.append(BillVersion(
            label=label,
            source_url=urljoin(ROOT, f"pdf.aspx?id={value}&q=billVersion"),
            format="pdf",
        ))
    return versions


def _detail_url(bill_id: int) -> str:
    return urljoin(ROOT, f"billinfo.aspx?id={bill_id}&inflect=2")


def _chamber_for_number(number: str) -> Chamber:
    upper = number.upper()
    if upper.startswith(("HB", "HR")):
        return Chamber.LOWER
    if upper.startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(value: str) -> Chamber | None:
    text = value.upper()
    if text == "H":
        return Chamber.LOWER
    if text == "S":
        return Chamber.UPPER
    return None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _date_from_text(text: str) -> date | None:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if match is None:
        return None
    year = int(match.group(3))
    if year < 100:
        year += 2000
    return date(year, int(match.group(1)), int(match.group(2)))


def _detail_number(tree: HTMLParser) -> str | None:
    text = _clean_text(tree.css_first("#dvBillNo").text() if tree.css_first("#dvBillNo") else "")
    match = re.search(r"\b((?:HB|SB|HR|HCR|CACR)\s*\d+(?:-[A-Z-]+)?)\b", text, re.IGNORECASE)
    return _format_number(match.group(1)) if match else None


def _first_link(node: Node) -> str | None:
    link = node.css_first("a[href]")
    return urljoin(ROOT, link.attributes["href"]) if link is not None else None


def _format_number(number: str) -> str:
    match = re.match(r"([A-Za-z]+)\s*(\d+)(.*)", _clean_text(number))
    if match is None:
        return _clean_text(number)
    suffix = _clean_text(match.group(3)).upper()
    return f"{match.group(1).upper()} {int(match.group(2))}{suffix}"


def _label_text(tree: HTMLParser, selector: str, label: str) -> str | None:
    node = tree.css_first(selector)
    if node is None:
        return None
    text = _clean_text(node.text(separator=" "))
    value = re.sub(rf"^{re.escape(label)}\s*", "", text, flags=re.IGNORECASE).strip()
    return value or None


def _looks_like_bill_number(text: str) -> bool:
    return re.match(r"^(?:HB|SB|HR|HCR|CACR)\s*\d+", _clean_text(text), re.IGNORECASE) is not None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "SB": 1, "CACR": 2, "HR": 3, "HCR": 4}.get(prefix, 9)
    match = re.search(r"\d+", number)
    return (order, int(match.group(0)) if match else 0, number)


def _party_from_text(text: str) -> str | None:
    match = re.search(r"\(([RDr])\)", text)
    return match.group(1).upper() if match else None


def _result_container(link: Node) -> Node | None:
    node = link.parent
    while node is not None:
        if node.css_first(".BS-ResultsCol2") is not None:
            return node
        node = node.parent
    return None


def _result_field(container: Node, label: str) -> str | None:
    children = container.css("div")
    for index, child in enumerate(children[:-1]):
        if _clean_text(child.text()).rstrip(":").lower() == label.rstrip(":").lower():
            return _clean_text(children[index + 1].text()) or None
    return None


def _sponsor_name(title: str, text: str) -> str:
    source = title or text
    source = re.sub(r"^(?:Sen|Rep)\.\s*", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s*\([RDr]\)\s*$", "", source).strip()
    source = source.replace("(Prime)", "").strip()
    return _clean_text(source)
