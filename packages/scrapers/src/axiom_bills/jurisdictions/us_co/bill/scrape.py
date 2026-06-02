"""Colorado bill scraper.

Colorado does not publish a documented bill API. The official General
Assembly site does expose stable bill-search and per-bill HTML pages,
so this scraper treats those pages as the source API and parses only the
semantic text/link structure we need.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin
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

ROOT = "https://leg.colorado.gov"
SEARCH_URL = f"{ROOT}/bills/bill-search"
MT = ZoneInfo("America/Denver")

BILL_LINK_RE = re.compile(r"^/bills/([hs]b\d{2}-\d+)$", re.IGNORECASE)
BILL_NUMBER_RE = re.compile(r"\b([HS]B)(\d{2})-(\d+)\b", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
ACTION_ROW_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(House|Senate|Joint|Executive)\s+(.+)$",
    re.IGNORECASE,
)


class ColoradoScraper(BillScraper):
    jurisdiction = "us-co"
    source_name = "leg.colorado.gov"
    min_interval_per_host = 1.5

    def scrape(self) -> ScrapeResult:
        session_year = _current_session_year()
        session = Session(
            name=f"{session_year} Regular Session",
            start_date=date(session_year, 1, 1),
            end_date=date(session_year, 12, 31),
            is_current=True,
        )
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
        seen: set[str] = set()
        page = 0
        while True:
            params = {"page": page} if page else None
            html = self.http.get(SEARCH_URL, params=params).text
            urls = parse_search_bill_urls(html)
            new_urls = [u for u in urls if u not in seen]
            if not new_urls:
                return
            for url in new_urls:
                seen.add(url)
                yield url
                if self.limit is not None and len(seen) >= self.limit:
                    return
            page += 1


def _current_session_year() -> int:
    return datetime.now(tz=MT).year


def parse_search_bill_urls(html: str) -> list[str]:
    """Return official bill detail URLs from a Colorado search page."""
    tree = HTMLParser(html)
    urls: list[str] = []
    seen: set[str] = set()
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        match = BILL_LINK_RE.match(href)
        if not match:
            continue
        url = urljoin(ROOT, href)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_bill_page(html: str, *, url: str) -> Bill | None:
    tree = HTMLParser(html)
    lines = _text_lines(tree)
    number = _bill_number(lines, url)
    if number is None:
        return None
    title = _title(lines, number)
    session_name = _session_name(lines) or f"{_current_session_year()} Regular Session"
    subjects = _subjects(lines)
    summary = _summary(lines)
    sponsors = _sponsors(lines)
    actions = _actions(lines)
    versions = _versions(tree)

    return Bill(
        jurisdiction=ColoradoScraper.jurisdiction,
        session_name=session_name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=summary,
        subjects=subjects,
        sponsors=sponsors,
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
    for line in lines[:120]:
        match = BILL_NUMBER_RE.search(line)
        if match:
            return _normalize_bill_number(match.group(0))
    match = BILL_NUMBER_RE.search(url)
    return _normalize_bill_number(match.group(0)) if match else None


def _normalize_bill_number(raw: str) -> str:
    match = BILL_NUMBER_RE.search(raw)
    if not match:
        return raw.upper()
    return f"{match.group(1).upper()}{match.group(2)}-{match.group(3)}"


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("SB") else Chamber.LOWER


def _title(lines: list[str], number: str) -> str | None:
    for i, line in enumerate(lines):
        if _normalize_bill_number(line) != number:
            continue
        for candidate in lines[i + 1:i + 8]:
            if candidate not in {"Bill", "Type", "Session"} and not candidate.startswith("Type "):
                return candidate.lstrip("# ").strip()
    return None


def _session_name(lines: list[str]) -> str | None:
    full_text = "\n".join(lines)
    match = re.search(r"Session\s+(\d{4}\s+(?:Regular|Extraordinary)\s+Session)", full_text)
    return match.group(1) if match else None


def _subjects(lines: list[str]) -> list[str]:
    block = _block(lines, "Subjects", ("Bill Summary:", "Recent Bill", "Concerning "))
    if not block:
        return []
    raw = "  ".join(block)
    out = [part.strip(" *") for part in re.split(r"\s{2,}|\s+\*\s+", raw) if part.strip(" *")]
    return [s for s in out if not s.startswith("Concerning ")]


def _summary(lines: list[str]) -> str | None:
    block = _block(lines, "Bill Summary:", ("Prime Sponsors", "Committees", "Share:"))
    cleaned: list[str] = []
    for line in block:
        if line.startswith("(Note:"):
            break
        cleaned.append(line)
    return " ".join(cleaned).strip() or None


def _sponsors(lines: list[str]) -> list[Sponsor]:
    block = _block(lines, "Prime Sponsors", ("Committees", "Share:", "Status"))
    sponsors: list[Sponsor] = []
    for line in block:
        if line.startswith(("Representative ", "Senator ")):
            sponsors.append(Sponsor(name=line, role="primary"))
    if sponsors:
        return sponsors

    # Fallback for pages where only abbreviated sponsors are present.
    block = _block(lines, "Sponsors", ("Quick Links",))
    for line in block:
        if line.startswith(("Rep. ", "Sen. ")):
            sponsors.append(Sponsor(name=line, role="sponsor"))
    return sponsors


def _actions(lines: list[str]) -> list[BillAction]:
    block = _bill_history_block(lines)
    actions: list[BillAction] = []
    i = 0
    while i < len(block):
        line = block[i]
        row = ACTION_ROW_RE.match(line)
        if row:
            when = _parse_date(row.group(1))
            chamber = _chamber_for_location(row.group(2))
            text = row.group(3).strip()
            actions.append(BillAction(
                occurred_at=when,
                chamber=chamber,
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            ))
            i += 1
            continue
        if DATE_RE.match(line) and i + 2 < len(block):
            when = _parse_date(line)
            chamber = _chamber_for_location(block[i + 1])
            text = block[i + 2].strip()
            actions.append(BillAction(
                occurred_at=when,
                chamber=chamber,
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            ))
            i += 3
            continue
        i += 1
    return actions


def _bill_history_block(lines: list[str]) -> list[str]:
    start_index = None
    for i, line in enumerate(lines):
        if line.startswith("Bill history"):
            start_index = i + 1
            break
    if start_index is None:
        return _block(lines, "Date  Location  Action", ("Sponsors", "Quick Links"))

    out: list[str] = []
    for line in lines[start_index:]:
        if line.startswith(("Sponsors", "Quick Links")):
            break
        if line in {"Date", "Location", "Action"}:
            continue
        out.append(line)
    return out


def _parse_date(raw: str) -> datetime:
    return datetime.strptime(raw, "%m/%d/%Y").replace(tzinfo=MT)


def _chamber_for_location(raw: str) -> Chamber | None:
    value = raw.lower()
    if value.startswith("house"):
        return Chamber.LOWER
    if value.startswith("senate"):
        return Chamber.UPPER
    if value.startswith("joint"):
        return Chamber.JOINT
    if value.startswith("executive"):
        return Chamber.EXECUTIVE
    return None


def _versions(tree: HTMLParser) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        text = node.text(strip=True).lower()
        if "/bill_files/" not in href or "pdf" not in text:
            continue
        url = urljoin(ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=f"version-{len(versions) + 1}",
            source_url=url,
            format="pdf",
        ))
    return versions[:3]


def _block(lines: list[str], start: str, end_prefixes: tuple[str, ...]) -> list[str]:
    try:
        start_index = next(i for i, line in enumerate(lines) if line == start or line.startswith(start))
    except StopIteration:
        return []
    out: list[str] = []
    for line in lines[start_index + 1:]:
        if any(line.startswith(prefix) for prefix in end_prefixes):
            break
        out.append(line)
    return out
