"""Connecticut bill scraper.

Connecticut publishes official bill status pages under cga.ct.gov. Each page
contains bill metadata, document links, and a dated Bill History table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlencode, urljoin

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

ROOT = "https://www.cga.ct.gov"
DEFAULT_YEAR = 2026
BILL_RANGES = {
    "HB": ((1, 999), (5001, 7500)),
    "SB": ((1, 1500),),
}


@dataclass(frozen=True)
class ConnecticutBillPage:
    query_number: str
    display_number: str
    html: str


class ConnecticutScraper(BillScraper):
    jurisdiction = "us-ct"
    source_name = "cga.ct.gov official bill status pages"
    min_interval_per_host = 0.2
    verify_tls = False

    def __init__(self, *, session_year: int = DEFAULT_YEAR, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_year = session_year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.session_year)
        bills: list[Bill] = []
        for query_number, html in self._bill_pages():
            page = parse_page(query_number, html)
            if page is None:
                continue
            bills.append(parse_bill(page, session=session))
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _bill_pages(self):
        miss_limit = 150 if self.limit is None else 25
        for prefix, ranges in BILL_RANGES.items():
            for start, stop in ranges:
                misses = 0
                number = start
                while number <= stop and misses < miss_limit:
                    query_number = query_number_for(prefix, number)
                    html = self.http.get(_status_url(query_number, self.session_year)).text
                    if _is_missing_bill(html):
                        misses += 1
                    else:
                        misses = 0
                        yield query_number, html
                    number += 1


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year} Connecticut Regular Session",
        start_date=date(year, 2, 1),
        end_date=date(year, 12, 31),
        is_current=datetime.now().year == year,
    )


def parse_page(query_number: str, html: str) -> ConnecticutBillPage | None:
    if _is_missing_bill(html):
        return None
    tree = HTMLParser(html)
    header = _clean_text((tree.css_first("h3") or tree.css_first("title")).text() if tree.css_first("h3") or tree.css_first("title") else None)
    display_number = _display_number_from_header(header) or display_number_for(query_number)
    return ConnecticutBillPage(query_number=query_number, display_number=display_number, html=html)


def parse_bill(page: ConnecticutBillPage, *, session: Session) -> Bill:
    tree = HTMLParser(page.html)
    title = _clean_text(tree.css_first("h4").text() if tree.css_first("h4") else None) or page.display_number
    summary = _clean_text(tree.css_first("p.text-justify").text() if tree.css_first("p.text-justify") else None)
    source_url = _status_url(page.query_number, int(session.name[:4]))
    actions = parse_actions(page.html, source_url=source_url)
    return Bill(
        jurisdiction=ConnecticutScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(page.display_number),
        number=page.display_number,
        title=title,
        summary=summary or title,
        subjects=[title] if title else [],
        sponsors=parse_sponsors(page.html),
        source_url=source_url,
        actions=actions,
        versions=parse_versions(page.html),
        kind=classify_kind(title),
    )


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for table in tree.css("table"):
        header = _clean_text(table.css_first("thead").text(separator=" ", strip=True) if table.css_first("thead") else None)
        if "Date" not in header or "Action Taken" not in header:
            continue
        for row in table.css("tbody tr"):
            cells = row.css("td")
            if len(cells) < 4:
                continue
            occurred_at = _parse_date(_clean_text(cells[1].text()))
            action_text = _clean_text(" ".join(part for part in [_clean_text(cells[2].text()), _clean_text(cells[3].text())] if part))
            if occurred_at is None or not action_text:
                continue
            actions.append(BillAction(
                occurred_at=occurred_at,
                chamber=_chamber_from_action(action_text),
                action_text=action_text,
                normalized_status=match_first(action_text, PATTERNS),
                source_url=source_url,
            ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for table in tree.css("table"):
        header = _clean_text(table.css_first("thead").text(separator=" ", strip=True) if table.css_first("thead") else None)
        if header not in {"Text of Bill", "Called Amendments", "Uncalled Amendments"}:
            continue
        for anchor in table.css("tbody a"):
            href = _clean_text(anchor.attributes.get("href"))
            label = _clean_text(anchor.text()) or "document"
            if not href or href.startswith("#") or label.lower() == "[doc]":
                continue
            url = urljoin(ROOT, href)
            if url in seen:
                continue
            seen.add(url)
            versions.append(BillVersion(label=_version_label(label), source_url=url, format=_format_for_url(url)))
    return versions


def parse_sponsors(html: str) -> list[Sponsor]:
    fragment = _introduced_fragment(html)
    if not fragment:
        return []
    tree = HTMLParser(fragment)
    sponsors: list[Sponsor] = []
    for anchor in tree.css("a"):
        sponsor = _sponsor_from_text(_clean_text(anchor.text()), role="primary")
        if sponsor is not None:
            sponsors.append(sponsor)
    if sponsors:
        return sponsors
    text = _clean_text(tree.text(separator=" ", strip=True))
    if text:
        sponsors.append(Sponsor(name=text, role="primary"))
    return sponsors


def query_number_for(prefix: str, number: int) -> str:
    return f"{prefix}{number:05d}"


def display_number_for(query_number: str) -> str:
    prefix = query_number[:2].upper()
    digits = query_number[2:].lstrip("0") or "0"
    return f"{prefix}-{digits}"


def _display_number_from_header(header: str | None) -> str | None:
    text = _clean_text(header)
    if not text:
        return None
    match = re.search(r"\b([HS])\.B\.\s+No\.\s+(\d+)\b", text, re.IGNORECASE)
    if match:
        return f"{match.group(1).upper()}B-{int(match.group(2))}"
    return None


def _introduced_fragment(html: str) -> str:
    match = re.search(r"<h5>\s*Introduced by:\s*</h5>(?P<body>.*?)(?:</div>|<hr\b)", html, re.IGNORECASE | re.DOTALL)
    return match.group("body") if match else ""


def _sponsor_from_text(text: str, *, role: str) -> Sponsor | None:
    if not text:
        return None
    match = re.match(r"(?P<name>.+?),\s*(?P<district>[\w ]+? Dist\.)$", text)
    if match:
        return Sponsor(name=_clean_text(match.group("name")), role=role, district=_clean_text(match.group("district")))
    return Sponsor(name=text, role=role)


def _is_missing_bill(html: str) -> bool:
    if "Bill not found in Database" in html:
        return True
    tree = HTMLParser(html)
    header = _clean_text(tree.css_first("h3").text() if tree.css_first("h3") else None)
    return "Session Year" not in header or _display_number_from_header(header) is None


def _status_url(query_number: str, year: int) -> str:
    return f"{ROOT}/ASP/CGABILLSTATUS/cgabillstatus.asp?{urlencode({'bill_num': query_number, 'selBillType': 'Bill', 'which_year': str(year)})}"


def _parse_date(value: str | None) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _chamber_for_number(number: str) -> Chamber:
    normalized = number.upper().replace(".", "")
    if normalized.startswith("HB"):
        return Chamber.LOWER
    if normalized.startswith("SB"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "house" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    if "governor" in lowered:
        return Chamber.EXECUTIVE
    return None


def _version_label(label: str) -> str:
    text = _clean_text(label)
    lowered = text.lower()
    if "public act" in lowered:
        return "public act"
    if "file no" in lowered:
        return lowered.replace("no.", "no")
    if "raised bill" in lowered:
        return "raised bill"
    if "new bill" in lowered:
        return "new bill"
    if "joint favorable" in lowered:
        return lowered
    if "amendment" in lowered or "schedule" in lowered:
        return lowered
    return text or "document"


def _format_for_url(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".docx"):
        return "docx"
    if lowered.endswith(".doc"):
        return "doc"
    return "html"


def _number_sort_key(number: str) -> tuple[str, int]:
    match = re.match(r"([A-Z]+)-?(\d+)", number.upper())
    if match is None:
        return (number, 0)
    return (match.group(1), int(match.group(2)))


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\xa0", " ").split())
