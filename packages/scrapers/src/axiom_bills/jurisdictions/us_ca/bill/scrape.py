"""California bill scraper.

California publishes official bill status, history, and text version pages
under leginfo.legislature.ca.gov. Bill IDs are stable within a session,
for example 202520260AB1 for AB 1 in the 2025-2026 session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

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

ROOT = "https://leginfo.legislature.ca.gov"
DEFAULT_SESSION = "20252026"
BILL_PREFIXES = ("AB", "SB", "ACA", "ACR", "AJR", "HR", "SCA", "SCR", "SJR", "SR")


@dataclass(frozen=True)
class CaliforniaBillPage:
    bill_id: str
    number: str
    status_html: str
    history_html: str


class CaliforniaScraper(BillScraper):
    jurisdiction = "us-ca"
    source_name = "leginfo.legislature.ca.gov official bill pages"
    min_interval_per_host = 0.2

    def __init__(self, *, session_year: str = DEFAULT_SESSION, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_year = session_year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.session_year)
        bills: list[Bill] = []
        for bill_id in self._bill_ids():
            page = self._page_for_bill_id(bill_id)
            if page is None:
                continue
            bills.append(parse_bill(page, session=session))
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _bill_ids(self):
        prefixes = BILL_PREFIXES if self.limit is None else ("AB", "SB")
        miss_limit = 100 if self.limit is None else 25
        for prefix in prefixes:
            misses = 0
            number = 1
            while misses < miss_limit:
                bill_id = bill_id_for(self.session_year, prefix, number)
                status_html = self.http.get(_status_url(bill_id)).text
                if _is_missing_bill(status_html):
                    misses += 1
                else:
                    misses = 0
                    yield bill_id, status_html
                number += 1

    def _page_for_bill_id(self, value) -> CaliforniaBillPage | None:
        if isinstance(value, tuple):
            bill_id, status_html = value
        else:
            bill_id = value
            status_html = self.http.get(_status_url(bill_id)).text
        if _is_missing_bill(status_html):
            return None
        fields = parse_status_fields(status_html)
        number = fields.get("Measure") or _number_from_bill_id(bill_id)
        history_html = self.http.get(_history_url(bill_id)).text
        return CaliforniaBillPage(bill_id=bill_id, number=number, status_html=status_html, history_html=history_html)


def session_for_year(session_year: str) -> Session:
    start = int(session_year[:4])
    end = int(session_year[4:])
    return Session(
        name=f"{start}-{end} California Regular Session",
        start_date=date(start, 1, 1),
        end_date=date(end, 12, 31),
        is_current=start <= datetime.now().year <= end,
    )


def parse_bill(page: CaliforniaBillPage, *, session: Session) -> Bill:
    fields = parse_status_fields(page.status_html)
    number = fields.get("Measure") or page.number
    title = fields.get("Topic") or number
    sponsors = _sponsors(fields)
    return Bill(
        jurisdiction=CaliforniaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=fields.get("Title") or title,
        subjects=[title] if title else [],
        sponsors=sponsors,
        source_url=_status_url(page.bill_id),
        actions=parse_history_actions(page.history_html, source_url=_history_url(page.bill_id)),
        versions=parse_versions(page.status_html, bill_id=page.bill_id),
        kind=classify_kind(title),
    )


def parse_status_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    ids = {
        "Measure": "measureNum",
        "Lead Authors": "leadAuthors",
        "Principal Coauthors": "principalAuthors",
        "Coauthors": "coAuthors",
        "Topic": "subject",
        "Title": "title",
        "House Location": "houseLoc",
        "Last Action": "lastAction",
    }
    fields: dict[str, str] = {}
    for label, node_id in ids.items():
        node = tree.css_first(f"#{node_id}")
        text = _clean_text(node.text()) if node is not None else None
        if text and text != "-":
            fields[label] = text
    return fields


def parse_history_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("#billhistory tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        occurred_at = _parse_date(_clean_text(cells[0].text()))
        text = _clean_text(cells[1].text())
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_action(text),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(html: str, *, bill_id: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    select = tree.css_first("#version")
    if select is None:
        return versions
    for option in select.css("option"):
        version_id = _clean_text(option.attributes.get("value"))
        label_text = _clean_text(option.text()) or "document"
        if not version_id:
            continue
        label = _version_label(label_text)
        url = _text_url(bill_id, version_id)
        if url not in seen:
            seen.add(url)
            versions.append(BillVersion(label=label, source_url=url, format="html"))
        pdf_url = _pdf_url(bill_id, version_id)
        if pdf_url not in seen:
            seen.add(pdf_url)
            versions.append(BillVersion(label=f"{label} pdf", source_url=pdf_url, format="pdf"))
    return versions


def bill_id_for(session_year: str, prefix: str, number: int) -> str:
    return f"{session_year}0{prefix}{number}"


def _sponsors(fields: dict[str, str]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for label, role in [
        ("Lead Authors", "primary"),
        ("Principal Coauthors", "cosponsor"),
        ("Coauthors", "cosponsor"),
    ]:
        for name in _split_authors(fields.get(label)):
            sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def _split_authors(raw: str | None) -> list[str]:
    text = _clean_text(raw)
    if not text:
        return []
    parts = [part.strip() for part in text.replace(" ,", ",").split(",")]
    return [part for part in parts if part and part != "-"]


def _is_missing_bill(html: str) -> bool:
    if "Bill not found" in html:
        return True
    return HTMLParser(html).css_first("#measureNum") is None


def _status_url(bill_id: str) -> str:
    return f"{ROOT}/faces/billStatusClient.xhtml?{urlencode({'bill_id': bill_id})}"


def _history_url(bill_id: str) -> str:
    return f"{ROOT}/faces/billHistoryClient.xhtml?{urlencode({'bill_id': bill_id})}"


def _text_url(bill_id: str, version_id: str) -> str:
    return f"{ROOT}/faces/billTextClient.xhtml?{urlencode({'bill_id': bill_id, 'version': version_id})}"


def _pdf_url(bill_id: str, version_id: str) -> str:
    return f"{ROOT}/faces/billPdf.xhtml?{urlencode({'bill_id': bill_id, 'version': version_id})}"


def _version_label(raw: str) -> str:
    text = raw.lower()
    if "chapter" in text:
        return "chaptered"
    if "enrolled" in text:
        return "enrolled"
    if "introduced" in text:
        return "introduced"
    if "amended" in text:
        return "amended"
    return _clean_text(raw) or "document"


def _number_from_bill_id(bill_id: str) -> str:
    tail = bill_id[9:]
    letters = "".join(ch for ch in tail if ch.isalpha())
    digits = "".join(ch for ch in tail if ch.isdigit())
    return f"{letters}-{digits}" if letters and digits else bill_id


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _chamber_from_action(text: str) -> Chamber | None:
    lower = text.lower()
    if "senate" in lower:
        return Chamber.UPPER
    if "assembly" in lower:
        return Chamber.LOWER
    if "governor" in lower:
        return Chamber.EXECUTIVE
    if "secretary of state" in lower:
        return Chamber.EXECUTIVE
    return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%m/%d/%y")
    except ValueError:
        return None


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _clean_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
