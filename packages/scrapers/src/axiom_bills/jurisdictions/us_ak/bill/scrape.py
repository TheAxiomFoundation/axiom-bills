"""Alaska bill scraper.

Alaska publishes official bill lists and detail pages through BASIS. The
list page provides core metadata, while each detail page includes the
official action history and bill text PDF versions.
"""
from __future__ import annotations

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

ROOT = "https://www.akleg.gov"


@dataclass(frozen=True)
class BillListItem:
    number: str
    title: str
    sponsors: list[str]
    status: str
    status_date: date | None
    detail_url: str


class AlaskaScraper(BillScraper):
    jurisdiction = "us-ak"
    source_name = "akleg.gov BASIS"
    min_interval_per_host = 0.5

    def __init__(self, *, session_id: int | None = None, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_id = session_id or session_id_for_year(year or datetime.now().year)

    def scrape(self) -> ScrapeResult:
        session = session_for_id(self.session_id)
        items = parse_bill_list(self.http.get(_range_url(self.session_id)).text)
        if self.limit is not None:
            items = items[:self.limit]
        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            bill = parse_bill_page(detail_html, item=item, session=session)
            if bill is not None:
                bills.append(bill)
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_id_for_year(year: int) -> int:
    start_year = year if year % 2 == 1 else year - 1
    return 34 + ((start_year - 2025) // 2)


def session_for_id(session_id: int) -> Session:
    start_year = 2025 + ((session_id - 34) * 2)
    return Session(
        name=f"{session_id}th Alaska Legislature ({start_year}-{start_year + 1})",
        start_date=date(start_year, 1, 1),
        end_date=date(start_year + 1, 12, 31),
        is_current=start_year <= datetime.now().year <= start_year + 1,
    )


def parse_bill_list(html: str) -> list[BillListItem]:
    tree = HTMLParser(html)
    items: list[BillListItem] = []
    for row in tree.css("tr"):
        bill_cell = row.css_first("td.billRoot")
        cells = row.css("td")
        if bill_cell is None or len(cells) < 6:
            continue
        link = bill_cell.css_first("a")
        href = link.attributes.get("href") if link is not None else None
        number = _bill_number(bill_cell.text())
        title = _clean_text(cells[1].text()) or ""
        if not href or not number or not title or title == "NOT INTRODUCED":
            continue
        items.append(BillListItem(
            number=number,
            title=title,
            sponsors=_sponsor_names(cells[2]),
            status=_clean_text(cells[4].text()) or "",
            status_date=_parse_date(_clean_text(cells[5].text())),
            detail_url=urljoin(ROOT, href),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill_page(html: str, *, item: BillListItem, session: Session) -> Bill | None:
    tree = HTMLParser(html)
    title = _strip_quotes(_info_value(tree, "Title")) or item.title
    number = _bill_number(_info_value(tree, "Bill")) or item.number
    if not number:
        return None
    sponsors = _detail_sponsors(tree) or [Sponsor(name=name, role="sponsor") for name in item.sponsors]
    return Bill(
        jurisdiction=AlaskaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=_info_value(tree, "Short Title") or item.title,
        subjects=_subjects(tree),
        sponsors=sponsors,
        source_url=item.detail_url,
        actions=_actions(tree),
        versions=_versions(tree),
        kind=classify_kind(title),
    )


def _detail_sponsors(tree: HTMLParser) -> list[Sponsor]:
    raw = _info_value(tree, "Sponsor(S)") or ""
    sponsors: list[Sponsor] = []
    for name in raw.replace("REPRESENTATIVES", "").replace("SENATORS", ",").split(","):
        cleaned = _clean_text(name)
        if cleaned:
            sponsors.append(Sponsor(name=cleaned.title(), role="sponsor"))
    return sponsors


def _actions(tree: HTMLParser) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in tree.css("tr.floorAction, tr.committeeAction"):
        time_node = row.css_first("time")
        text_node = row.css_first('span[data-label="Text"]')
        text = _clean_text(text_node.text()) if text_node is not None else None
        occurred_at = _parse_action_date(time_node.attributes.get("datetime") if time_node else None)
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_action(text),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for row in tree.css("#tab1_4 tbody tr"):
        if "Merrors" in (row.attributes.get("class") or ""):
            continue
        pdf_link = row.css_first("a.pdf")
        if pdf_link is None:
            continue
        href = pdf_link.attributes.get("href")
        if not href or href in seen:
            continue
        seen.add(href)
        cells = row.css("td")
        label_parts = [
            _clean_text(cells[0].text()) if len(cells) > 0 else None,
            _clean_text(cells[1].text()) if len(cells) > 1 else None,
        ]
        versions.append(BillVersion(
            label=" - ".join(part for part in label_parts if part) or "Bill Text",
            source_url=href,
            format="pdf",
        ))
    return versions


def _subjects(tree: HTMLParser) -> list[str]:
    subjects: list[str] = []
    for link in tree.css("ul.list-links a"):
        href = link.attributes.get("href") or ""
        text = _clean_text(link.text())
        if "subject=" in href and text:
            subjects.append(text)
    return subjects


def _info_value(tree: HTMLParser, label: str) -> str | None:
    target = label.lower()
    for item in tree.css("ul.information li"):
        span = item.css_first("span")
        strong = item.css_first("strong")
        if span is None or strong is None:
            continue
        label_text = _clean_text(span.text())
        if label_text and label_text.lower() == target:
            return _clean_text(strong.text())
    return None


def _sponsor_names(cell: Node) -> list[str]:
    names: list[str] = []
    for part in cell.text(separator="|").split("|"):
        cleaned = _clean_text(part)
        if cleaned:
            names.append(cleaned.title())
    return names


def _bill_number(raw: str | None) -> str | None:
    text = _clean_text(raw)
    if not text:
        return None
    prefix = "".join(ch for ch in text if ch.isalpha()).upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    return f"{prefix} {int(digits)}" if prefix and digits else text


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _chamber_from_action(text: str) -> Chamber | None:
    if text.startswith("(S)"):
        return Chamber.UPPER
    if text.startswith("(H)"):
        return Chamber.LOWER
    return None


def _parse_action_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _range_url(session_id: int) -> str:
    return f"{ROOT}/basis/Bill/Range/{session_id}?bill1=&bill2="


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _strip_quotes(raw: str | None) -> str | None:
    text = _clean_text(raw)
    return text.strip('"') if text else None


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
