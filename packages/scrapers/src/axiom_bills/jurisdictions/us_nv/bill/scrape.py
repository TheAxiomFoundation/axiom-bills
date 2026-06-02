"""Nevada bill scraper.

Nevada's public NELIS app renders bill lists and detail tabs as official
HTML fragments. The current NELIS landing page may point to a future
session with no bills, so this scraper walks session links until it finds
the newest session that actually returns bill rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

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

ROOT = "https://www.leg.state.nv.us"
NELIS_ROOT = f"{ROOT}/App/NELIS/REL"
BILL_TYPES = ("AB", "AR", "ACR", "AJR", "IP", "SB", "SR", "SCR", "SJR")


@dataclass(frozen=True)
class NevadaListItem:
    number: str
    title: str
    bill_key: str
    source_url: str


class NevadaScraper(BillScraper):
    jurisdiction = "us-nv"
    source_name = "leg.state.nv.us official Nevada NELIS"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session_slug, session_html, items = self._session_with_bills()
        session = session_from_html(session_slug, session_html)
        bills: list[Bill] = []
        for item in items:
            if self.limit is not None and len(bills) >= self.limit:
                break
            bills.append(self._bill_from_item(item, session=session, session_slug=session_slug))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session_with_bills(self) -> tuple[str, str, list[NevadaListItem]]:
        home = self.http.get(f"{NELIS_ROOT}/")
        candidates = session_slugs(home.text, str(home.url))
        for slug in candidates:
            session_html = self.http.get(f"{NELIS_ROOT}/{slug}").text
            items = self._list_items(slug)
            if items:
                return slug, session_html, items
        return candidates[0], home.text, []

    def _list_items(self, session_slug: str) -> list[NevadaListItem]:
        items: list[NevadaListItem] = []
        seen: set[str] = set()
        for bill_type in BILL_TYPES:
            html = self.http.get(_bill_list_url(session_slug, bill_type)).text
            for item in parse_bill_list(html):
                if item.bill_key in seen:
                    continue
                seen.add(item.bill_key)
                items.append(item)
        items.sort(key=lambda item: _number_sort_key(item.number))
        return items

    def _bill_from_item(self, item: NevadaListItem, *, session: Session, session_slug: str) -> Bill:
        overview = self.http.get(_tab_url(session_slug, item.bill_key, "Overview")).text
        text = self.http.get(_tab_url(session_slug, item.bill_key, "Text")).text
        return parse_bill(item, overview_html=overview, text_html=text, session=session)


def session_slugs(html: str, effective_url: str | None = None) -> list[str]:
    slugs: list[str] = []
    if effective_url:
        match = re.search(r"/App/NELIS/REL/([^/?#]+)", urlsplit(effective_url).path)
        if match and _is_session_slug(match.group(1)):
            slugs.append(match.group(1))
    for match in re.finditer(r"/App/NELIS/REL/([0-9A-Za-z]+(?:Special)?)", html):
        slug = match.group(1)
        if slug not in slugs and _is_session_slug(slug):
            slugs.append(slug)
    return slugs or ["83rd2025"]


def session_from_html(slug: str, html: str) -> Session:
    tree = HTMLParser(html)
    display = _clean_text(tree.css_first(".session-text").text() if tree.css_first(".session-text") else "")
    if not display:
        display = _display_from_slug(slug)
    body = _clean_text(tree.body.text() if tree.body else html)
    start = _date_after(body, r"(?:convened|will begin) on ([A-Z][a-z]+ \d{1,2}, \d{4})")
    end = _date_after(body, r"adjourned sine die on ([A-Z][a-z]+ \d{1,2}, \d{4})")
    now = datetime.now().date()
    is_current = bool(start and (end is None and start <= now or end is not None and start <= now <= end))
    return Session(
        name=f"{display} Nevada Legislature",
        start_date=start,
        end_date=end,
        is_current=is_current,
    )


def parse_bill_list(html: str) -> list[NevadaListItem]:
    tree = HTMLParser(html)
    items: list[NevadaListItem] = []
    for link in tree.css("a[href*='/Bill/'][href$='/Overview']"):
        number = _format_number(link.text())
        href = link.attributes.get("href") or ""
        key_match = re.search(r"/Bill/(\d+)/Overview", href)
        if key_match is None or not number:
            continue
        row = _ancestor_with_class(link, "row")
        title = _title_from_list_row(row, number) if row else ""
        items.append(NevadaListItem(
            number=number,
            title=title or number,
            bill_key=key_match.group(1),
            source_url=urljoin(ROOT, href),
        ))
    return items


def parse_bill(item: NevadaListItem, *, overview_html: str, text_html: str, session: Session) -> Bill:
    overview = HTMLParser(overview_html)
    summary = _value_for_label(overview, "Summary") or item.title
    title = summary or item.title
    digest = _node_text(overview.css_first("#digest"))
    return Bill(
        jurisdiction=NevadaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=title,
        summary=digest or summary,
        subjects=[],
        sponsors=parse_sponsors(overview),
        source_url=item.source_url,
        actions=parse_actions(overview_html, source_url=item.source_url),
        versions=parse_versions(text_html),
        kind=classify_kind(" ".join(part for part in (title, digest) if part)),
    )


def parse_sponsors(tree: HTMLParser) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[tuple[str, str]] = set()
    for label, role in (("Primary Sponsor", "primary"), ("Co-Sponsors", "cosponsor"), ("Co-Sponsor", "cosponsor")):
        row = _row_for_label(tree, label)
        if row is None:
            continue
        for link in row.css("a"):
            name = _clean_text(link.text())
            key = (name, role)
            if name and key not in seen:
                seen.add(key)
                sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def parse_actions(html: str, *, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for table in tree.css("table"):
        caption = _clean_text(table.css_first("caption").text() if table.css_first("caption") else "")
        if "bill history" not in caption.lower():
            continue
        for row in table.css("tbody tr"):
            date_cell = row.css_first("td[data-th='Date']")
            action_cell = row.css_first("td[data-th='Action']")
            occurred_at = _parse_action_date(_node_text(date_cell))
            text = _node_text(action_cell)
            if occurred_at is None or not text:
                continue
            actions.append(BillAction(
                occurred_at=occurred_at,
                chamber=_chamber_from_action(text),
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
                source_url=source_url,
            ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(html: str) -> list[BillVersion]:
    tree = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in tree.css("a[href]"):
        href = link.attributes.get("href") or ""
        if not href.lower().endswith(".pdf") or "/Session/" not in href:
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        label = _clean_text(link.text()) or source_url.rsplit("/", 1)[-1]
        versions.append(BillVersion(label=label, source_url=source_url, format="pdf"))
    return versions


def _bill_list_url(session_slug: str, bill_type: str) -> str:
    return f"{NELIS_ROOT}/{session_slug}/HomeBill/BillsTab?Filters.PageSize=2147483647&SelectedBillTypes={bill_type}"


def _tab_url(session_slug: str, bill_key: str, selected_tab: str) -> str:
    return f"{NELIS_ROOT}/{session_slug}/Bill/FillSelectedBillTab?selectedTab={selected_tab}&billKey={bill_key}"


def _row_for_label(tree: HTMLParser, label: str) -> Node | None:
    for row in tree.css(".row"):
        cells = _child_elements(row, "div")
        if len(cells) >= 2 and _clean_text(cells[0].text()).lower() == label.lower():
            return row
    return None


def _value_for_label(tree: HTMLParser, label: str) -> str:
    row = _row_for_label(tree, label)
    if row is None:
        return ""
    cells = _child_elements(row, "div")
    return _clean_text(cells[1].text()) if len(cells) > 1 else ""


def _ancestor_with_class(node: Node, class_name: str) -> Node | None:
    current = node.parent
    while current is not None:
        classes = current.attributes.get("class") or ""
        if class_name in classes.split():
            return current
        current = current.parent
    return None


def _title_from_list_row(row: Node, number: str) -> str:
    cells = _child_elements(row, "div")
    if len(cells) < 2:
        return ""
    text = _clean_text(cells[1].text())
    return text.removeprefix(number).strip()


def _child_elements(node: Node, tag: str | None = None) -> list[Node]:
    children: list[Node] = []
    child = node.child
    while child is not None:
        if (tag is None or child.tag == tag) and child.tag != "-text":
            children.append(child)
        child = child.next
    return children


def _display_from_slug(slug: str) -> str:
    match = re.match(r"(\d+)(?:st|nd|rd|th)(\d{4})(Special)?", slug)
    if match is None:
        return slug
    special = " Special" if match.group(3) else ""
    ordinal = slug[: slug.index(match.group(2))]
    return f"{ordinal} ({match.group(2)}){special} Session"


def _is_session_slug(value: str) -> bool:
    return bool(re.match(r"^\d+(?:st|nd|rd|th)\d{4}(?:Special)?$", value))


def _date_after(text: str, pattern: str) -> date | None:
    match = re.search(pattern, text)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


def _parse_action_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%b %d, %Y")
    except ValueError:
        return None
    return datetime.combine(parsed.date(), datetime.min.time())


def _format_number(value: object) -> str:
    text = _clean_text(value).upper().replace(" ", "")
    match = re.match(r"([A-Z]+)(\d+)$", text)
    if match is None:
        return text
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    prefix = number.upper().split()[0]
    if prefix in {"AJR", "ACR", "SJR", "SCR", "IP"}:
        return Chamber.JOINT
    if prefix.startswith("A"):
        return Chamber.LOWER
    if prefix.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "assembly" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())


def _node_text(node: Node | None) -> str:
    return _clean_text(node.text() if node else "")


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
