"""Wisconsin bill scraper.

Wisconsin publishes official proposal list and proposal history pages on
docs.legis.wisconsin.gov. The bill text endpoint also exposes JSON, but
the current action history is embedded in the proposal page, so this
scraper parses those official pages directly.
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

ROOT = "https://docs.legis.wisconsin.gov"
CT = ZoneInfo("America/Chicago")
BILL_URL_RE = re.compile(r"^/(\d{4})/proposals/reg/(sen|asm)/bill/([as]b\d+)$", re.IGNORECASE)


class WisconsinScraper(BillScraper):
    jurisdiction = "us-wi"
    source_name = "docs.legis.wisconsin.gov"
    min_interval_per_host = 0.5

    def __init__(self, *, biennium: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.biennium = biennium or _current_biennium()

    def scrape(self) -> ScrapeResult:
        bills: list[Bill] = []
        for url in self._list_bill_urls():
            html = self.http.get(url).text
            bill = parse_bill_page(html, url=url)
            if bill is not None:
                bills.append(bill)
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda b: b.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session_for_biennium(self.biennium),
            bills=bills,
        )

    def _list_bill_urls(self) -> list[str]:
        urls: list[str] = []
        for chamber in ("sen", "asm"):
            html = self.http.get(f"{ROOT}/{self.biennium}/proposals/reg/{chamber}/bill").text
            urls.extend(parse_list_bill_urls(html))
        seen: set[str] = set()
        out: list[str] = []
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
        return out


def session_for_biennium(biennium: int) -> Session:
    return Session(
        name=f"{biennium}-{biennium + 1} Wisconsin Legislature",
        start_date=date(biennium, 1, 1),
        end_date=date(biennium + 1, 12, 31),
        is_current=True,
    )


def parse_list_bill_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    urls: list[str] = []
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        if BILL_URL_RE.match(href):
            urls.append(urljoin(ROOT, href))
    return urls


def parse_bill_page(html: str, *, url: str) -> Bill | None:
    tree = HTMLParser(html)
    number = _number(url)
    if number is None:
        return None
    title = _title(tree) or number
    biennium = _biennium(url)
    actions = _actions(tree, number)
    versions = _versions(tree, biennium, number)
    return Bill(
        jurisdiction=WisconsinScraper.jurisdiction,
        session_name=session_for_biennium(biennium).name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=_summary(tree),
        subjects=[],
        sponsors=_sponsors(tree),
        source_url=url,
        actions=actions,
        versions=versions,
        kind=classify_kind(title),
    )


def _number(url: str) -> str | None:
    match = BILL_URL_RE.search(url.replace(ROOT, ""))
    return match.group(3).upper() if match else None


def _biennium(url: str) -> int:
    match = BILL_URL_RE.search(url.replace(ROOT, ""))
    return int(match.group(1)) if match else _current_biennium()


def _title(tree: HTMLParser) -> str | None:
    for node in tree.css("p"):
        text = _clean_text(node.text())
        if text and text.startswith("An Act Relating to:"):
            return text.replace("An Act Relating to:", "Relating to:", 1).strip()
        if text and text.startswith("Relating to:"):
            return text
    title = tree.css_first("title")
    return _clean_text(title.text()) if title else None


def _summary(tree: HTMLParser) -> str | None:
    text_node = tree.css_first(".proposalText")
    if text_node:
        text = _clean_text(text_node.text())
        if text:
            return text[:2000]
    for node in tree.css("p"):
        text = _clean_text(node.text())
        if text and text.startswith("An Act Relating to:"):
            return text
    return None


def _actions(tree: HTMLParser, number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in tree.css("tr.historyRow"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        when = _parse_history_date(_clean_text(cells[0].text()))
        text = _clean_text(cells[1].text())
        if when is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=when,
            chamber=_chamber_from_history(cells[0].text()) or _chamber_for_number(number),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _sponsors(tree: HTMLParser) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    first_row = tree.css_first("tr.historyRow")
    if first_row is None:
        return sponsors
    cells = first_row.css("td")
    if len(cells) < 2:
        return sponsors
    text = _clean_text(cells[1].text()) or ""
    if not text.startswith("Introduced by "):
        return sponsors
    names = re.sub(r"^Introduced by (Senators|Representatives) ", "", text)
    names = re.split(r",| and ", names)
    for name in names:
        cleaned = name.strip()
        if cleaned:
            sponsors.append(Sponsor(name=cleaned, role="sponsor"))
    return sponsors


def _versions(tree: HTMLParser, biennium: int, number: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for node in tree.css("a"):
        href = node.attributes.get("href") or ""
        text = _clean_text(node.text()) or ""
        if "/document/proposaltext/" not in href and not href.endswith((".pdf", ".html")):
            continue
        if number not in href.upper():
            continue
        source_url = urljoin(ROOT, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        label = text or "Bill Text"
        versions.append(BillVersion(
            label=label,
            source_url=source_url,
            format=_format(source_url),
        ))
    if not versions:
        path = f"{ROOT}/document/proposaltext/{biennium}/REG/{number}"
        versions.append(BillVersion(label="Bill Text", source_url=path, format="html"))
    return versions


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("SB") else Chamber.LOWER


def _chamber_from_history(raw: str) -> Chamber | None:
    if "Sen." in raw:
        return Chamber.UPPER
    if "Asm." in raw:
        return Chamber.LOWER
    return None


def _parse_history_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if not match:
        return None
    month, day, year = (int(part) for part in match.groups())
    return datetime(year, month, day, tzinfo=CT)


def _format(url: str) -> str:
    suffix = url.rsplit(".", 1)[-1].lower()
    return suffix if suffix in {"html", "pdf", "xml", "txt"} else "html"


def _clean_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = " ".join(raw.split())
    return cleaned or None


def _current_biennium() -> int:
    year = datetime.now(tz=CT).year
    return year if year % 2 == 1 else year - 1
