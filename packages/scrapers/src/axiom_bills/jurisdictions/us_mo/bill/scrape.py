"""Missouri bill scraper.

Missouri's House site publishes a custom bill report that enumerates both
House and Senate bills. House bill detail lives on house.mo.gov content/action
endpoints; Senate bill detail lives on senate.mo.gov BillTracking endpoints.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote, urljoin

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

HOUSE_ROOT = "https://house.mo.gov"
SENATE_ROOT = "https://www.senate.mo.gov"
DEFAULT_YEAR = 2026
DEFAULT_CODE = "R"
DEFAULT_CHAMBERS = ("h", "s")


@dataclass(frozen=True)
class MissouriListItem:
    number: str
    sponsor: str
    bill_string: str
    last_action: str | None
    detail_url: str


class MissouriScraper(BillScraper):
    jurisdiction = "us-mo"
    source_name = "house.mo.gov and senate.mo.gov official bill pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        year: int = DEFAULT_YEAR,
        code: str = DEFAULT_CODE,
        chambers: tuple[str, ...] = DEFAULT_CHAMBERS,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.year = year
        self.code = code
        self.chambers = chambers

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        items: list[MissouriListItem] = []
        for chamber in self.chambers:
            html = self.http.get(_report_url(chamber)).text
            items.extend(parse_listing(html))
        items.sort(key=lambda item: _number_sort_key(item.number))
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            if item.number.startswith(("HB", "HJR")):
                content_url = _house_content_url(item.number, self.year, self.code)
                actions_url = _house_actions_url(item.number, self.year, self.code)
                detail_html = self.http.get(content_url).text
                actions_html = self.http.get(actions_url).text
                bills.append(parse_house_bill(item, detail_html, actions_html, session=session, source_url=content_url))
            else:
                detail_html = self.http.get(item.detail_url).text
                actions_url = _senate_modal_url(detail_html, "Actions")
                text_url = _senate_modal_url(detail_html, "BillText")
                actions_html = self.http.get(actions_url).text if actions_url else ""
                text_html = self.http.get(text_url).text if text_url else ""
                bills.append(parse_senate_bill(item, detail_html, actions_html, text_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_for_year(year: int) -> Session:
    return Session(
        name=f"{year} Missouri Regular Session",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=datetime.now().year == year,
    )


def parse_listing(html: str) -> list[MissouriListItem]:
    tree = HTMLParser(html)
    items: list[MissouriListItem] = []
    seen: set[str] = set()
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 5:
            continue
        link = cells[0].css_first("a[href]")
        if link is None:
            continue
        number = _format_number(_clean_text(link.text()))
        if not number or number.lower() == "bill" or number in seen:
            continue
        href = link.attributes.get("href")
        if not href:
            continue
        seen.add(number)
        last_action = _clean_text(cells[4].text(separator=" ")) or None
        if last_action == "1/1/1900":
            last_action = None
        items.append(MissouriListItem(
            number=number,
            sponsor=_clean_text(cells[1].text(separator=" ")),
            bill_string=_clean_text(cells[3].text(separator=" ")) or number,
            last_action=last_action,
            detail_url=urljoin(HOUSE_ROOT, href.strip()),
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_house_bill(
    item: MissouriListItem,
    detail_html: str,
    actions_html: str,
    *,
    session: Session,
    source_url: str,
) -> Bill:
    fields = _label_fields(detail_html)
    title = _house_title(detail_html) or item.bill_string
    summary = title
    return Bill(
        jurisdiction=MissouriScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=summary,
        subjects=parse_subjects(title),
        sponsors=parse_house_sponsors(detail_html, fallback=item.sponsor),
        source_url=source_url,
        actions=parse_house_actions(actions_html, source_url=source_url),
        versions=parse_house_versions(detail_html),
        kind=classify_kind(" ".join(part for part in (title, fields.get("Bill String")) if part)),
    )


def parse_senate_bill(
    item: MissouriListItem,
    detail_html: str,
    actions_html: str,
    text_html: str,
    *,
    session: Session,
) -> Bill:
    fields = _senate_fields(detail_html)
    title = fields.get("Title") or item.bill_string
    summary = _senate_summary(detail_html) or title
    return Bill(
        jurisdiction=MissouriScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=summary,
        subjects=parse_subjects(title),
        sponsors=parse_senate_sponsors(detail_html, fallback=item.sponsor),
        source_url=item.detail_url,
        actions=parse_senate_actions(actions_html, source_url=item.detail_url),
        versions=parse_senate_versions(text_html),
        kind=classify_kind(" ".join(part for part in (title, summary) if part)),
    )


def parse_house_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
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
            chamber=_chamber_from_text(f"{journal} {text}"),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_senate_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("tr"):
        cells = row.css("td,th")
        if len(cells) < 2:
            continue
        occurred_on = _parse_date(_clean_text(cells[0].text()))
        if occurred_on is None:
            continue
        text = _clean_text(cells[1].text(separator=" "))
        journal = _clean_text(cells[2].text(separator=" ")) if len(cells) > 2 else ""
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=_chamber_from_text(f"{journal} {text}"),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_house_sponsors(html: str, *, fallback: str | None = None) -> list[Sponsor]:
    fields = _label_fields(html)
    sponsor = fields.get("Sponsor") or fallback
    return [Sponsor(name=_format_name(sponsor), role="primary")] if sponsor else []


def parse_senate_sponsors(html: str, *, fallback: str | None = None) -> list[Sponsor]:
    fields = _senate_fields(html)
    sponsor = fields.get("Sponsor") or fallback
    return [Sponsor(name=_format_name(sponsor), role="primary")] if sponsor else []


def parse_subjects(title: str | None) -> list[str]:
    if not title:
        return []
    match = re.match(r"(?:Creates|Modifies|Establishes|Changes|Requires|Authorizes)\s+provisions?\s+relating\s+to\s+(.+)", title, re.IGNORECASE)
    if match:
        return [_clean_text(match.group(1)).title()]
    return []


def parse_house_versions(html: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in HTMLParser(html).css('a[href$=".pdf"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(HOUSE_ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(label=_clean_text(link.text(separator=" ")) or _label_from_url(url), source_url=url, format="pdf"))
    return versions


def parse_senate_versions(html: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in HTMLParser(html).css('a[href$=".pdf"]'):
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(SENATE_ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(label=_clean_text(link.text(separator=" ")) or _label_from_url(url), source_url=url, format="pdf"))
    return versions


def _report_url(chamber: str) -> str:
    return f"{HOUSE_ROOT}/billreport.aspx?select=chamber%3A{quote(chamber)}&showlastactivity=yes"


def _house_content_url(number: str, year: int, code: str) -> str:
    compact = number.replace(" ", "")
    return f"{HOUSE_ROOT}/BillContent.aspx?bill={compact}&year={year}&code={code}&style=new"


def _house_actions_url(number: str, year: int, code: str) -> str:
    compact = number.replace(" ", "")
    return f"{HOUSE_ROOT}/BillActions.aspx?bill={compact}&year={year}&code={code}"


def _senate_modal_url(html: str, handler: str) -> str | None:
    for button in HTMLParser(html).css("[data-modal-url]"):
        url = button.attributes.get("data-modal-url") or ""
        if f"handler={handler}" in url:
            return urljoin(SENATE_ROOT, url)
    return None


def _label_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in HTMLParser(html).css("tr"):
        cells = row.css("td,th")
        if len(cells) < 2:
            continue
        value = _clean_text(cells[0].text(separator=" "))
        label = _clean_text(cells[1].text(separator=" ")).rstrip(":")
        if label and value:
            fields[label] = value
    return fields


def _senate_fields(html: str) -> dict[str, str]:
    text = _clean_text(HTMLParser(html).text(separator=" "))
    fields: dict[str, str] = {}
    for label in ("Sponsor", "LR Number", "Title", "Effective Date", "Committee", "Current Status"):
        match = re.search(rf"\b{re.escape(label)}\s+(.+?)(?=\s+(?:Sponsor|LR Number|Title|House Handler|Journal Page|Effective Date|Committee|Current Status|Quick Links|CURRENT BILL SUMMARY)\b|$)", text)
        if match:
            fields[label] = _clean_text(match.group(1))
    return fields


def _senate_summary(html: str) -> str | None:
    text = _clean_text(HTMLParser(html).text(separator=" "))
    match = re.search(r"CURRENT BILL SUMMARY\s+(.+?)(?:\s+[A-Z][A-Z ]{3,}$|$)", text)
    return _clean_text(match.group(1)) if match else None


def _house_title(html: str) -> str | None:
    text = _clean_text(HTMLParser(html).text(separator=" "))
    match = re.search(r"\b(?:HB|SB|HJR|SJR)\s+\d+\s+(.+?)\s+Sponsor:", text)
    return _clean_text(match.group(1)) if match else None


def _format_number(value: str) -> str:
    match = re.match(r"([A-Za-z]+)\s*(\d+)", _clean_text(value))
    return f"{match.group(1).upper()} {int(match.group(2))}" if match else _clean_text(value)


def _format_name(value: str | None) -> str:
    text = _clean_text(value)
    text = re.sub(r"\s+\(\d+\)$", "", text)
    if "," in text:
        last, first = [part.strip() for part in text.split(",", 1)]
        return f"{first} {last}".strip()
    return text


def _chamber_for_number(number: str) -> Chamber:
    if number.upper().startswith(("HB", "HJR")):
        return Chamber.LOWER
    if number.upper().startswith(("SB", "SJR")):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(text: str) -> Chamber | None:
    if re.search(r"\b(?:H|House|\(H\))\b", text, re.IGNORECASE):
        return Chamber.LOWER
    if re.search(r"\b(?:S|Senate|\(S\))\b", text, re.IGNORECASE):
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix = number.upper().split(" ", 1)[0]
    order = {"HB": 0, "HJR": 1, "SB": 2, "SJR": 3}.get(prefix, 9)
    match = re.search(r"\d+", number)
    return (order, int(match.group(0)) if match else 0, number)


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(_clean_text(value), "%m/%d/%Y").date()
    except ValueError:
        return None


def _label_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
