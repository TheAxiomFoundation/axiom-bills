"""Minnesota bill scraper.

The Minnesota Revisor publishes bill search/status pages as official
HTML. There is no documented JSON API for this prototype, so we parse
the current search table and individual bill status pages.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

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

ROOT = "https://www.revisor.mn.gov"
SEARCH_URL = f"{ROOT}/revisor/pages/search_status/"
CT = ZoneInfo("America/Chicago")

BILL_IN_PATH_RE = re.compile(r"/bills/\d{2}/\d{4}/\d+/([HS]F)/(\d+)/?", re.IGNORECASE)
BILL_NUMBER_RE = re.compile(r"\b([HS]F)\s*0*(\d+)\b", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
ACTION_COMPACT_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$")


class MinnesotaScraper(BillScraper):
    jurisdiction = "us-mn"
    source_name = "revisor.mn.gov"
    min_interval_per_host = 1.5

    def scrape(self) -> ScrapeResult:
        session = _current_session()
        bills: list[Bill] = []
        for url in self._list_bill_urls():
            html = self.http.get(url).text
            bill = parse_bill_page(html, url=url)
            if bill is None:
                continue
            bills.append(bill)
            if self.limit is not None and len(bills) >= self.limit:
                break
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session,
            bills=bills,
        )

    def _list_bill_urls(self):
        html = self.http.get(SEARCH_URL).text
        urls = parse_search_bill_urls(html)
        for url in urls:
            yield url
            if self.limit is not None and urls.index(url) + 1 >= self.limit:
                return


def _current_session() -> Session:
    today = datetime.now(tz=CT).date()
    start_year = today.year if today.year % 2 == 1 else today.year - 1
    legislature = 93 + (start_year - 2023) // 2
    return Session(
        name=f"{legislature}th Legislature ({start_year} - {start_year + 1})",
        start_date=date(start_year, 1, 1),
        end_date=date(start_year + 1, 12, 31),
        is_current=True,
    )


def parse_search_bill_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    urls: list[str] = []
    seen: set[str] = set()
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        if not _is_bill_status_href(href):
            continue
        url = urljoin(ROOT, href)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _is_bill_status_href(href: str) -> bool:
    if "/versions/" in href or href.lower().endswith((".pdf", "/pdf/")):
        return False
    if BILL_IN_PATH_RE.search(href):
        return True
    if "status_detail.php" not in href:
        return False
    query = parse_qs(urlparse(href).query)
    value = (query.get("f") or [""])[0]
    return bool(BILL_NUMBER_RE.search(value))


def parse_bill_page(html: str, *, url: str) -> Bill | None:
    tree = HTMLParser(html)
    lines = _text_lines(tree)
    number = _bill_number(lines, url)
    if number is None:
        return None
    title = _description(lines)
    session_name = _session_name(lines) or _current_session().name
    authors = _authors(lines)
    actions = _actions(lines, number)
    versions = _versions(tree, number)

    return Bill(
        jurisdiction=MinnesotaScraper.jurisdiction,
        session_name=session_name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=authors,
        source_url=url,
        actions=actions,
        versions=versions,
        kind=classify_kind(title),
    )


def _text_lines(tree: HTMLParser) -> list[str]:
    root = tree.body or tree.root
    text = root.text(separator="\n")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _bill_number(lines: list[str], url: str) -> str | None:
    match = BILL_IN_PATH_RE.search(url)
    if match:
        return f"{match.group(1).upper()}{int(match.group(2))}"
    query = parse_qs(urlparse(url).query)
    value = (query.get("f") or [""])[0]
    match = BILL_NUMBER_RE.search(value)
    if match:
        return f"{match.group(1).upper()}{int(match.group(2))}"
    for line in lines[:120]:
        match = BILL_NUMBER_RE.search(line)
        if match:
            return f"{match.group(1).upper()}{int(match.group(2))}"
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("SF") else Chamber.LOWER


def _session_name(lines: list[str]) -> str | None:
    text = "\n".join(lines[:80])
    match = re.search(r"(\d+(?:st|nd|rd|th) Legislature \(\d{4}\s*-\s*\d{4}\))", text)
    return match.group(1) if match else None


def _description(lines: list[str]) -> str | None:
    block = _block(lines, "Description", ("Authors", "Actions", "Bill Text Versions"))
    return " ".join(block).strip() or None


def _authors(lines: list[str]) -> list[Sponsor]:
    block = _block(lines, "Authors", ("Actions", "Bill Text Versions", "House Actions"))
    sponsors: list[Sponsor] = []
    for line in block:
        if line.startswith("*"):
            line = line.lstrip("* ")
        name = line.strip(" ;")
        if not name or name.lower().startswith("show"):
            continue
        sponsors.append(Sponsor(name=name, role="author"))
    return sponsors


def _actions(lines: list[str], number: str) -> list[BillAction]:
    chamber = _chamber_for_number(number)
    actions_block = _block(lines, "Actions", ("House Actions", "Senate Actions", "Bill Text Versions"))
    if not actions_block:
        actions_block = _block(lines, "House", ("Senate", "Bill Text Versions"))
    actions: list[BillAction] = []
    i = 0
    while i < len(actions_block):
        line = actions_block[i]
        compact = ACTION_COMPACT_RE.match(line)
        if compact:
            action_text = compact.group(2).strip()
            actions.append(_action(compact.group(1), chamber, action_text))
            i += 1
            continue
        if DATE_RE.match(line) and i + 1 < len(actions_block):
            action_text = actions_block[i + 1].strip()
            actions.append(_action(line, chamber, action_text))
            i += 2
            continue
        i += 1
    return actions


def _action(raw_date: str, chamber: Chamber, text: str) -> BillAction:
    return BillAction(
        occurred_at=datetime.strptime(raw_date, "%m/%d/%Y").replace(tzinfo=CT),
        chamber=chamber,
        action_text=text,
        normalized_status=match_first(text, PATTERNS),
    )


def _versions(tree: HTMLParser, number: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        text = node.text(strip=True)
        if not href or "/versions/" not in href and "text.php" not in href:
            continue
        if not href.lower().endswith(("/pdf/", ".pdf")) and "format=pdf" not in href:
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        label = text or f"{number} version {len(versions) + 1}"
        versions.append(BillVersion(label=label, source_url=url, format="pdf"))
    return versions


def _block(lines: list[str], start: str, end_prefixes: tuple[str, ...]) -> list[str]:
    start_index = None
    for i, line in enumerate(lines):
        if line == start or line.startswith(f"{start} "):
            start_index = i + 1
            break
    if start_index is None:
        return []
    out: list[str] = []
    for line in lines[start_index:]:
        if any(line == prefix or line.startswith(f"{prefix} ") for prefix in end_prefixes):
            break
        if line in {"---"}:
            continue
        out.append(line)
    return out
