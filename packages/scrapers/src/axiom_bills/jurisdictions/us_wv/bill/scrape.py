"""West Virginia bill scraper.

West Virginia's legacy bill status pages are official, static HTML pages
with all-bills and complete-history views. The history page contains
sponsors, text versions, code affected, subjects, and action rows.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
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

ROOT = "https://www.wvlegislature.gov/Bill_Status"
HOST = "https://www.wvlegislature.gov"
ET = ZoneInfo("America/New_York")


class WestVirginiaScraper(BillScraper):
    jurisdiction = "us-wv"
    source_name = "wvlegislature.gov official bill status pages"
    min_interval_per_host = 0.2

    def __init__(self, *, year: int | None = None, session_type: str = "RS", limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year or datetime.now(tz=ET).year
        self.session_type = session_type.upper()

    def scrape(self) -> ScrapeResult:
        rows = parse_bill_list(self.http.get(
            f"{ROOT}/Bills_all_bills.cfm?btype=bill&sessiontype={self.session_type}&year={self.year}"
        ).text)
        if self.limit is not None:
            rows = rows[:self.limit]
        session = session_from_year(self.year, self.session_type)
        bills = [
            parse_bill(row, self.http.get(urljoin(ROOT + "/", row["href"])).text, session=session)
            for row in rows
        ]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_from_year(year: int, session_type: str) -> Session:
    name = "Regular Session" if session_type.upper() == "RS" else session_type.upper()
    return Session(
        name=f"{year} West Virginia {name}",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now(tz=ET).year,
    )


def parse_bill_list(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    parser = HTMLParser(html)
    for tr in parser.css("table#results tr"):
        cells = tr.css("td")
        if len(cells) < 3:
            continue
        link = cells[0].css_first("a")
        number = _clean_text(link.text() if link else cells[0].text())
        if not re.match(r"^[SH]B\s+\d+$", number):
            continue
        rows.append({
            "number": number,
            "href": link.attributes.get("href", "") if link else "",
            "title": _clean_text(cells[1].text()),
            "status": _clean_text(cells[2].text()),
        })
    return rows


def parse_bill(row: dict[str, str], html: str, *, session: Session) -> Bill:
    details = parse_details(html)
    title = details.get("SUMMARY") or row.get("title") or row["number"]
    summary = details.get("LONG_TITLE") or title
    return Bill(
        jurisdiction=WestVirginiaScraper.jurisdiction,
        session_name=session.name,
        chamber=Chamber.UPPER if row["number"].startswith("SB") else Chamber.LOWER,
        number=row["number"],
        title=title,
        summary=summary,
        subjects=details.get("SUBJECTS_LIST", []),
        sponsors=parse_sponsors(details),
        source_url=urljoin(ROOT + "/", row["href"]),
        actions=parse_actions(html),
        versions=parse_versions(html),
        kind=classify_kind(title),
    )


def parse_details(html: str) -> dict[str, Any]:
    parser = HTMLParser(html)
    details: dict[str, Any] = {}
    for tr in parser.css("table.bstat tr"):
        cells = tr.css("td")
        if len(cells) < 2:
            continue
        label = _clean_text(cells[0].text()).rstrip(":")
        value = _clean_text(cells[1].text())
        if not label:
            continue
        details[label] = value
        if label in {"LEAD SPONSOR", "SPONSORS", "SUBJECTS"}:
            details[f"{label}_LIST"] = [_clean_text(a.text()) for a in cells[1].css("a") if _clean_text(a.text())]
    long_title = re.search(r"A BILL to .*?(?=<)", html, re.IGNORECASE | re.DOTALL)
    if long_title:
        details["LONG_TITLE"] = _clean_text(HTMLParser(long_title.group(0)).text())
    return details


def parse_sponsors(details: dict[str, Any]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for name in details.get("LEAD SPONSOR_LIST", []):
        if name not in seen:
            seen.add(name)
            sponsors.append(Sponsor(name=name, role="primary"))
    for name in details.get("SPONSORS_LIST", []):
        if name not in seen:
            seen.add(name)
            sponsors.append(Sponsor(name=name, role="cosponsor"))
    return sponsors


def parse_actions(html: str) -> list[BillAction]:
    parser = HTMLParser(html)
    actions: list[BillAction] = []
    for tr in parser.css("tr.actionrows"):
        cells = tr.css("td")
        if len(cells) < 3:
            continue
        chamber = _chamber(_clean_text(cells[0].text()))
        text = _clean_text(cells[1].text())
        occurred_at = _parse_date(cells[2].text())
        if not text or occurred_at is None:
            continue
        link = cells[1].css_first("a")
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=chamber,
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=urljoin(HOST, link.attributes["href"]) if link and link.attributes.get("href") else None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(html: str) -> list[BillVersion]:
    parser = HTMLParser(html)
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for link in parser.css("a"):
        title = link.attributes.get("title", "")
        href = link.attributes.get("href", "")
        if " - " not in title or "Bill" not in title or not href:
            continue
        fmt = "html" if "HTML -" in title else link.attributes.get("data-type") or _format_from_url(href)
        if fmt not in {"html", "pdf", "docx"}:
            continue
        label = _clean_text(title.split(" - ", 2)[1])
        url = urljoin(HOST, href)
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(label=label, source_url=url, format="html" if fmt == "htm" else fmt))
    return versions


def _chamber(raw: str) -> Chamber | None:
    if raw.upper().startswith("S"):
        return Chamber.UPPER
    if raw.upper().startswith("H"):
        return Chamber.LOWER
    return None


def _parse_date(raw: object) -> datetime | None:
    text = _clean_text(str(raw))
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%y").replace(tzinfo=ET)
    except ValueError:
        return None


def _format_from_url(url: str) -> str:
    suffix = url.rsplit(".", 1)[-1].lower()
    return "html" if suffix in {"htm", "html"} else suffix


def _clean_text(raw: object) -> str:
    return re.sub(r"\s+", " ", str(raw or "").replace("\xa0", " ")).strip()
