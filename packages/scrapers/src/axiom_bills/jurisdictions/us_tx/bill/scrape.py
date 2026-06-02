"""Texas bill scraper.

Texas Legislature Online publishes current-session filing-date reports
with BillLookup links. BillLookup history pages contain title metadata
and action tables, while Text.aspx exposes official bill text versions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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

ROOT = "https://capitol.texas.gov"
REPORTS_URL = f"{ROOT}/Reports/BillsBy.aspx"


@dataclass(frozen=True)
class TexasSessionInfo:
    code: str
    display: str
    year: int
    name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class TexasIndexItem:
    number: str
    source_url: str
    roster_title: str = ""


class TexasScraper(BillScraper):
    jurisdiction = "us-tx"
    source_name = "capitol.texas.gov official Texas Legislature Online"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        reports_html = self.http.get(REPORTS_URL).text
        session_info = current_session_from_reports(reports_html)
        session = Session(
            name=session_info.name,
            start_date=session_info.start_date,
            end_date=session_info.end_date,
            is_current=session_info.start_date <= date.today() <= session_info.end_date,
        )
        bills: list[Bill] = []
        for item in self._index_items(session_info):
            if self.limit is not None and len(bills) >= self.limit:
                break
            history_html = self.http.get(item.source_url).text
            text_html = self.http.get(_text_url(item.source_url)).text
            bills.append(parse_bill(item, history_html=history_html, text_html=text_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _index_items(self, session_info: TexasSessionInfo) -> list[TexasIndexItem]:
        items: list[TexasIndexItem] = []
        seen: set[str] = set()
        for filing_date in _date_range(session_info.start_date, session_info.end_date):
            report_html = self.http.get(_filing_date_url(session_info.code, filing_date)).text
            for item in parse_filing_date_report(report_html):
                if item.number in seen:
                    continue
                seen.add(item.number)
                items.append(item)
                if self.limit is not None and len(items) >= self.limit:
                    return items
        return items


def current_session_from_reports(html: str) -> TexasSessionInfo:
    tree = HTMLParser(html)
    option = tree.css_first("#cboLegSess option[selected]")
    if option is None:
        option = tree.css_first("#cboLegSess option")
    code = _clean_text(option.attributes.get("value") if option is not None else "") or "892"
    display = _clean_text(option.text() if option is not None else "") or "89(2) - 2025"
    year_match = re.search(r"\b(20\d{2})\b", display)
    year = int(year_match.group(1)) if year_match else 2025
    header = _clean_text(_node_text(tree.css_first("#usrHeader_lblApplicationName")))
    name = f"{header}, {display}" if header else f"Texas Legislature {display}"
    start_date = date(year, 1, 1) if code.endswith("R") else date(year, 7, 1)
    end_date = date(year, 12, 31)
    if year == date.today().year:
        end_date = min(end_date, date.today())
    return TexasSessionInfo(
        code=code,
        display=display,
        year=year,
        name=name,
        start_date=start_date,
        end_date=end_date,
    )


def parse_filing_date_report(html: str) -> list[TexasIndexItem]:
    tree = HTMLParser(html)
    items: list[TexasIndexItem] = []
    for row in tree.css(".bill-search-results .row"):
        link = row.css_first("a[href*='BillLookup/History.aspx']")
        if link is None:
            continue
        number = _format_number(_clean_text(link.text()))
        if not number:
            continue
        items.append(TexasIndexItem(
            number=number,
            source_url=_canonical_history_url(link.attributes.get("href") or ""),
            roster_title=_caption_from_report_row(row),
        ))
    return items


def parse_bill(item: TexasIndexItem, *, history_html: str, text_html: str, session: Session) -> Bill:
    tree = HTMLParser(history_html)
    title = _clean_text(_node_text(tree.css_first("#lblCaptionText"))) or item.roster_title or item.number
    return Bill(
        jurisdiction=TexasScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=title,
        subjects=parse_subjects(tree),
        sponsors=parse_sponsors(tree),
        source_url=item.source_url,
        actions=parse_actions(tree, source_url=item.source_url),
        versions=parse_versions(HTMLParser(text_html)),
        kind=classify_kind(title),
    )


def parse_subjects(tree: HTMLParser) -> list[str]:
    node = tree.css_first("#lblSubjects")
    if node is None:
        return []
    subjects: list[str] = []
    seen: set[str] = set()
    for text in node.text(separator="\n").splitlines():
        subject = _clean_text(text)
        if not subject or subject in seen:
            continue
        seen.add(subject)
        subjects.append(subject)
    return subjects


def parse_sponsors(tree: HTMLParser) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for name in _split_names(_node_text(tree.css_first("#lblAuthor"))):
        if name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary" if not sponsors else "cosponsor"))
    sponsor_node = tree.css_first("#lblSponsor")
    for name in _split_names(_node_text(sponsor_node)):
        if name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="sponsor"))
    return sponsors


def parse_actions(tree: HTMLParser, *, source_url: str | None = None) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in tree.css("table.actions tr"):
        cells = row.css("td")
        if len(cells) < 4:
            continue
        chamber = _chamber_from_code(_clean_text(cells[0].text()))
        action_text = _clean_text(cells[1].text())
        comment = _clean_text(cells[2].text())
        occurred_at = _parse_date(_clean_text(cells[3].text()))
        if occurred_at is None or not action_text:
            continue
        if comment:
            action_text = f"{action_text} ({comment})"
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=chamber,
            action_text=action_text,
            normalized_status=match_first(action_text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for row in tree.css("table tr"):
        version_label = _clean_text(_node_text(row.css_first("td[data-label='Version']")))
        bill_cell = row.css_first("td[data-label='Bill']")
        if bill_cell is None:
            continue
        for link in bill_cell.css("a[href*='/billtext/'][href]"):
            href = link.attributes.get("href") or ""
            source_url = urljoin(ROOT, href)
            if source_url in seen:
                continue
            seen.add(source_url)
            versions.append(BillVersion(
                label=version_label or _clean_text(link.attributes.get("aria-label")) or "Bill text",
                source_url=source_url,
                format=_format_from_url(source_url),
            ))
    return versions


def _caption_from_report_row(row: Node) -> str:
    labels = row.css(".bill-search-result-label")
    for index, label in enumerate(labels):
        if "Caption" not in _clean_text(label.text()):
            continue
        next_data = label.next
        while next_data is not None:
            if "bill-search-result-data" in (next_data.attributes.get("class") or ""):
                return _clean_text(next_data.text())
            next_data = next_data.next
    return ""


def _canonical_history_url(href: str) -> str:
    query = parse_qs(urlsplit(href).query)
    leg_sess = (query.get("LegSess") or [""])[0]
    bill = (query.get("Bill") or [""])[0]
    if leg_sess and bill:
        return f"{ROOT}/BillLookup/History.aspx?LegSess={leg_sess}&Bill={bill.upper()}"
    return urljoin(ROOT, href)


def _text_url(history_url: str) -> str:
    query = parse_qs(urlsplit(history_url).query)
    leg_sess = (query.get("LegSess") or [""])[0]
    bill = (query.get("Bill") or [""])[0]
    return f"{ROOT}/BillLookup/Text.aspx?LegSess={leg_sess}&Bill={bill.upper()}"


def _filing_date_url(session_code: str, filing_date: date) -> str:
    return f"{ROOT}/Reports/Report.aspx?ID=filingDate&LegSess={session_code}&Code={filing_date.isoformat()}"


def _date_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _format_number(text: str) -> str:
    match = re.search(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)\b", text.upper())
    if match is None:
        return ""
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    prefix = number.split()[0].upper()
    if prefix in {"HJR", "SJR", "HCR", "SCR"}:
        return Chamber.JOINT
    if prefix.startswith("H"):
        return Chamber.LOWER
    if prefix.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_code(code: str) -> Chamber | None:
    if code == "H":
        return Chamber.LOWER
    if code == "S":
        return Chamber.UPPER
    if code == "E":
        return Chamber.EXECUTIVE
    return None


def _parse_date(text: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _split_names(text: str) -> list[str]:
    return [_clean_text(part) for part in text.split("|") if _clean_text(part)]


def _format_from_url(url: str) -> str:
    suffix = url.rsplit(".", 1)[-1].lower()
    return "docx" if suffix == "docx" else suffix


def _number_sort_key(number: str) -> tuple[int, int]:
    prefix, _, digits = number.partition(" ")
    order = {"HB": 0, "SB": 1, "HJR": 2, "SJR": 3, "HCR": 4, "SCR": 5, "HR": 6, "SR": 7}.get(prefix.upper(), 9)
    return order, int(digits) if digits.isdigit() else 0


def _node_text(node: Node | None) -> str:
    return node.text(separator=" ") if node is not None else ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
