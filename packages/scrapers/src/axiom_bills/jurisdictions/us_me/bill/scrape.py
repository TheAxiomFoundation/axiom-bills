"""Maine bill scraper.

Maine publishes official LD directory pages under bills/billdirectory_ps.asp
and per-bill details under bills/display_ps.asp. LawMakerWeb pages linked
from each detail page provide chamber actions, sponsors, and subjects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

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

ROOT = "https://legislature.maine.gov"
LAWMAKER_ROOT = f"{ROOT}/LawMakerWeb/"
DEFAULT_LEGISLATURE = 132
DEFAULT_SESSION_ID = 16
DIRECTORY_PAGE_SIZE = 200


@dataclass(frozen=True)
class MaineListItem:
    number: str
    paper: str
    title: str
    detail_url: str


class MaineScraper(BillScraper):
    jurisdiction = "us-me"
    source_name = "legislature.maine.gov official bill pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        legislature: int = DEFAULT_LEGISLATURE,
        session_id: int = DEFAULT_SESSION_ID,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.legislature = legislature
        self.session_id = session_id

    def scrape(self) -> ScrapeResult:
        session = session_for_legislature(self.legislature)
        items = self._listing_items()
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            summary_url = _summary_url_for_detail(
                detail_html,
                paper=item.paper,
                session_id=self.session_id,
            )
            summary_html = self.http.get(summary_url).text
            linked_urls = _lawmaker_links(summary_html)
            actions_html = self.http.get(linked_urls.get("Actions", "") or _lawmaker_url("dockets", summary_url)).text
            sponsors_html = self.http.get(linked_urls.get("Sponsors", "") or _lawmaker_url("sponsors", summary_url)).text
            subjects_html = self.http.get(linked_urls.get("Subjects", "") or _lawmaker_url("subjects", summary_url)).text
            bills.append(parse_bill(
                item,
                detail_html,
                actions_html=actions_html,
                sponsors_html=sponsors_html,
                subjects_html=subjects_html,
                session=session,
            ))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _listing_items(self) -> list[MaineListItem]:
        items: list[MaineListItem] = []
        seen: set[str] = set()
        ld_from = 1
        while True:
            html = self.http.get(_directory_url(self.legislature, ld_from)).text
            page_items = parse_listing(html)
            if not page_items:
                break
            for item in page_items:
                if item.number in seen:
                    continue
                seen.add(item.number)
                items.append(item)
            if self.limit is not None and len(items) >= self.limit:
                break
            if len(page_items) < DIRECTORY_PAGE_SIZE:
                break
            ld_from += DIRECTORY_PAGE_SIZE
        items.sort(key=lambda item: _number_sort_key(item.number))
        return items


def session_for_legislature(legislature: int) -> Session:
    start = 2025 + (legislature - DEFAULT_LEGISLATURE) * 2
    end = start + 1
    return Session(
        name=f"{_ordinal(legislature)} Maine Legislature ({start}-{end})",
        start_date=date(start, 1, 1),
        end_date=date(end, 12, 31),
        is_current=start <= datetime.now().year <= end,
    )


def parse_listing(html: str) -> list[MaineListItem]:
    tree = HTMLParser(html)
    rows = tree.css("tr")
    items: list[MaineListItem] = []
    for index, row in enumerate(rows):
        cells = row.css("td,th")
        if len(cells) < 3:
            continue
        heading = _clean_text(cells[1].text(separator=" "))
        match = re.search(r"\bLD\s+(\d+),\s+([HS]P)\s*0*(\d+)", heading, re.IGNORECASE)
        if match is None:
            continue
        links_row = rows[index + 1] if index + 1 < len(rows) else row
        detail_link = _detail_link(links_row) or _detail_link(row)
        if detail_link is None:
            continue
        items.append(MaineListItem(
            number=f"LD {int(match.group(1))}",
            paper=f"{match.group(2).upper()}{int(match.group(3)):04d}",
            title=_clean_text(cells[2].text(separator=" ")),
            detail_url=detail_link,
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(
    item: MaineListItem,
    detail_html: str,
    *,
    actions_html: str,
    sponsors_html: str,
    subjects_html: str,
    session: Session,
) -> Bill:
    title = _title(detail_html) or item.title or item.number
    actions = parse_actions(actions_html)
    final_action = _final_disposition_action(detail_html, source_url=item.detail_url)
    if final_action is not None:
        actions.append(final_action)
        actions.sort(key=lambda action: action.occurred_at)
    text_for_kind = " ".join(part for part in (title, _final_disposition_text(detail_html)) if part)
    return Bill(
        jurisdiction=MaineScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_paper(item.paper),
        number=item.number,
        title=title,
        summary=_final_disposition_text(detail_html) or title,
        subjects=parse_subjects(subjects_html),
        sponsors=parse_sponsors(sponsors_html),
        source_url=item.detail_url,
        actions=actions,
        versions=parse_versions(detail_html),
        kind=classify_kind(text_for_kind),
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
        chamber = _chamber_from_text(_clean_text(cells[1].text()))
        text = _clean_text(cells[2].text(separator=" "))
        if not text:
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
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 2:
            continue
        label = _clean_text(cells[0].text()).lower()
        if label not in {"sponsored by:", "cosponsored by:"}:
            continue
        role = "primary" if label.startswith("sponsored") else "cosponsor"
        for name in _sponsor_names(cells[1].html or cells[1].text(separator=" ")):
            if name in seen:
                continue
            seen.add(name)
            sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def parse_subjects(html: str) -> list[str]:
    tree = HTMLParser(html)
    subjects: list[str] = []
    seen: set[str] = set()
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 4:
            continue
        values = [_clean_text(cell.text(separator=" ")).title() for cell in cells[1:4]]
        if values == ["Major Subject", "Minor Subject", "Detail Subject"]:
            continue
        for value in values:
            if value and value not in seen:
                seen.add(value)
                subjects.append(value)
    return subjects


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css('a[href*="getPDF.asp"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_version_label(link.text(separator=" "), url),
            source_url=url,
            format="pdf",
        ))
    return versions


def _directory_url(legislature: int, ld_from: int) -> str:
    return f"{ROOT}/bills/billdirectory_ps.asp?ldFrom={ld_from}&snum={legislature}"


def _detail_link(row) -> str | None:
    for link in row.css('a[href*="display_ps.asp"]'):
        if _clean_text(link.text(separator=" ")).lower().startswith("bill"):
            return urljoin(f"{ROOT}/bills/", link.attributes.get("href") or "")
    return None


def _summary_url_for_detail(html: str, *, paper: str, session_id: int) -> str:
    tree = HTMLParser(html)
    for link in tree.css('a[href*="summary.asp"]'):
        href = link.attributes.get("href")
        if href:
            return urljoin(ROOT, href)
    return f"{LAWMAKER_ROOT}summary.asp?paper={paper}&SessionID={session_id}"


def _lawmaker_links(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    urls: dict[str, str] = {}
    for link in tree.css("a[href]"):
        text = _clean_text(link.text(separator=" "))
        if text not in {"Actions", "Sponsors", "Subjects"}:
            continue
        urls[text] = urljoin(LAWMAKER_ROOT, link.attributes.get("href") or "")
    return urls


def _lawmaker_url(kind: str, summary_url: str) -> str:
    qs = parse_qs(urlsplit(summary_url).query)
    page_id = (qs.get("ID") or [""])[0]
    return f"{LAWMAKER_ROOT}{kind}.asp?ID={page_id}" if page_id else summary_url


def _title(html: str) -> str | None:
    node = HTMLParser(html).css_first("h2")
    return _clean_text(node.text(separator=" ")) if node else None


def _final_disposition_text(html: str) -> str | None:
    tree = HTMLParser(html)
    for paragraph in tree.css("p"):
        text = _clean_text(paragraph.text(separator=" "))
        if text.startswith("Final Disposition"):
            return text
    return None


def _final_disposition_action(html: str, *, source_url: str) -> BillAction | None:
    text = _final_disposition_text(html)
    if not text:
        return None
    matches = list(re.finditer(r"\b[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\b", text))
    if not matches:
        return None
    occurred_on = _parse_date(matches[-1].group(0))
    if occurred_on is None:
        return None
    return BillAction(
        occurred_at=datetime.combine(occurred_on, datetime.min.time()),
        chamber=None,
        action_text=text,
        normalized_status=match_first(text, PATTERNS),
        source_url=source_url,
    )


def _sponsor_names(fragment: str) -> list[str]:
    parts = re.split(r"<br\s*/?>", fragment, flags=re.IGNORECASE)
    names: list[str] = []
    for part in parts:
        text = _clean_text(HTMLParser(part).text(separator=" "))
        text = re.sub(r"^(Representative|Senator|Speaker|President)\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+of\s+.+$", "", text)
        text = text.title()
        if text:
            names.append(text)
    return names


def _version_label(text: str, url: str) -> str:
    query = parse_qs(urlsplit(url).query)
    item = (query.get("item") or [""])[0]
    cleaned = _clean_text(text)
    return f"{cleaned} {item}".strip() if item and cleaned == "Printed Document PDF" else cleaned or _label_from_url(url)


def _chamber_for_paper(paper: str) -> Chamber:
    if paper.upper().startswith("HP"):
        return Chamber.LOWER
    if paper.upper().startswith("SP"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(text: str) -> Chamber | None:
    if text.lower() == "house":
        return Chamber.LOWER
    if text.lower() == "senate":
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[int, str]:
    match = re.search(r"\d+", number)
    return (int(match.group(0)) if match else 0, number)


def _parse_date(value: str | None) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _ordinal(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _label_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

