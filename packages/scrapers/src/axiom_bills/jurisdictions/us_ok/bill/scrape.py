"""Oklahoma bill scraper.

Oklahoma publishes official ASP.NET WebForms reports for bill status and
server-rendered BillInfo pages with history, author, and version tabs.
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

ROOT = "https://www.oklegislature.gov"
STATUS_URL = "https://webapps.oklegislature.gov/WebApplication3/WebForm1.aspx"
BILL_TYPES = ("HB", "HJR", "HCR", "HR", "SB", "SJR", "SCR", "SR")


@dataclass(frozen=True)
class OklahomaSessionInfo:
    session_id: str
    display: str


@dataclass(frozen=True)
class OklahomaListItem:
    number: str
    title: str
    status: str
    status_date: datetime | None
    chamber_code: str
    source_url: str


class OklahomaScraper(BillScraper):
    jurisdiction = "us-ok"
    source_name = "oklegislature.gov official Oklahoma Legislature"
    min_interval_per_host = 0.15

    def scrape(self) -> ScrapeResult:
        session_info, items = self._current_status_items()
        session = session_from_info(session_info)
        bills: list[Bill] = []
        for item in items:
            if self.limit is not None and len(bills) >= self.limit:
                break
            if self.limit is None:
                bills.append(parse_bill_from_status_item(item, session=session))
                continue
            html = self.http.get(item.source_url).text
            bills.append(parse_bill(item, detail_html=html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _current_status_items(self) -> tuple[OklahomaSessionInfo, list[OklahomaListItem]]:
        first_page = self.http.get(STATUS_URL).text
        session_info = current_session_from_form(first_page)
        items: list[OklahomaListItem] = []
        seen: set[str] = set()
        for bill_type in BILL_TYPES:
            form_page = first_page if bill_type == BILL_TYPES[0] else self.http.get(STATUS_URL).text
            report_html = self.http.post(
                STATUS_URL,
                data=status_report_payload(form_page, session_info.session_id, bill_type),
            ).text
            for item in parse_status_report(report_html):
                if item.source_url in seen:
                    continue
                seen.add(item.source_url)
                items.append(item)
                if self.limit is not None and len(items) >= self.limit:
                    items.sort(key=lambda item: _number_sort_key(item.number))
                    return session_info, items
        items.sort(key=lambda item: _number_sort_key(item.number))
        return session_info, items


def current_session_from_form(html: str) -> OklahomaSessionInfo:
    tree = HTMLParser(html)
    option = tree.css_first("#cbxSessionId option")
    if option is None:
        return OklahomaSessionInfo(session_id="2600", display="2026 Regular Session")
    return OklahomaSessionInfo(
        session_id=_clean_text(option.attributes.get("value")) or "2600",
        display=_clean_text(option.text()) or "2026 Regular Session",
    )


def status_report_payload(html: str, session_id: str, bill_type: str) -> dict[str, str]:
    tree = HTMLParser(html)
    data: dict[str, str] = {}
    for node in tree.css("input"):
        name = node.attributes.get("name")
        if not name:
            continue
        input_type = (node.attributes.get("type") or "").lower()
        if input_type in {"checkbox", "radio"} and "checked" not in node.attributes:
            continue
        if input_type in {"submit", "image"}:
            continue
        data[name] = node.attributes.get("value") or ""
    data.update({
        "cbxSessionId": session_id,
        "cbxActiveStatus": "All",
        "lbxTypes": bill_type,
        "RadioButtonList1": "On Any day",
        "Button1": "Retrieve",
    })
    return data


def session_from_info(info: OklahomaSessionInfo) -> Session:
    year_match = re.search(r"\b(20\d{2})\b", info.display)
    year = int(year_match.group(1)) if year_match else 2026
    return Session(
        name=f"{year} Oklahoma {info.display.split(' ', 1)[1]}",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now().year,
    )


def parse_status_report(html: str) -> list[OklahomaListItem]:
    tree = HTMLParser(html)
    items: list[OklahomaListItem] = []
    for row in tree.css("tr"):
        cells = row.css("td")
        if len(cells) < 6:
            continue
        link = cells[0].css_first("a[href*='BillInfo.aspx']")
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        raw_number = _bill_number_from_href(href) or _clean_text(link.text())
        number = _format_number(raw_number)
        if not number:
            continue
        source_url = _canonical_bill_url(href)
        items.append(OklahomaListItem(
            number=number,
            title=_clean_text(cells[5].text()) or number,
            status=_clean_text(cells[3].text()),
            status_date=_parse_date(_clean_text(cells[4].text())),
            chamber_code=_clean_text(cells[2].text()),
            source_url=source_url,
        ))
    return items


def parse_bill(item: OklahomaListItem, *, detail_html: str, session: Session) -> Bill:
    tree = HTMLParser(detail_html)
    title = _clean_text(_node_text(tree.css_first("#ctl00_ContentPlaceHolder1_txtST"))) or item.title
    text_for_kind = " ".join(part for part in (title, item.status) if part)
    actions = parse_actions(tree, source_url=item.source_url)
    if not actions and item.status_date is not None and item.status:
        actions = [_action_from_status_item(item)]
    return Bill(
        jurisdiction=OklahomaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=parse_sponsors(tree),
        source_url=item.source_url,
        actions=actions,
        versions=parse_versions(tree),
        kind=classify_kind(text_for_kind),
    )


def parse_bill_from_status_item(item: OklahomaListItem, *, session: Session) -> Bill:
    actions = [_action_from_status_item(item)] if item.status_date is not None and item.status else []
    title = item.title or item.number
    return Bill(
        jurisdiction=OklahomaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=[],
        source_url=item.source_url,
        actions=actions,
        versions=[],
        kind=classify_kind(" ".join(part for part in (title, item.status) if part)),
    )


def parse_actions(tree: HTMLParser, *, source_url: str | None = None) -> list[BillAction]:
    table = tree.css_first("#ctl00_ContentPlaceHolder1_TabContainer1_TabPanel1_tblHouseActions")
    if table is None:
        return []
    actions: list[BillAction] = []
    for row in table.css("tr"):
        cells = row.css("td")
        if len(cells) < 4:
            continue
        text = _clean_text(cells[0].text())
        occurred_at = _parse_date(_clean_text(cells[2].text()))
        if not text or occurred_at is None or _is_heading_or_divider(text):
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_code(_clean_text(cells[3].text())),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(tree: HTMLParser) -> list[BillVersion]:
    table = tree.css_first("#ctl00_ContentPlaceHolder1_TabContainer1_TabPanel4_tblVersions")
    if table is None:
        return []
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in table.css("a[href]"):
        href = link.attributes.get("href") or ""
        if not href.lower().endswith(".pdf"):
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        label = _clean_text(link.text()) or source_url.rsplit("/", 1)[-1]
        versions.append(BillVersion(label=label, source_url=source_url, format="pdf"))
    return versions


def parse_sponsors(tree: HTMLParser) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[tuple[str, str]] = set()
    primary = _clean_text(_node_text(tree.css_first("#ctl00_ContentPlaceHolder1_lnkAuth")))
    other = _clean_text(_node_text(tree.css_first("#ctl00_ContentPlaceHolder1_lnkOtherAuth")))
    for name, role in ((primary, "primary"), (other, "cosponsor")):
        key = (name, role)
        if name and key not in seen:
            seen.add(key)
            sponsors.append(Sponsor(name=name, role=role))
    for action in parse_actions(tree):
        match = re.match(r"(?:Co)?[Aa]uthored by (?:Senator|Representative)\s+(.+?)(?:\s+\(|$)", action.action_text)
        if match is None:
            continue
        name = _clean_text(match.group(1))
        role = "cosponsor" if action.action_text.lower().startswith("coauthored") else "primary"
        key = (name, role)
        if name and key not in seen:
            seen.add(key)
            sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def _action_from_status_item(item: OklahomaListItem) -> BillAction:
    return BillAction(
        occurred_at=item.status_date or datetime.now(),
        chamber=_chamber_from_code(item.chamber_code),
        action_text=item.status,
        normalized_status=match_first(item.status, PATTERNS),
        source_url=item.source_url,
    )


def _bill_number_from_href(href: str) -> str:
    parsed = urlsplit(href)
    params = parse_qs(parsed.query)
    return (params.get("Bill") or params.get("bill") or [""])[0]


def _canonical_bill_url(href: str) -> str:
    absolute = urljoin(ROOT, href.replace("http://www.oklegislature.gov", ROOT))
    parsed = urlsplit(absolute)
    params = parse_qs(parsed.query)
    bill = (params.get("Bill") or params.get("bill") or [""])[0]
    session = (params.get("Session") or params.get("session") or [""])[0]
    if bill and session:
        return f"{ROOT}/BillInfo.aspx?Bill={bill.upper()}&Session={session}"
    return absolute


def _format_number(text: str) -> str:
    value = text.replace("*", "").strip().upper()
    match = re.match(r"([A-Z]+)\s*0*(\d+)", value)
    if match is None:
        return value
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    prefix = number.upper().split()[0]
    if prefix in {"HCR", "HJR", "SCR", "SJR"}:
        return Chamber.JOINT
    if prefix.startswith("H"):
        return Chamber.LOWER
    return Chamber.UPPER


def _chamber_from_code(code: str) -> Chamber | None:
    normalized = code.strip().upper()
    if normalized == "H":
        return Chamber.LOWER
    if normalized == "S":
        return Chamber.UPPER
    return None


def _parse_date(text: str) -> datetime | None:
    cleaned = _clean_text(text)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _is_heading_or_divider(text: str) -> bool:
    lowered = text.lower()
    return lowered in {"action", "history"} or "history for" in lowered


def _node_text(node: Node | None) -> str:
    return node.text() if node is not None else ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())
