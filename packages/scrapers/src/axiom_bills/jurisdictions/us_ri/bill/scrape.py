"""Rhode Island bill scraper.

Rhode Island publishes bill text in official chamber directories and bill
history through the official status.rilegislature.gov search form.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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

STATUS_ROOT = "https://status.rilegislature.gov/"
TEXT_ROOT = "http://webserver.rilegislature.gov/BillText/BillText{suffix}/"
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BillTextItem:
    number: str
    pdf_url: str
    html_url: str


class RhodeIslandScraper(BillScraper):
    jurisdiction = "us-ri"
    source_name = "status.rilegislature.gov"
    min_interval_per_host = 0.2

    def __init__(self, *, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year or datetime.now(tz=ET).year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        items = self._list_bill_texts()
        item_by_number = {item.number.upper(): item for item in items}
        bills: list[Bill] = []
        for chamber, ranges in _ranges_by_chamber(items).items():
            for first, last in ranges:
                html = self._status_range(first, last)
                for bill in parse_status_results(html, session=session, chamber=chamber, item_by_number=item_by_number):
                    bills.append(bill)
                    if self.limit is not None and len(bills) >= self.limit:
                        break
                if self.limit is not None and len(bills) >= self.limit:
                    break
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: bill.number)
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _list_bill_texts(self) -> list[BillTextItem]:
        suffix = str(self.year)[-2:]
        root = TEXT_ROOT.format(suffix=suffix)
        urls = [
            f"{root}HouseText{suffix}/HouseText{suffix}.html",
            f"{root}SenateText{suffix}/SenateText{suffix}.html",
        ]
        items: list[BillTextItem] = []
        for url in urls:
            items.extend(parse_bill_text_index(self.http.get(url).text, base_url=url))
        items.sort(key=lambda item: (_bill_prefix(item.number), _bill_number_int(item.number), item.number.lower()))
        return items

    def _status_range(self, first: int, last: int) -> str:
        page = self.http.get(STATUS_ROOT).text
        form = _form_fields(page)
        form.update({
            "ctl00$rilinContent$cbYear": str(self.year),
            "ctl00$rilinContent$txtBillFrom": str(first),
            "ctl00$rilinContent$txtBillTo": str(last),
            "ctl00$rilinContent$comm": "cbxIn",
            "ctl00$rilinContent$cmdReport": "Enter",
        })
        return self.http.post(STATUS_ROOT, data=form).text


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year} Rhode Island General Assembly",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now(tz=ET).year,
    )


def parse_bill_text_index(html: str, *, base_url: str) -> list[BillTextItem]:
    tree = HTMLParser(html)
    items: list[BillTextItem] = []
    for row in tree.css("tr.bill_row, tr.bill_row_alt"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        number = _clean_text(cells[0].text())
        pdf = cells[1].css_first("a")
        html_link = cells[2].css_first("a")
        pdf_href = pdf.attributes.get("href") if pdf else None
        html_href = html_link.attributes.get("href") if html_link else None
        if not number or not _looks_like_bill_number(number) or not pdf_href or not html_href:
            continue
        items.append(BillTextItem(
            number=number,
            pdf_url=urljoin(base_url, pdf_href),
            html_url=urljoin(base_url, html_href),
        ))
    return items


def parse_status_results(
    html: str,
    *,
    session: Session,
    chamber: Chamber,
    item_by_number: dict[str, BillTextItem],
) -> list[Bill]:
    container = HTMLParser(html).css_first("#lblBills")
    if container is None:
        return []
    bills: list[Bill] = []
    current: dict | None = None
    for child in container.iter():
        if child.tag != "div":
            continue
        text = _clean_text(child.text())
        if not text or text.startswith("Condition:") or text.startswith("Total Bills:"):
            continue
        if _is_bill_header(text):
            if current is not None:
                bill = _bill_from_section(current, session, chamber, item_by_number)
                if bill is not None:
                    bills.append(bill)
            current = {"header": child, "lines": []}
        elif current is not None:
            current["lines"].append((text, child))
    if current is not None:
        bill = _bill_from_section(current, session, chamber, item_by_number)
        if bill is not None:
            bills.append(bill)
    return bills


def _bill_from_section(
    section: dict,
    session: Session,
    chamber: Chamber,
    item_by_number: dict[str, BillTextItem],
) -> Bill | None:
    header: Node = section["header"]
    link = header.css_first("a")
    href = link.attributes.get("href") if link else None
    if not href:
        return None
    number = _number_from_href(href)
    if not number:
        return None
    lines = section["lines"]
    title = _line_after_prefix(lines, "ENTITLED,") or number
    sponsor = _line_after_prefix(lines, "BY")
    actions = _actions(lines)
    item = item_by_number.get(number.upper())
    pdf_url = item.pdf_url if item else href
    html_url = item.html_url if item else re.sub(r"\.pdf$", ".htm", href, flags=re.IGNORECASE)
    versions = [
        BillVersion(label="pdf", source_url=pdf_url, format="pdf"),
        BillVersion(label="html", source_url=html_url, format="html"),
    ]
    return Bill(
        jurisdiction=RhodeIslandScraper.jurisdiction,
        session_name=session.name,
        chamber=chamber,
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=[Sponsor(name=sponsor, role="sponsor")] if sponsor else [],
        source_url=pdf_url,
        actions=actions,
        versions=versions,
        kind=classify_kind(f"{_clean_text(header.text())} {title}"),
    )


def _actions(lines: list[tuple[str, Node]]) -> list[BillAction]:
    actions: list[BillAction] = []
    for text, _node in lines:
        match = re.match(r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<action>.+)", text)
        if not match:
            if re.match(r"Chapter \d+", text, flags=re.IGNORECASE):
                if actions:
                    actions[-1].normalized_status = match_first(text, PATTERNS)
            continue
        occurred_at = datetime.strptime(match.group("date"), "%m/%d/%Y").replace(tzinfo=ET)
        action_text = _clean_text(match.group("action")) or ""
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_for_action(action_text),
            action_text=action_text,
            normalized_status=match_first(action_text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _form_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    fields: dict[str, str] = {}
    for field in tree.css("input"):
        name = field.attributes.get("name")
        if not name:
            continue
        input_type = (field.attributes.get("type") or "").lower()
        if input_type in {"submit", "button", "image"}:
            continue
        fields[name] = field.attributes.get("value") or ""
    return fields


def _ranges_by_chamber(items: list[BillTextItem]) -> dict[Chamber, list[tuple[int, int]]]:
    numbers: dict[Chamber, list[int]] = {Chamber.LOWER: [], Chamber.UPPER: []}
    for item in items:
        chamber = Chamber.UPPER if item.number.upper().startswith("S") else Chamber.LOWER
        number = _bill_number_int(item.number)
        if number >= 0:
            numbers[chamber].append(number)
    ranges: dict[Chamber, list[tuple[int, int]]] = {Chamber.LOWER: [], Chamber.UPPER: []}
    for chamber, values in numbers.items():
        if not values:
            continue
        first = min(values)
        last = max(values)
        start = first
        while start <= last:
            end = min(start + 249, last)
            ranges[chamber].append((start, end))
            start = end + 1
    return ranges


def _line_after_prefix(lines: list[tuple[str, Node]], prefix: str) -> str | None:
    for text, _node in lines:
        if text.upper().startswith(prefix):
            return _clean_text(text[len(prefix):].strip(" ,\xa0"))
    return None


def _is_bill_header(text: str) -> bool:
    return bool(re.match(r"^(House|Senate) (Bill|Resolution) No\.", text, re.IGNORECASE))


def _looks_like_bill_number(number: str) -> bool:
    return bool(re.match(r"^[HS]\d{4}[A-Za-z]*$", number, re.IGNORECASE))


def _number_from_href(href: str) -> str | None:
    match = re.search(r"/([HS]\d+[A-Za-z]*)\.pdf$", href, re.IGNORECASE)
    return match.group(1) if match else None


def _chamber_for_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "house" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _bill_prefix(number: str) -> str:
    return number[:1].upper()


def _bill_number_int(number: str) -> int:
    match = re.search(r"\d+", number)
    return int(match.group(0)) if match else -1


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
