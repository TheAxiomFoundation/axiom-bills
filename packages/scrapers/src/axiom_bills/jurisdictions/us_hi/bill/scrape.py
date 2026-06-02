"""Hawaii bill scraper.

Hawaii publishes official measure reports and per-measure status pages under
capitol.hawaii.gov. The same official content is available from
data.capitol.hawaii.gov without the public site's Cloudflare interstitial.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

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

ROOT = "https://data.capitol.hawaii.gov"
PUBLIC_ROOT = "https://www.capitol.hawaii.gov"
DEFAULT_YEAR = 2026
DEFAULT_MEASURE_TYPES = ("hb", "sb")


@dataclass(frozen=True)
class HawaiiReportItem:
    number: str
    detail_url: str
    pdf_url: str | None
    report_title: str | None
    title: str
    summary: str | None
    sponsors: str | None
    current_referral: str | None
    current_status_date: str | None
    current_status_text: str | None


class HawaiiScraper(BillScraper):
    jurisdiction = "us-hi"
    source_name = "capitol.hawaii.gov official measure reports and status pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        year: int = DEFAULT_YEAR,
        measure_types: tuple[str, ...] = DEFAULT_MEASURE_TYPES,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.year = year
        self.measure_types = measure_types

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        items = self._report_items()
        if self.limit is not None:
            items = items[:self.limit]
        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            bills.append(parse_bill(item, detail_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _report_items(self) -> list[HawaiiReportItem]:
        by_number: dict[str, HawaiiReportItem] = {}
        for measure_type in self.measure_types:
            html = self.http.get(_report_url(self.year, measure_type)).text
            for item in parse_report(html):
                by_number.setdefault(item.number, item)
        return sorted(by_number.values(), key=lambda item: _number_sort_key(item.number))


def session_for_year(year: int) -> Session:
    start = year - 1
    return Session(
        name=f"{start}-{year} Hawaii Regular Session",
        start_date=date(start, 1, 1),
        end_date=date(year, 12, 31),
        is_current=start <= datetime.now().year <= year,
    )


def parse_report(html: str) -> list[HawaiiReportItem]:
    tree = HTMLParser(html)
    items: list[HawaiiReportItem] = []
    for row in tree.css("#GridViewReports tr"):
        cells = row.css("td")
        if len(cells) < 5:
            continue
        detail_link = _first_link(cells[1])
        if detail_link is None:
            continue
        number = _clean_text(detail_link.text())
        href = detail_link.attributes.get("href")
        if not number or not href:
            continue
        status_date, status_text = _parse_current_status(cells[2])
        items.append(HawaiiReportItem(
            number=number,
            detail_url=_detail_url(href),
            pdf_url=_absolute_url(_href(_first_link(cells[0]))),
            report_title=_text_by_id(cells[1], "GridViewReports_Label1_"),
            title=_text_by_id(cells[1], "GridViewReports_Label7_") or number,
            summary=_text_by_id(cells[1], "GridViewReports_Label2_"),
            sponsors=_clean_text(cells[3].text()) or None,
            current_referral=_clean_text(cells[4].text()) or None,
            current_status_date=status_date,
            current_status_text=status_text,
        ))
    return items


def parse_bill(item: HawaiiReportItem, html: str, *, session: Session) -> Bill:
    fields = parse_measure_fields(html)
    number = _measure_number(html) or item.number
    title = fields.get("Measure Title") or item.title or number
    summary = fields.get("Description") or item.summary or title
    report_title = fields.get("Report Title") or item.report_title
    return Bill(
        jurisdiction=HawaiiScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=summary,
        subjects=[report_title] if report_title else [],
        sponsors=parse_sponsors(fields.get("Introducer(s)") or item.sponsors),
        source_url=item.detail_url,
        actions=parse_actions(html, fallback_item=item),
        versions=parse_versions(html, fallback_pdf_url=item.pdf_url),
        kind=classify_kind(" ".join(part for part in (title, report_title, summary) if part)),
    )


def parse_measure_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    fields: dict[str, str] = {}
    for row in tree.css("#measure-info tr"):
        cells = row.css("th,td")
        if len(cells) < 2:
            continue
        label = _clean_text(cells[0].text()).rstrip(":")
        value = _clean_text(cells[1].text())
        if label and value and value != "None":
            fields[label] = value
    return fields


def parse_actions(html: str, *, fallback_item: HawaiiReportItem | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("#MainContent_GridViewStatus tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        occurred_at = _parse_date(_clean_text(cells[0].text()))
        chamber = _chamber(_clean_text(cells[1].text()))
        text = _clean_text(cells[2].text())
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    if not actions and fallback_item and fallback_item.current_status_date and fallback_item.current_status_text:
        occurred_at = _parse_date(fallback_item.current_status_date)
        if occurred_at is not None:
            actions.append(BillAction(
                occurred_at=occurred_at,
                chamber=_chamber_for_number(fallback_item.number),
                action_text=fallback_item.current_status_text,
                normalized_status=match_first(fallback_item.current_status_text, PATTERNS),
            ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(html: str, *, fallback_pdf_url: str | None = None) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()

    def add(label: str, href: str | None) -> None:
        source_url = _absolute_url(href)
        if not source_url or source_url in seen:
            return
        lower = source_url.lower()
        if "/bills/" not in lower or not lower.endswith((".pdf", ".htm", ".html")):
            return
        seen.add(source_url)
        versions.append(BillVersion(label=_clean_text(label) or "measure", source_url=source_url, format=_format_for_url(source_url)))

    for link in tree.css('a[href*="/bills/"]'):
        add(_clean_text(link.text()) or _label_from_url(link.attributes.get("href")), link.attributes.get("href"))
    add("current pdf", fallback_pdf_url)
    return versions


def parse_sponsors(value: str | None) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for name in re.split(r",|;", value or ""):
        cleaned = _clean_text(name)
        if cleaned:
            sponsors.append(Sponsor(name=cleaned, role="primary"))
    return sponsors


def _report_url(year: int, measure_type: str) -> str:
    query = urlencode({
        'year': year,
        'report': 'deadline',
        'active': 'false',
        'rpt_type': '',
        'measuretype': measure_type,
        'title': f'{year - 1} and {year} {measure_type.upper()} measures',
    })
    return f"{ROOT}/advreports/advreport.aspx?{query}"


def _detail_url(href: str) -> str:
    parsed = urlsplit(href)
    query = parse_qs(parsed.query)
    detail_query = urlencode({
        'billtype': (query.get('billtype') or [''])[0],
        'billnumber': (query.get('billnumber') or [''])[0],
        'year': (query.get('year') or [DEFAULT_YEAR])[0],
    })
    return f"{ROOT}/session/measure_indiv.aspx?{detail_query}"


def _absolute_url(href: str | None) -> str:
    if not href:
        return ""
    return urljoin(ROOT, href.replace(PUBLIC_ROOT, ROOT))


def _first_link(node: Any) -> Any | None:
    links = node.css("a")
    return links[0] if links else None


def _href(node: Any | None) -> str | None:
    return node.attributes.get("href") if node is not None else None


def _text_by_id(node: Any, prefix: str) -> str | None:
    for child in node.css("[id]"):
        if child.attributes.get("id", "").startswith(prefix):
            text = _clean_text(child.text())
            if text:
                return text
    return None


def _parse_current_status(node: Any) -> tuple[str | None, str | None]:
    text = _clean_text(node.text())
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(.+)", text)
    if match:
        return match.group(1), match.group(2).strip()
    return None, text or None


def _measure_number(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first(".measure-header")
    text = _clean_text(node.text()) if node is not None else ""
    return text or None


def _chamber_for_number(number: str) -> Chamber:
    upper = number.upper()
    if upper.startswith("H"):
        return Chamber.LOWER
    if upper.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber(value: str) -> Chamber | None:
    upper = value.upper()
    if upper == "H":
        return Chamber.LOWER
    if upper == "S":
        return Chamber.UPPER
    if upper == "D":
        return Chamber.JOINT
    return None


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _format_for_url(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith((".htm", ".html")):
        return "html"
    return "txt"


def _label_from_url(url: str | None) -> str:
    if not url:
        return "measure"
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").strip()


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Z]+)\s*(\d+)(.*)", number.upper())
    if not match:
        return (number, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3).strip())


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()
