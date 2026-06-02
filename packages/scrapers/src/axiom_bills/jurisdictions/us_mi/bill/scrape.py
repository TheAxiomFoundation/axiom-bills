"""Michigan bill scraper.

Michigan publishes official search-result pages for the current legislative
session and per-bill detail pages under Home/GetObject.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

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

ROOT = "https://www.legislature.mi.gov"
DEFAULT_SESSION = "2025-2026"
DEFAULT_DOC_TYPES = ("House Bill", "Senate Bill")


@dataclass(frozen=True)
class MichiganListItem:
    number: str
    doc_type: str
    title: str
    summary: str
    detail_url: str


class MichiganScraper(BillScraper):
    jurisdiction = "us-mi"
    source_name = "legislature.mi.gov official bill pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        session: str = DEFAULT_SESSION,
        doc_types: tuple[str, ...] = DEFAULT_DOC_TYPES,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.session = session
        self.doc_types = doc_types

    def scrape(self) -> ScrapeResult:
        session = session_for_code(self.session)
        items: list[MichiganListItem] = []
        for doc_type in self.doc_types:
            html = self.http.get(_search_url(self.session, doc_type)).text
            items.extend(parse_listing(html))
        items.sort(key=lambda item: _number_sort_key(item.number))
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            bills.append(parse_bill(item, detail_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_code(session: str) -> Session:
    start, end = [int(part) for part in session.split("-", 1)]
    return Session(
        name=f"Michigan Legislature {session}",
        start_date=date(start, 1, 1),
        end_date=date(end, 12, 31),
        is_current=start <= datetime.now().year <= end,
    )


def parse_listing(html: str) -> list[MichiganListItem]:
    tree = HTMLParser(html)
    items: list[MichiganListItem] = []
    seen: set[str] = set()
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 3:
            continue
        link = cells[0].css_first('a[href*="ObjectName=2025-"]')
        if link is None:
            continue
        href = link.attributes.get("href")
        number = _format_number(_clean_text(link.text(separator=" ")))
        if not href or not number or number in seen:
            continue
        seen.add(number)
        doc_type = _clean_text(cells[1].text(separator=" "))
        summary = _clean_summary(cells[2].text(separator=" "))
        items.append(MichiganListItem(
            number=number,
            doc_type=doc_type,
            title=summary or number,
            summary=summary or number,
            detail_url=urljoin(ROOT, href),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: MichiganListItem, html: str, *, session: Session) -> Bill:
    summary = _summary(html) or item.summary
    subjects = parse_subjects(html)
    title = summary or item.title
    return Bill(
        jurisdiction=MichiganScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=summary,
        subjects=subjects,
        sponsors=parse_sponsors(html),
        source_url=item.detail_url,
        actions=parse_actions(html, source_url=item.detail_url),
        versions=parse_versions(html),
        kind=classify_kind(" ".join(part for part in (title, summary) if part)),
    )


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 3:
            continue
        occurred_on = _parse_date(_clean_text(cells[0].text()))
        if occurred_on is None:
            continue
        journal = _clean_text(cells[1].text(separator=" "))
        text = _clean_text(cells[2].text(separator=" "))
        if not text:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=_chamber_from_journal(journal),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(html: str) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in HTMLParser(html).css('a[href*="sponsorTypesList"]'):
        name = re.sub(r"\s+\(District\s+\d+\)$", "", _clean_text(link.text(separator=" ")))
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary" if not sponsors else "cosponsor"))
    return sponsors


def parse_subjects(html: str) -> list[str]:
    summary = _summary(html) or ""
    if ":" not in summary:
        return []
    subject = _clean_text(summary.split(";", 1)[0].split(":", 1)[0]).title()
    return [subject] if subject else []


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="/documents/"][href$=".pdf"], a[href*="/documents/"][href$=".htm"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        lowered = href.lower()
        if "billanalysis" in lowered:
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_version_label(url),
            source_url=url,
            format="pdf" if lowered.endswith(".pdf") else "html",
        ))
    return versions


def _search_url(session: str, doc_type: str) -> str:
    return f"{ROOT}/Search/ExecuteSearch?sessions={session}&docTypes={doc_type.replace(' ', '%20')}"


def _summary(html: str) -> str | None:
    tree = HTMLParser(html)
    for h2 in tree.css("h2"):
        if _clean_text(h2.text()).lower() != "categories":
            continue
        parent = h2.parent
        if parent is None:
            continue
        text = _clean_text(parent.text(separator=" "))
        text = re.sub(r"^Categories\s+", "", text)
        if text:
            parts = text.split("Documents Bill Document", 1)[0]
            return _clean_summary(parts)
    return None


def _clean_summary(value: str) -> str:
    text = _clean_text(value)
    return re.split(r"\s+Last Action:\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]


def _format_number(value: str) -> str:
    match = re.search(r"\b([HS]B)\s*0*(\d+)", value, re.IGNORECASE)
    return f"{match.group(1).upper()} {int(match.group(2))}" if match else _clean_text(value)


def _chamber_for_number(number: str) -> Chamber:
    if number.upper().startswith("HB"):
        return Chamber.LOWER
    if number.upper().startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_journal(journal: str) -> Chamber | None:
    if journal.upper().startswith("HJ"):
        return Chamber.LOWER
    if journal.upper().startswith("SJ"):
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "SB": 1}.get(prefix, 9)
    match = re.search(r"\d+", number)
    return (order, int(match.group(0)) if match else 0, number)


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(_clean_text(value), "%m/%d/%Y").date()
    except ValueError:
        return None


def _version_label(url: str) -> str:
    path = urlsplit(url).path
    file_name = path.rsplit("/", 1)[-1]
    folder = path.split("/")[-3] if len(path.split("/")) >= 3 else ""
    return f"{folder} {file_name}".strip()


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
