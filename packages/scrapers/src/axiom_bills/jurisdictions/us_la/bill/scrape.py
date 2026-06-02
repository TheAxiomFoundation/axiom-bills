"""Louisiana bill scraper.

Louisiana publishes full-session final disposition pages and per-bill detail
pages at legis.la.gov. The disposition pages enumerate all House and Senate
instruments for a session; each BillInfo page contains title, authors, action
history, and official document links.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

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

ROOT = "https://www.legis.la.gov"
LEGIS_ROOT = f"{ROOT}/legis/"
DEFAULT_SESSION_CODE = "26RS"


@dataclass(frozen=True)
class LouisianaListItem:
    number: str
    detail_url: str


class LouisianaScraper(BillScraper):
    jurisdiction = "us-la"
    source_name = "legis.la.gov official bill pages"
    min_interval_per_host = 0.2

    def __init__(self, *, session_code: str = DEFAULT_SESSION_CODE, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_code = session_code

    def scrape(self) -> ScrapeResult:
        session = session_for_code(self.session_code)
        items: list[LouisianaListItem] = []
        for chamber_code, prefix in (("H", "HB"), ("S", "SB")):
            html = self.http.get(_final_disposition_url(self.session_code, chamber_code)).text
            items.extend(parse_listing(html, prefix=prefix))
        items.sort(key=lambda item: _number_sort_key(item.number))
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            html = self.http.get(item.detail_url).text
            bills.append(parse_bill(item, html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_code(session_code: str) -> Session:
    match = re.match(r"(\d{2})RS", session_code, re.IGNORECASE)
    year = 2000 + int(match.group(1)) if match else datetime.now().year
    start = date(year, 3, 9) if year == 2026 else date(year, 1, 1)
    end = date(year, 6, 1) if year == 2026 else date(year, 12, 31)
    today = datetime.now().date()
    return Session(
        name=f"{year} Louisiana Regular Session",
        start_date=start,
        end_date=end,
        is_current=start <= today <= end,
    )


def parse_listing(html: str, *, prefix: str) -> list[LouisianaListItem]:
    tree = HTMLParser(html)
    items: list[LouisianaListItem] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="BillInfo.aspx"]'):
        number_text = _clean_text(link.text())
        number_match = re.fullmatch(r"\d+", number_text)
        href = link.attributes.get("href")
        if number_match is None or not href:
            continue
        number = f"{prefix.upper()} {int(number_match.group(0))}"
        if number in seen:
            continue
        seen.add(number)
        items.append(LouisianaListItem(
            number=number,
            detail_url=urljoin(LEGIS_ROOT, href),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: LouisianaListItem, html: str, *, session: Session) -> Bill:
    bill_number = _format_number(_text_by_id(html, "ctl00_PageBody_LabelBillID")) or item.number
    title = _text_by_id(html, "ctl00_PageBody_LabelShortTitle") or item.number
    summary = title
    text_for_kind = " ".join(part for part in (title, summary) if part)
    return Bill(
        jurisdiction=LouisianaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(bill_number),
        number=bill_number,
        title=title,
        summary=summary,
        subjects=parse_subjects(title),
        sponsors=parse_sponsors(html),
        source_url=item.detail_url,
        actions=parse_actions(html, source_url=item.detail_url, session_year=session.start_date.year if session.start_date else None),
        versions=parse_versions(html),
        kind=classify_kind(text_for_kind),
    )


def parse_actions(
    html: str,
    *,
    source_url: str | None = None,
    session_year: int | None = None,
) -> list[BillAction]:
    tree = HTMLParser(html)
    year = session_year or datetime.now().year
    actions: list[BillAction] = []
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 4:
            continue
        date_text = _clean_text(cells[0].text())
        occurred_on = _parse_action_date(date_text, year=year)
        if occurred_on is None:
            continue
        chamber = _chamber_from_code(_clean_text(cells[1].text()))
        action_text = _clean_text(cells[3].text(separator=" "))
        if not action_text:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=chamber,
            action_text=action_text,
            normalized_status=match_first(action_text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_sponsors(html: str) -> list[Sponsor]:
    tree = HTMLParser(html)
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="members"], a[href*="smembers"]'):
        name = _clean_text(link.text(separator=" "))
        if not name:
            continue
        primary = "(primary)" in name.lower()
        name = re.sub(r"\s*\(primary\)\s*", "", name, flags=re.IGNORECASE).strip()
        if name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary" if primary or not sponsors else "cosponsor"))
    return sponsors


def parse_subjects(title: str | None) -> list[str]:
    if not title or ":" not in title:
        return []
    subject = _clean_text(title.split(":", 1)[0]).title()
    return [subject] if subject else []


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="ViewDocument.aspx"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(LEGIS_ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_clean_text(link.text(separator=" ")) or _label_from_url(url),
            source_url=url,
            format="pdf",
        ))
    return versions


def _final_disposition_url(session_code: str, chamber_code: str) -> str:
    return f"{LEGIS_ROOT}FinalDisposition.aspx?c={chamber_code}&sid={session_code}"


def _text_by_id(html: str, element_id: str) -> str | None:
    node = HTMLParser(html).css_first(f"#{element_id}")
    if node is None:
        return None
    return _clean_text(node.text(separator=" ")) or None


def _format_number(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"([A-Za-z]+)\s*(\d+)", _clean_text(value))
    if match is None:
        return _clean_text(value)
    return f"{match.group(1).upper()} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    if number.upper().startswith("HB"):
        return Chamber.LOWER
    if number.upper().startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_code(value: str) -> Chamber | None:
    if value.upper() == "H":
        return Chamber.LOWER
    if value.upper() == "S":
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "SB": 1}.get(prefix, 9)
    match = re.search(r"(\d+)", number)
    return (order, int(match.group(1)) if match else 0, number)


def _parse_action_date(value: str, *, year: int) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", text)
    if match is None:
        return None
    return date(year, int(match.group(1)), int(match.group(2)))


def _label_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
