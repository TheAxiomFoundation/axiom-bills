"""Illinois bill scraper.

ILGA publishes current range pages and per-bill status pages under
ilga.gov/Legislation. The status pages include the official short title,
synopsis, sponsors, action table, and links to full text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

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

ROOT = "https://www.ilga.gov"
DEFAULT_GA_ID = 18
DEFAULT_SESSION_ID = 114
DEFAULT_GENERAL_ASSEMBLY = 104
DEFAULT_DOC_TYPES = ("HB", "SB")


@dataclass(frozen=True)
class IllinoisListItem:
    number: str
    title: str
    detail_url: str
    doc_type: str
    doc_num: int
    leg_id: int | None = None


class IllinoisScraper(BillScraper):
    jurisdiction = "us-il"
    source_name = "ilga.gov official legislation pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        ga_id: int = DEFAULT_GA_ID,
        session_id: int = DEFAULT_SESSION_ID,
        general_assembly: int = DEFAULT_GENERAL_ASSEMBLY,
        doc_types: tuple[str, ...] = DEFAULT_DOC_TYPES,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.ga_id = ga_id
        self.session_id = session_id
        self.general_assembly = general_assembly
        self.doc_types = doc_types

    def scrape(self) -> ScrapeResult:
        landing_html = self.http.get(f"{ROOT}/Legislation").text
        session = session_for_general_assembly(self.general_assembly)
        range_urls = parse_range_urls(
            landing_html,
            ga_id=self.ga_id,
            session_id=self.session_id,
            doc_types=self.doc_types,
        )
        bills: list[Bill] = []
        seen: set[str] = set()
        for range_url in range_urls:
            list_html = self.http.get(range_url).text
            for item in parse_listing(list_html):
                if item.number in seen:
                    continue
                seen.add(item.number)
                detail_html = self.http.get(item.detail_url).text
                bills.append(parse_bill(item, detail_html, session=session))
                if self.limit is not None and len(bills) >= self.limit:
                    bills.sort(key=lambda bill: _number_sort_key(bill.number))
                    return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_general_assembly(general_assembly: int) -> Session:
    start = 2025 + (general_assembly - DEFAULT_GENERAL_ASSEMBLY) * 2
    end = start + 1
    return Session(
        name=f"{_ordinal(general_assembly)} Illinois General Assembly ({start}-{end})",
        start_date=date(start, 1, 1),
        end_date=date(end, 12, 31),
        is_current=start <= datetime.now().year <= end,
    )


def parse_range_urls(
    html: str,
    *,
    ga_id: int,
    session_id: int,
    doc_types: tuple[str, ...] = DEFAULT_DOC_TYPES,
) -> list[str]:
    tree = HTMLParser(html)
    allowed = {doc_type.upper() for doc_type in doc_types}
    urls: list[str] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="/Legislation/RegularSession/"]'):
        href = link.attributes.get("href") or ""
        url = urljoin(ROOT, href)
        qs = parse_qs(urlsplit(url).query)
        doc_type = (qs.get("DocTypeID") or [""])[0].upper()
        if doc_type not in allowed:
            continue
        if _int_or_none((qs.get("GaId") or qs.get("GAID") or [""])[0]) != ga_id:
            continue
        if _int_or_none((qs.get("SessionId") or qs.get("SessionID") or [""])[0]) != session_id:
            continue
        if "num1=" not in url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    urls.sort(key=lambda url: (_doc_type_sort_key(_query_value(url, "DocTypeID")), _int_or_none(_query_value(url, "num1")) or 0))
    return urls


def parse_listing(html: str) -> list[IllinoisListItem]:
    tree = HTMLParser(html)
    items: list[IllinoisListItem] = []
    for row in tree.css("table tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        bill_link = _first_link(cells[0])
        title_link = _first_link(cells[1])
        if bill_link is None:
            continue
        raw_number = _clean_text(bill_link.text())
        href = bill_link.attributes.get("href")
        if not raw_number or not href:
            continue
        url = urljoin(ROOT, href)
        qs = parse_qs(urlsplit(url).query)
        doc_type = (qs.get("DocTypeID") or [_bill_prefix(raw_number)])[0].upper()
        doc_num = _int_or_none((qs.get("DocNum") or [""])[0]) or _bill_number_int(raw_number)
        if doc_num is None:
            continue
        title = _clean_text((title_link or cells[1]).text(separator=" "))
        items.append(IllinoisListItem(
            number=_format_number(doc_type, doc_num),
            title=title or raw_number,
            detail_url=url,
            doc_type=doc_type,
            doc_num=doc_num,
            leg_id=_int_or_none((qs.get("LegId") or qs.get("LegID") or [""])[0]),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: IllinoisListItem, html: str, *, session: Session) -> Bill:
    title = _title(html) or item.title or item.number
    summary = _summary(html) or title
    text_for_kind = " ".join(part for part in (title, summary) if part)
    return Bill(
        jurisdiction=IllinoisScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_doc_type(item.doc_type),
        number=item.number,
        title=title,
        summary=summary,
        subjects=_subjects(html),
        sponsors=parse_sponsors(html),
        source_url=item.detail_url,
        actions=parse_actions(html, source_url=item.detail_url),
        versions=parse_versions(html),
        kind=classify_kind(text_for_kind),
    )


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("table.table-striped tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        occurred_on = _parse_date(_clean_text(cells[0].text()))
        chamber = _chamber_from_text(_clean_text(cells[1].text()))
        text = _clean_text(cells[2].text(separator=" "))
        if occurred_on is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(html: str) -> list[Sponsor]:
    tree = HTMLParser(html)
    sponsor_div = tree.css_first("#sponsorDiv")
    if sponsor_div is None:
        return []
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in sponsor_div.css("a"):
        name = _clean_text(link.text())
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary"))
    return sponsors


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()

    def add(label: str, href: str | None, fmt: str = "html") -> None:
        if not href:
            return
        url = urljoin(ROOT, href)
        if url in seen:
            return
        seen.add(url)
        versions.append(BillVersion(label=_clean_text(label) or "full text", source_url=url, format=fmt))

    for link in tree.css('a[href*="/Legislation/BillStatus/FullText"]'):
        text = _clean_text(link.text())
        if "witness" in text.lower():
            continue
        add(text or "full text", link.attributes.get("href"), "html")
    for link in tree.css('a[href*="/documents/legislation/"][href$=".pdf"], a[href*="/documents/legislation/"][href*="/PDF/"]'):
        add(_clean_text(link.text()) or "pdf", link.attributes.get("href"), "pdf")
    return versions


def _title(html: str) -> str | None:
    tree = HTMLParser(html)
    headings = [_clean_text(node.text(separator=" ")) for node in tree.css("h5")]
    for text in headings:
        if text and text not in {
            "Select Language",
            "ILGA.gov Virtual Assistant",
            "Last Action",
            "House Sponsors",
            "Senate Sponsors",
            "Actions",
            "Statutes Amended In Order of Appearance",
            "Synopsis As Introduced",
        }:
            return text
    return None


def _summary(html: str) -> str | None:
    tree = HTMLParser(html)
    for heading in tree.css("h5"):
        if "synopsis" not in _clean_text(heading.text()).lower():
            continue
        container = heading.parent
        if container is None:
            continue
        synopsis = container.css_first(".list-group-item")
        if synopsis is not None:
            return _clean_text(synopsis.text(separator=" "))
    return None


def _subjects(html: str) -> list[str]:
    tree = HTMLParser(html)
    subjects: list[str] = []
    for heading in tree.css("h5"):
        if "statutes amended" not in _clean_text(heading.text()).lower():
            continue
        container = heading.parent
        if container is None:
            continue
        for node in container.css(".row .col-sm"):
            text = _clean_text(node.text(separator=" "))
            if text and "Statutes Amended" not in text and "Synopsis" not in text:
                subjects.append(text)
        break
    return subjects[:20]


def _first_link(node: Node) -> Node | None:
    return node.css_first("a[href]")


def _chamber_for_doc_type(doc_type: str) -> Chamber:
    if doc_type.upper().startswith("H"):
        return Chamber.LOWER
    if doc_type.upper().startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(text: str) -> Chamber | None:
    lowered = text.lower()
    if "house" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _format_number(doc_type: str, doc_num: int) -> str:
    return f"{doc_type.upper()} {doc_num}"


def _bill_prefix(number: str) -> str:
    match = re.match(r"([A-Za-z]+)", number.strip())
    return match.group(1).upper() if match else ""


def _bill_number_int(number: str) -> int | None:
    match = re.search(r"(\d+)", number)
    return int(match.group(1)) if match else None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = _bill_prefix(number)
    return (_doc_type_sort_key(prefix), _bill_number_int(number) or 0, number)


def _doc_type_sort_key(doc_type: str) -> int:
    return {"HB": 0, "SB": 1}.get(doc_type.upper(), 9)


def _query_value(url: str, name: str) -> str:
    values = parse_qs(urlsplit(url).query)
    for key, value in values.items():
        if key.lower() == name.lower() and value:
            return value[0]
    return ""


def _parse_date(value: str | None) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value or "")
    except ValueError:
        return None


def _ordinal(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
