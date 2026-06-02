"""Tennessee bill scraper.

Tennessee publishes current-session roster pages by bill-number range
and server-rendered BillInfo detail pages with sponsors, text links,
caption, summary, and history tables.
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

ROOT = "https://wapp.capitol.tn.gov"
INDEX_URL = f"{ROOT}/apps/Indexes/BillsByIndex"
GENERAL_ASSEMBLY = "114"
SESSION_LABEL = "2025-2026"


@dataclass(frozen=True)
class TennesseeIndexItem:
    compact_number: str
    number: str
    source_url: str
    roster_title: str = ""


class TennesseeScraper(BillScraper):
    jurisdiction = "us-tn"
    source_name = "wapp.capitol.tn.gov official Tennessee General Assembly"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session = Session(
            name=f"{SESSION_LABEL} Tennessee {GENERAL_ASSEMBLY}th General Assembly",
            start_date=date(2025, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=datetime.now().year in {2025, 2026},
        )
        bills: list[Bill] = []
        for item in self._index_items():
            if self.limit is not None and len(bills) >= self.limit:
                break
            html = self.http.get(item.source_url).text
            bills.append(parse_bill(item, detail_html=html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _index_items(self) -> list[TennesseeIndexItem]:
        index_html = self.http.get(INDEX_URL).text
        items: list[TennesseeIndexItem] = []
        seen: set[str] = set()
        for range_url in parse_range_urls(index_html):
            range_html = self.http.get(range_url).text
            for item in parse_bill_index(range_html):
                if item.compact_number in seen:
                    continue
                seen.add(item.compact_number)
                items.append(item)
                if self.limit is not None and len(items) >= self.limit:
                    return items
        return items


def parse_range_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    urls: list[str] = []
    seen: set[str] = set()
    for link in tree.css("a[href*='BillIndex?startNum='][href*='ga=114']"):
        href = link.attributes.get("href") or ""
        url = urljoin(ROOT, href)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_bill_index(html: str) -> list[TennesseeIndexItem]:
    tree = HTMLParser(html)
    items: list[TennesseeIndexItem] = []
    for link in tree.css("a[href*='BillInfo/Default'][href*='BillNumber=']"):
        href = link.attributes.get("href") or ""
        compact = _compact_number_from_url(href) or _clean_text(link.text())
        number = _format_number(compact)
        if not number:
            continue
        title = _title_from_index_link(link)
        items.append(TennesseeIndexItem(
            compact_number=number.replace(" ", ""),
            number=number,
            source_url=_canonical_bill_url(href),
            roster_title=title,
        ))
    return items


def parse_bill(item: TennesseeIndexItem, *, detail_html: str, session: Session) -> Bill:
    tree = HTMLParser(detail_html)
    title = _title_from_detail(tree) or item.roster_title or item.number
    summary = _summary_from_detail(tree) or title
    text_for_kind = " ".join(part for part in (title, summary[:500]) if part)
    return Bill(
        jurisdiction=TennesseeScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=summary,
        subjects=_subjects_from_title(title),
        sponsors=parse_sponsors(tree),
        source_url=item.source_url,
        actions=parse_actions(tree, source_url=item.source_url),
        versions=parse_versions(tree),
        kind=classify_kind(text_for_kind),
    )


def parse_sponsors(tree: HTMLParser) -> list[Sponsor]:
    bill_info = tree.css_first("#udpBillInfo")
    heading = bill_info.css_first("h2") if bill_info is not None else None
    if heading is None:
        return []
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for link in heading.css("a[href*='LegislatorInfo/Member']"):
        name = _sponsor_name(link.text())
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(
            name=name,
            role="primary" if not sponsors else "cosponsor",
            district=_district_from_member_url(link.attributes.get("href") or ""),
        ))
    coprime = heading.css_first("#divCoPrimeSponsors")
    if coprime is not None:
        for name in _sponsor_names_from_text(coprime.text()):
            if name in seen:
                continue
            seen.add(name)
            sponsors.append(Sponsor(name=name, role="cosponsor"))
    return sponsors


def parse_actions(tree: HTMLParser, *, source_url: str | None = None) -> list[BillAction]:
    table = tree.css_first("#gvBillActionHistory")
    if table is None:
        return []
    actions: list[BillAction] = []
    for row in table.css("tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        text = _clean_text(cells[0].text())
        occurred_at = _parse_date(_clean_text(cells[1].text()))
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_row(row),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css("a[href*='/Bills/114/'][href$='.pdf'], a[href*='/Bills/114/'][href$='.PDF']"):
        href = link.attributes.get("href") or ""
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        label = _clean_text(link.text()) or _version_label_from_url(source_url)
        versions.append(BillVersion(label=label, source_url=source_url, format="pdf"))
    return versions


def _title_from_detail(tree: HTMLParser) -> str:
    abstract = _clean_text(_node_text(tree.css_first(".abstract-container")))
    if abstract:
        return abstract
    return _clean_text(_node_text(tree.css_first("#divCaptionText")))


def _summary_from_detail(tree: HTMLParser) -> str:
    summary = _clean_text(_node_text(tree.css_first("#tabpanel-summary")))
    return summary


def _subjects_from_title(title: str) -> list[str]:
    subject = title.split(" - ", 1)[0].strip()
    return [subject] if subject and subject != title else []


def _title_from_index_link(link: Node) -> str:
    title = _clean_text(link.attributes.get("title"))
    match = re.search(r"\s+-\s+(.+)$", title)
    return match.group(1) if match else ""


def _compact_number_from_url(href: str) -> str:
    query = parse_qs(urlsplit(href).query)
    values = query.get("BillNumber") or query.get("billnumber")
    return values[0] if values else ""


def _canonical_bill_url(href: str) -> str:
    compact = _compact_number_from_url(href)
    if not compact:
        return urljoin(ROOT, href)
    return f"{ROOT}/apps/BillInfo/Default?BillNumber={compact.upper()}&ga={GENERAL_ASSEMBLY}"


def _format_number(text: str) -> str:
    match = re.search(r"\b(HB|SB|HJR|SJR|HR|SR)\s*0*(\d+)\b", text.upper())
    if match is None:
        return ""
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    prefix = number.split()[0].upper()
    if prefix in {"HJR", "SJR"}:
        return Chamber.JOINT
    if prefix.startswith("H"):
        return Chamber.LOWER
    if prefix.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_row(row: Node) -> Chamber | None:
    class_name = (row.attributes.get("class") or "").lower()
    if "house" in class_name:
        return Chamber.LOWER
    if "senate" in class_name:
        return Chamber.UPPER
    return None


def _parse_date(text: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _sponsor_name(text: str) -> str:
    return _clean_text(text).lstrip("*").strip()


def _sponsor_names_from_text(text: str) -> list[str]:
    return [_sponsor_name(part) for part in text.split(",") if _sponsor_name(part)]


def _district_from_member_url(href: str) -> str | None:
    query = parse_qs(urlsplit(href).query)
    district = (query.get("district") or [""])[0].strip()
    return district or None


def _version_label_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1] or "Bill text"


def _number_sort_key(number: str) -> tuple[int, int]:
    prefix, _, digits = number.partition(" ")
    order = {"HB": 0, "SB": 1, "HJR": 2, "SJR": 3, "HR": 4, "SR": 5}.get(prefix.upper(), 9)
    return order, int(digits) if digits.isdigit() else 0


def _node_text(node: Node | None) -> str:
    return node.text(separator=" ") if node is not None else ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
