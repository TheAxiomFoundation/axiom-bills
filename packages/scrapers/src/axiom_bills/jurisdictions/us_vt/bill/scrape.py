"""Vermont bill scraper.

The Vermont Legislature publishes public JSON feeds behind its bill list
and bill detail DataTables. Its documented API requires a key, so this
scraper uses those same public official list/status endpoints and bill
status pages.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
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

ROOT = "https://legislature.vermont.gov"
ET = ZoneInfo("America/New_York")


class VermontScraper(BillScraper):
    jurisdiction = "us-vt"
    source_name = "legislature.vermont.gov official bill status pages"
    min_interval_per_host = 0.2

    def __init__(self, *, biennium: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.biennium = biennium or _current_biennium()

    def scrape(self) -> ScrapeResult:
        session = session_from_biennium(self.biennium)
        rows = _dedupe_rows([
            *self.http.get_json(f"{ROOT}/bill/loadAllBillsByChamber/{self.biennium}/H").get("data", []),
            *self.http.get_json(f"{ROOT}/bill/loadAllBillsByChamber/{self.biennium}/S").get("data", []),
        ])
        rows.sort(key=lambda row: _number_sort_key(str(row.get("BillNumber") or "")))
        if self.limit is not None:
            rows = rows[:self.limit]

        bills: list[Bill] = []
        for row in rows:
            number = _clean_text(row.get("BillNumber"))
            if not number:
                continue
            detail_html = self.http.get(f"{ROOT}/bill/status/{self.biennium}/{number}").text
            detail = parse_detail_page(detail_html)
            status_id = detail.get("status_id")
            status_rows: list[dict[str, Any]] = []
            if status_id:
                status_rows = self.http.get_json(
                    f"{ROOT}/bill/loadBillDetailedStatus/{self.biennium}/{status_id}"
                ).get("data", [])
            version_rows = self.http.post(
                f"{ROOT}/bill/loadTextVersionsByBill/{self.biennium}/{number}"
            ).json().get("data", {})
            bills.append(parse_bill(
                row,
                detail=detail,
                status_rows=status_rows,
                version_rows=version_rows,
                session=session,
                biennium=self.biennium,
            ))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_from_biennium(biennium: str) -> Session:
    end_year = int(biennium)
    start_year = end_year - 1
    return Session(
        name=f"{start_year}-{end_year} Vermont Regular Session",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=biennium == _current_biennium(),
    )


def parse_bill(
    row: dict[str, Any],
    *,
    detail: dict[str, Any],
    status_rows: list[dict[str, Any]],
    version_rows: dict[str, Any],
    session: Session,
    biennium: str,
) -> Bill:
    number = _clean_text(row.get("BillNumber")) or _clean_text(detail.get("number")) or ""
    title = _clean_text(detail.get("title")) or _clean_text(row.get("Title")) or number
    summary = _clean_text(" ".join(str(row.get(key) or "") for key in ("Title1", "Title2", "Title3", "Title4"))) or title
    versions = parse_versions(version_rows)
    act_link = _clean_text(row.get("ActLink"))
    if act_link:
        versions.append(BillVersion(
            label=f"Act {row.get('ActNo')}",
            source_url=_absolute_url(act_link),
            format=_format_from_url(act_link),
        ))
    return Bill(
        jurisdiction=VermontScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(row.get("Body"), number),
        number=number,
        title=title,
        summary=summary,
        subjects=[],
        sponsors=parse_sponsors(detail.get("sponsors_text")),
        source_url=f"{ROOT}/bill/status/{biennium}/{number}",
        actions=parse_actions(status_rows),
        versions=_dedupe_versions(versions),
        kind=classify_kind(title),
    )


def parse_detail_page(html: str) -> dict[str, Any]:
    parser = HTMLParser(html)
    title = parser.css_first(".bill-title .charge")
    number = parser.css_first(".bill-title h1")
    sponsors = parser.css_first("#bill-sponsors")
    sponsor_links = [
        _clean_text(node.text())
        for node in parser.css(".summary-table .item-list a")
    ]
    sponsor_links = [name for name in sponsor_links if name]
    location = parser.css_first("#bill-location")
    last_action = parser.css_first("#bill-last-recorded-action")
    status_id = None
    match = re.search(r"loadBillDetailedStatus/\d+/(\d+)", html)
    if match:
        status_id = match.group(1)
    return {
        "number": _html_to_text(number.html if number else ""),
        "title": _html_to_text(title.html if title else ""),
        "sponsors_text": "\n".join(sponsor_links) if sponsor_links else _html_to_text(sponsors.html if sponsors else ""),
        "location": _html_to_text(location.html if location else ""),
        "last_action": _html_to_text(last_action.html if last_action else ""),
        "status_id": status_id,
    }


def parse_sponsors(raw: object) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    text = re.sub(r"\s+(?=(?:Rep|Sen)\.\s)", "\n", str(raw or ""))
    for part in re.split(r"\n| {2,}", text):
        name = _clean_text(part)
        if not name or name in seen:
            continue
        if name.lower() in {"committee sponsors", "lead sponsors", "co-sponsors"}:
            continue
        seen.add(name)
        sponsors.append(Sponsor(name=name, role="primary" if not sponsors else "cosponsor"))
    return sponsors


def parse_actions(rows: list[dict[str, Any]]) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        occurred_at = _parse_date(row.get("StatusDate") or row.get("SessionMeetingDate"))
        text = _html_to_text(row.get("FullStatus")) or _clean_text(row.get("FullStatus1"))
        if occurred_at is None or not text:
            continue
        status_text = " ".join(
            str(part) for part in (text, row.get("keywords"), row.get("Location")) if part
        )
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber(row.get("ChamberCode"), ""),
            action_text=text,
            normalized_status=match_first(status_text, PATTERNS),
            source_url=_absolute_url(row["Url"]) if row.get("Url") else None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(rows: dict[str, Any]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    for label, row in rows.items():
        if not isinstance(row, dict) or not row.get("Url"):
            continue
        display = _clean_text(row.get("DisplayName")) or _clean_text(label) or "Bill text"
        url = _absolute_url(str(row["Url"]))
        versions.append(BillVersion(label=display, source_url=url, format=_format_from_url(url)))
    return _dedupe_versions(versions)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        number = _clean_text(row.get("BillNumber"))
        if not number or number in seen:
            continue
        seen.add(number)
        out.append(row)
    return out


def _dedupe_versions(versions: list[BillVersion]) -> list[BillVersion]:
    out: list[BillVersion] = []
    seen: set[str] = set()
    for version in versions:
        if version.source_url in seen:
            continue
        seen.add(version.source_url)
        out.append(version)
    return out


def _chamber(body: object, number: str) -> Chamber:
    text = str(body or "").upper()
    prefix = number.upper()
    if text == "H" or prefix.startswith(("H.", "HR")):
        return Chamber.LOWER
    if text == "S" or prefix.startswith(("S.", "SR", "PR")):
        return Chamber.UPPER
    return Chamber.JOINT


def _parse_date(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%m/%d/%Y").replace(tzinfo=ET)
    except ValueError:
        return None


def _html_to_text(raw: object) -> str:
    if not raw:
        return ""
    return _clean_text(HTMLParser(unescape(str(raw))).text()) or ""


def _clean_text(raw: object) -> str | None:
    if raw is None:
        return None
    text = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    return text or None


def _absolute_url(url: str) -> str:
    return urljoin(ROOT + "/", url)


def _format_from_url(url: str) -> str:
    suffix = url.split("?", 1)[0].rsplit(".", 1)[-1].lower()
    return suffix if suffix in {"html", "pdf", "xml", "txt"} else "html"


def _number_sort_key(number: str) -> tuple[int, int, str]:
    match = re.match(r"([A-Z]+)\.?\s*(\d+)", number.upper())
    if not match:
        return 9, 0, number
    order = {
        "H": 0,
        "S": 1,
        "HR": 2,
        "SR": 3,
        "JRH": 4,
        "JRS": 5,
        "PR": 6,
    }.get(match.group(1), 8)
    return order, int(match.group(2)), number


def _current_biennium() -> str:
    year = datetime.now(tz=ET).year
    return str(year if year % 2 == 0 else year + 1)
