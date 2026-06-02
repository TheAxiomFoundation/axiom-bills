"""Virginia bill scraper.

Virginia LIS exposes public JSON endpoints used by its React app. The
scraper reads the default session, fetches the session legislation list,
and then fetches per-bill events and text versions.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Any

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

ROOT = "https://lis.virginia.gov"
API_HEADERS = {
    "WebAPIKey": "FCE351B6-9BD8-46E0-B18F-5572F4CCA5B9",
    "content-type": "application/json; charset=utf-8",
}


class VirginiaScraper(BillScraper):
    jurisdiction = "us-va"
    source_name = "lis.virginia.gov official Virginia Legislative Information System"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session_info = self.http.get_json(f"{ROOT}/Session/api/getDefaultSessionAsync", headers=API_HEADERS)["Sessions"][0]
        session = session_from_api(session_info)
        list_payload = self.http.post(
            f"{ROOT}/AdvancedLegislationSearch/api/GetLegislationListAsync",
            headers=API_HEADERS,
            json={"SessionID": session_info["SessionID"]},
        ).json()
        raw_bills = _dedupe_bills(sorted(
            list_payload.get("Legislations", []),
            key=lambda bill: _number_sort_key(_format_number(bill.get("LegislationNumber"))),
        ))
        if self.limit is not None:
            raw_bills = raw_bills[:self.limit]
        bills: list[Bill] = []
        for raw_bill in raw_bills:
            legislation_id = int(raw_bill["LegislationID"])
            events = self.http.get_json(
                f"{ROOT}/LegislationEvent/api/GetLegislationEventByLegislationIDAsync/?legislationID={legislation_id}",
                headers=API_HEADERS,
            ).get("LegislationEvents", [])
            versions = self.http.get_json(
                f"{ROOT}/LegislationVersion/api/GetLegislationVersionbyLegislationIDAsync?legislationID={legislation_id}",
                headers=API_HEADERS,
            ).get("LegislationsVersion", [])
            bills.append(parse_bill(raw_bill, events=events, versions=versions, session=session))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_from_api(raw: dict[str, Any]) -> Session:
    events = raw.get("SessionEvents", [])
    start = _event_date(events, "Session Start")
    end = _event_date(events, "Reconvene") or _event_date(events, "Adjournment")
    return Session(
        name=f"{raw.get('SessionYear')} Virginia {raw.get('DisplayName', 'Regular Session')}",
        start_date=start,
        end_date=end,
        is_current=bool(raw.get("IsDefault")) and (end is None or end >= date.today()),
    )


def parse_bill(
    raw_bill: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    session: Session,
) -> Bill:
    number = _format_number(raw_bill.get("LegislationNumber"))
    title = _clean_text(raw_bill.get("Description")) or _clean_text(raw_bill.get("LegislationTitle")) or number
    summary = _html_to_text(raw_bill.get("LegislationSummary")) or title
    return Bill(
        jurisdiction=VirginiaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_from_code(raw_bill.get("ChamberCode")),
        number=number,
        title=title,
        summary=summary,
        subjects=[],
        sponsors=parse_sponsors(raw_bill),
        source_url=f"{ROOT}/bill-details/{raw_bill.get('SessionCode')}/{raw_bill.get('LegislationNumber')}",
        actions=parse_actions(events),
        versions=parse_versions(versions),
        kind=classify_kind(" ".join([title, summary[:500], str(raw_bill.get("LegislationClass") or "")])),
    )


def parse_sponsors(raw_bill: dict[str, Any]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for patron in sorted(raw_bill.get("Patrons") or [], key=lambda item: item.get("Sequence") or 0):
        name = _clean_text(patron.get("MemberDisplayName")) or _clean_text(patron.get("PatronDisplayName"))
        if not name or name in seen:
            continue
        seen.add(name)
        role = _clean_text(patron.get("Name")) or ("primary" if not sponsors else "cosponsor")
        sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def parse_actions(events: list[dict[str, Any]]) -> list[BillAction]:
    actions: list[BillAction] = []
    for event in events:
        occurred_at = _parse_datetime(event.get("EventDate"))
        text = _clean_text(event.get("Description"))
        if occurred_at is None or not text:
            continue
        status_text = " ".join(part for part in (text, event.get("Status")) if part)
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_code(event.get("ChamberCode")),
            action_text=text,
            normalized_status=match_first(status_text, PATTERNS),
            source_url=f"{ROOT}/bill-details/{event.get('SessionCode') or ''}/{event.get('LegislationNumber')}",
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(versions: list[dict[str, Any]]) -> list[BillVersion]:
    out: list[BillVersion] = []
    seen: set[str] = set()
    for version in versions:
        label = _clean_text(version.get("Description")) or _clean_text(version.get("Version")) or "Bill text"
        for key in ("PdfFile", "PDFFile", "HtmlFile", "HTMLFile"):
            for file_info in version.get(key) or []:
                url = file_info.get("FileURL")
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append(BillVersion(label=label, source_url=url, format=_format_from_url(url)))
    return out


def _dedupe_bills(raw_bills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_bill in raw_bills:
        number = _format_number(raw_bill.get("LegislationNumber"))
        if not number or number in seen:
            continue
        seen.add(number)
        unique.append(raw_bill)
    return unique


def _event_date(events: list[dict[str, Any]], name: str) -> date | None:
    for event in events:
        if event.get("DisplayName") == name:
            parsed = _parse_datetime(event.get("ActualDate"))
            return parsed.date() if parsed else None
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_number(value: object) -> str:
    match = re.search(r"\b(HB|SB|HJ|SJ|HR|SR)\s*0*(\d+)\b", str(value or "").upper())
    if match is None:
        return ""
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_from_code(code: object) -> Chamber:
    if code == "H":
        return Chamber.LOWER
    if code == "S":
        return Chamber.UPPER
    return Chamber.JOINT


def _html_to_text(value: object) -> str:
    if not value:
        return ""
    return _clean_text(HTMLParser(unescape(str(value))).text())


def _format_from_url(url: str) -> str:
    suffix = url.rsplit(".", 1)[-1].lower()
    return "html" if suffix == "html" else suffix


def _number_sort_key(number: str) -> tuple[int, int]:
    prefix, _, digits = number.partition(" ")
    order = {"HB": 0, "SB": 1, "HJ": 2, "SJ": 3, "HR": 4, "SR": 5}.get(prefix.upper(), 9)
    return order, int(digits) if digits.isdigit() else 0


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
