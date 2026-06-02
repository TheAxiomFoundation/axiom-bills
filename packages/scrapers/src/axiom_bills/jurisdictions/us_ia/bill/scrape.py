"""Iowa bill scraper.

The Iowa Legislature publishes an official all-bills table and per-bill
BillBook pages. BillBook loads action history with a same-site POST; this
scraper uses that official endpoint instead of trying to scrape browser state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote, urlencode, urljoin

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

ROOT = "https://www.legis.iowa.gov"
DEFAULT_GENERAL_ASSEMBLY = 91
DEFAULT_BILL_PREFIXES = ("HF", "SF")


@dataclass(frozen=True)
class IowaBillListItem:
    number: str
    title: str
    detail_url: str
    sponsor: str | None = None
    companion: str | None = None
    similar: str | None = None


class IowaScraper(BillScraper):
    jurisdiction = "us-ia"
    source_name = "legis.iowa.gov official BillBook pages"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        general_assembly: int = DEFAULT_GENERAL_ASSEMBLY,
        bill_prefixes: tuple[str, ...] = DEFAULT_BILL_PREFIXES,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.general_assembly = general_assembly
        self.bill_prefixes = bill_prefixes

    def scrape(self) -> ScrapeResult:
        all_bills_html = self.http.get(_all_bills_url(self.general_assembly)).text
        session = session_from_all_bills(all_bills_html, self.general_assembly)
        items = parse_all_bills(all_bills_html, general_assembly=self.general_assembly)
        if self.bill_prefixes:
            allowed = {prefix.upper() for prefix in self.bill_prefixes}
            items = [item for item in items if _bill_prefix(item.number) in allowed]
        if self.limit is not None:
            items = items[:self.limit]

        bills: list[Bill] = []
        for item in items:
            detail_html = self.http.get(item.detail_url).text
            actions_html = self._actions_html(item.number)
            bills.append(parse_bill(item, detail_html, actions_html, session=session))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _actions_html(self, number: str) -> str:
        response = self.http.post(
            _billbook_url(self.general_assembly, number),
            data={
                "ga": str(self.general_assembly),
                "billName": number,
                "action": "getBillAction",
                "bl": "false",
            },
        )
        response.raise_for_status()
        return response.text


def session_from_all_bills(html: str, general_assembly: int) -> Session:
    match = re.search(
        rf"General Assembly:\s*{general_assembly}\s*.*?"
        r"\((\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\)",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        start = _parse_date(match.group(1))
        end = _parse_date(match.group(2))
    else:
        start = date(datetime.now().year, 1, 1)
        end = date(datetime.now().year, 12, 31)
    return Session(
        name=f"{_ordinal(general_assembly)} Iowa General Assembly ({start.year}-{end.year})",
        start_date=start,
        end_date=end,
        is_current=start <= date.today() <= end,
    )


def parse_all_bills(html: str, *, general_assembly: int) -> list[IowaBillListItem]:
    tree = HTMLParser(html)
    items: list[IowaBillListItem] = []
    for row in tree.css("#sortableTable tr"):
        cells = row.css("td")
        if len(cells) < 6:
            continue
        link = _first_link(cells[1])
        if link is None:
            continue
        number = _clean_text(link.text())
        href = link.attributes.get("href")
        title = _clean_text(cells[2].text(separator=" "))
        if not number or not href:
            continue
        items.append(IowaBillListItem(
            number=number,
            title=title or number,
            detail_url=_detail_url(href, general_assembly=general_assembly, number=number),
            companion=_clean_text(cells[3].text(separator=" ")) or None,
            similar=_clean_text(cells[4].text(separator=" ")) or None,
            sponsor=_clean_text(cells[5].text(separator=" ")) or None,
        ))
    items.sort(key=lambda item: _number_sort_key(item.number))
    return items


def parse_bill(item: IowaBillListItem, detail_html: str, actions_html: str, *, session: Session) -> Bill:
    number = _selected_bill(detail_html) or item.number
    title = item.title or _title(detail_html) or number
    context = " ".join(part for part in (title, item.companion, item.similar) if part)
    return Bill(
        jurisdiction=IowaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=title,
        subjects=_subjects(item),
        sponsors=parse_sponsors(item.sponsor),
        source_url=_billbook_url_from_item(item.detail_url, general_assembly=DEFAULT_GENERAL_ASSEMBLY, number=number),
        actions=parse_actions(actions_html, fallback_chamber=_chamber_for_number(number), source_url=item.detail_url),
        versions=parse_versions(detail_html),
        kind=classify_kind(context),
    )


def parse_actions(html: str, *, fallback_chamber: Chamber | None = None, source_url: str | None = None) -> list[BillAction]:
    tree = HTMLParser(html)
    actions: list[BillAction] = []
    for row in tree.css("table.billActionTable tbody tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        occurred_on = _parse_date(_clean_text(cells[0].text()))
        text = _clean_text(cells[1].text(separator=" "))
        if occurred_on is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(occurred_on, datetime.min.time()),
            chamber=_chamber_from_text(text) or fallback_chamber,
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

    def add(label: str, href: str | None) -> None:
        if not href:
            return
        url = urljoin(ROOT, href)
        lower = url.lower()
        path = lower.split("?", 1)[0]
        if "/docs/publications/" not in lower or not path.endswith((".pdf", ".html", ".htm", ".rtf")):
            return
        if url in seen:
            return
        seen.add(url)
        versions.append(BillVersion(
            label=_clean_text(label) or _label_from_url(url),
            source_url=url,
            format=_format_for_url(url),
        ))

    for match in re.finditer(r'\b(?:src|data)=["\']([^"\']*/docs/publications/[^"\']+)["\']', html, re.IGNORECASE):
        add("introduced html", match.group(1))
    for node in tree.css('[src*="/docs/publications/"]'):
        add("introduced html", node.attributes.get("src"))
    for link in tree.css('a[href*="/docs/publications/"]'):
        label = _clean_text(link.text()) or link.attributes.get("title") or link.attributes.get("alt") or ""
        add(label, link.attributes.get("href"))
    return versions


def parse_sponsors(value: str | None) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for raw in re.split(r",|;", value or ""):
        name = _clean_text(raw).strip(".")
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary"))
    return sponsors


def _subjects(item: IowaBillListItem) -> list[str]:
    subjects: list[str] = []
    for label, value in (("Companion", item.companion), ("Similar", item.similar)):
        if value:
            subjects.append(f"{label}: {value}")
    return subjects


def _title(html: str) -> str | None:
    tree = HTMLParser(html)
    for node in tree.css("h1, h2, .billTitle, div.billTitle"):
        text = _clean_text(node.text(separator=" "))
        if text and not text.lower().startswith("bill book"):
            return text
    return None


def _selected_bill(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first('input[name="selectedBill"]')
    value = node.attributes.get("value") if node else None
    return _clean_text(value) or None


def _all_bills_url(general_assembly: int) -> str:
    return f"{ROOT}/legislation/findLegislation/allbills?{urlencode({'ga': general_assembly})}"


def _billbook_url(general_assembly: int, number: str) -> str:
    return f"{ROOT}/legislation/BillBook?{urlencode({'ga': general_assembly, 'ba': number})}"


def _billbook_url_from_item(url: str, *, general_assembly: int, number: str) -> str:
    return url or _billbook_url(general_assembly, number)


def _detail_url(href: str, *, general_assembly: int, number: str) -> str:
    if href.startswith("http"):
        return href.replace(" ", "%20")
    return urljoin(ROOT, href).replace(" ", "%20") if "ba=" in href else _billbook_url(general_assembly, number)


def _first_link(node: Node) -> Node | None:
    return node.css_first("a[href]")


def _chamber_for_number(number: str) -> Chamber:
    prefix = _bill_prefix(number)
    if prefix.startswith("H"):
        return Chamber.LOWER
    if prefix.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_text(text: str) -> Chamber | None:
    lowered = text.lower()
    if re.search(r"\bhouse\b|\bh\.j\.", lowered):
        return Chamber.LOWER
    if re.search(r"\bsenate\b|\bs\.j\.", lowered):
        return Chamber.UPPER
    return None


def _bill_prefix(number: str) -> str:
    match = re.match(r"([A-Za-z]+)", number.strip())
    return match.group(1).upper() if match else ""


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Za-z]+)\s*(\d+)(.*)", number.strip())
    if not match:
        return (number, 0, "")
    return (match.group(1).upper(), int(match.group(2)), match.group(3))


def _ordinal(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _parse_date(value: str | None) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _format_for_url(url: str) -> str:
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".html", ".htm")):
        return "html"
    return "txt"


def _label_from_url(url: str) -> str:
    return quote(url.rsplit("/", 1)[-1].split("?", 1)[0]) or "document"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
