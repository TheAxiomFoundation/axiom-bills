"""Mississippi bill scraper.

Mississippi publishes official all-measures XML plus per-bill history XML
under billstatus.ls.state.ms.us.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

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

ROOT = "https://billstatus.ls.state.ms.us/2026/pdf/"
ALL_MEASURES_URL = f"{ROOT}all_measures/allmsrs.xml"
DEFAULT_YEAR = 2026
ALLOWED_PREFIXES = ("HB", "SB")


@dataclass(frozen=True)
class MississippiListItem:
    number: str
    title: str
    author: str | None
    action: str | None
    history_url: str
    document_url: str | None = None


class MississippiScraper(BillScraper):
    jurisdiction = "us-ms"
    source_name = "billstatus.ls.state.ms.us official bill status XML"
    min_interval_per_host = 0.2
    verify_tls = False

    def __init__(self, *, year: int = DEFAULT_YEAR, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        listing_html = self.http.get(_all_measures_url(self.year)).text
        items = parse_listing(listing_html)
        if self.limit is not None:
            items = items[:self.limit]
        bills: list[Bill] = []
        for item in items:
            history_xml = self.http.get(item.history_url).text
            bills.append(parse_bill(item, history_xml, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year} Mississippi Regular Session",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=datetime.now().year == year,
    )


def parse_listing(xml_text: str) -> list[MississippiListItem]:
    root = ET.fromstring(xml_text.encode("ISO-8859-1", errors="ignore"))
    items: list[MississippiListItem] = []
    seen: set[str] = set()
    for group in root.findall(".//MSRGROUP"):
        number = _format_number(_text(group, "MEASURE"))
        if not number.startswith(ALLOWED_PREFIXES) or number in seen:
            continue
        action_link = _text(group, "ACTIONLINK")
        if not action_link:
            continue
        seen.add(number)
        items.append(MississippiListItem(
            number=number,
            title=_text(group, "SHORTTITLE") or number,
            author=_text(group, "AUTHOR") or None,
            action=_text(group, "ACTION") or None,
            history_url=urljoin(ALL_MEASURES_URL, action_link),
            document_url=urljoin(ALL_MEASURES_URL, _text(group, "MEASURELINK")) if _text(group, "MEASURELINK") else None,
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: MississippiListItem, xml_text: str, *, session: Session) -> Bill:
    root = ET.fromstring(xml_text.encode("ISO-8859-1", errors="ignore"))
    title = _text(root, "SHORTTITLE") or item.title
    summary = _text(root, "LONGTITLE") or title
    sponsors = parse_sponsors(root, fallback=item.author)
    return Bill(
        jurisdiction=MississippiScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=_text(root, "SHORT_MSRID") or item.number,
        title=title,
        summary=summary,
        subjects=parse_subjects(root),
        sponsors=sponsors,
        source_url=item.history_url,
        actions=parse_actions(root),
        versions=parse_versions(root, source_url=item.document_url),
        kind=classify_kind(" ".join(part for part in (title, summary) if part)),
    )


def parse_actions(root: ET.Element) -> list[BillAction]:
    year = int(_text(root, "YEAR") or DEFAULT_YEAR)
    actions: list[BillAction] = []
    for action in root.findall(".//ACTION"):
        desc = _text(action, "ACT_DESC")
        parsed = _parse_action_desc(desc, year=year)
        if parsed is None:
            continue
        occurred_on, chamber, text = parsed
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(root: ET.Element, *, fallback: str | None = None) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for node in root.findall(".//AUTHORS/PRINCIPAL/P_NAME"):
        name = _clean_text(node.text)
        if name and name not in seen:
            seen.add(name)
            sponsors.append(Sponsor(name=name, role="primary"))
    if not sponsors and fallback:
        sponsors.append(Sponsor(name=fallback, role="primary"))
    return sponsors


def parse_subjects(root: ET.Element) -> list[str]:
    sections: list[str] = []
    seen: set[str] = set()
    for node in root.findall(".//CODESECTIONS/SECTION"):
        value = _clean_text(node.text)
        if value and value not in seen:
            seen.add(value)
            sections.append(value)
    return sections


def parse_versions(root: ET.Element, *, source_url: str | None = None) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    if source_url:
        seen.add(source_url)
        versions.append(BillVersion(label="Current", source_url=source_url, format=_format_for_url(source_url)))
    documents = root.find(".//DOCUMENTS")
    if documents is None:
        return versions
    for node in documents.iter():
        if list(node):
            continue
        tag = node.tag
        url_part = _clean_text(node.text)
        if not url_part or not re.search(r"\.(pdf|htm)$", url_part, re.IGNORECASE):
            continue
        url = urljoin(ROOT, url_part)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_label_for_tag(tag),
            source_url=url,
            format=_format_for_url(url),
        ))
    return versions


def _all_measures_url(year: int) -> str:
    return f"https://billstatus.ls.state.ms.us/{year}/pdf/all_measures/allmsrs.xml"


def _parse_action_desc(desc: str, *, year: int) -> tuple[date, Chamber | None, str] | None:
    text = _clean_text(desc)
    match = re.match(r"(\d{2})/(\d{2})(?:\s+\(([HS])\))?\s+(.+)", text)
    if match is None:
        return None
    occurred_on = date(year, int(match.group(1)), int(match.group(2)))
    chamber = {"H": Chamber.LOWER, "S": Chamber.UPPER}.get(match.group(3) or "")
    return occurred_on, chamber, match.group(4)


def _format_number(value: str) -> str:
    match = re.match(r"([A-Za-z]+)\s*(\d+)", _clean_text(value))
    return f"{match.group(1).upper()} {int(match.group(2))}" if match else _clean_text(value)


def _chamber_for_number(number: str) -> Chamber:
    if number.upper().startswith("HB"):
        return Chamber.LOWER
    if number.upper().startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "SB": 1}.get(prefix, 9)
    match = re.search(r"\d+", number)
    return (order, int(match.group(0)) if match else 0, number)


def _label_for_tag(tag: str) -> str:
    return tag.replace("_", " ").title()


def _format_for_url(url: str) -> str:
    return "pdf" if url.lower().endswith(".pdf") else "html"


def _text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    return _clean_text(node.text if node is not None else None)


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
