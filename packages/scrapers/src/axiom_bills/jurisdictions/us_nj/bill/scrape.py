"""New Jersey bill scraper.

The New Jersey Legislature site is a Next.js app backed by first-party
JSON endpoints. This scraper uses the same official bill search and bill
detail endpoints exposed by the public site.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

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

ROOT = "https://www.njleg.state.nj.us"
PUB_ROOT = "https://pub.njleg.gov"
CURRENT_SESSION = 2026


class NewJerseyScraper(BillScraper):
    jurisdiction = "us-nj"
    source_name = "njleg.state.nj.us official New Jersey Legislature API"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session_year = self._current_session_year()
        session = session_for_year(session_year)
        bills: list[Bill] = []
        for raw_bill in self._all_bills(session_year):
            if self.limit is not None and len(bills) >= self.limit:
                break
            number = _clean_text(raw_bill.get("Bill"))
            if not number or not _allowed_bill_number(number):
                continue
            bills.append(self._bill_from_api(raw_bill, session=session, session_year=session_year))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _current_session_year(self) -> int:
        sessions = self.http.get(f"{ROOT}/api/billSearch/sessions").json()
        years = [
            int(item["value"])
            for item in sessions
            if isinstance(item, dict) and str(item.get("value", "")).isdigit()
        ]
        return max(years) if years else CURRENT_SESSION

    def _all_bills(self, session_year: int) -> list[dict[str, Any]]:
        data = self.http.get(f"{ROOT}/api/billSearch/allBills/{session_year}").json()
        if not isinstance(data, list) or not data:
            return []
        return [item for item in data[0] if isinstance(item, dict)]

    def _bill_from_api(self, raw_bill: dict[str, Any], *, session: Session, session_year: int) -> Bill:
        number = _clean_text(raw_bill.get("Bill"))
        description = self._detail_json("billDescription", number, session_year)
        history = self._detail_json("billHistory", number, session_year)
        sponsors = self._detail_json("billSponsors", number, session_year)
        texts = self._detail_json("billText", number, session_year)
        return parse_bill(
            raw_bill,
            description=description,
            history=history,
            sponsors=sponsors,
            texts=texts,
            session=session,
            session_year=session_year,
        )

    def _detail_json(self, endpoint: str, number: str, session_year: int) -> Any:
        return self.http.get(f"{ROOT}/api/billDetail/{endpoint}/{number}/{session_year}").json()


def session_for_year(session_year: int) -> Session:
    end_year = session_year + 1
    return Session(
        name=f"{session_year}-{end_year} New Jersey Legislature",
        start_date=date(session_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=session_year <= datetime.now().year <= end_year,
    )


def parse_bill(
    raw_bill: dict[str, Any],
    *,
    description: list[dict[str, Any]] | None,
    history: list[dict[str, Any]] | None,
    sponsors: list[list[dict[str, Any]]] | None,
    texts: list[dict[str, Any]] | None,
    session: Session,
    session_year: int,
) -> Bill:
    number = _clean_text((description or [{}])[0].get("ActualBillNumber") if description else raw_bill.get("Bill"))
    synopsis = _clean_text((description or [{}])[0].get("Synopsis") if description else raw_bill.get("Synopsis"))
    subject = _clean_text((description or [{}])[0].get("Code_Description") if description else None)
    title = synopsis or number
    return Bill(
        jurisdiction=NewJerseyScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=synopsis or None,
        subjects=[subject] if subject else [],
        sponsors=parse_sponsors(sponsors or []),
        source_url=_source_url(session_year, number),
        actions=parse_actions(history or [], source_url=_source_url(session_year, number)),
        versions=parse_versions(texts or []),
        kind=classify_kind(title),
    )


def parse_actions(history: list[dict[str, Any]], *, source_url: str | None = None) -> list[BillAction]:
    actions: list[BillAction] = []
    for item in history:
        text = _clean_text(item.get("HistoryAction"))
        occurred_at = _parse_action_date(item.get("ActionDate"))
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


def parse_sponsors(payload: list[list[dict[str, Any]]]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[tuple[str, str | None]] = set()
    for index, sponsor_list in enumerate(payload[:2]):
        default_role = "primary" if index == 0 else "cosponsor"
        for item in sponsor_list:
            name = _clean_text(item.get("Full_Name"))
            role = _role_from_description(item.get("SponsorDescription")) or default_role
            key = (name, role)
            if not name or key in seen:
                continue
            seen.add(key)
            sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def parse_versions(texts: list[dict[str, Any]]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    for item in texts:
        description = _clean_text(item.get("Description")) or "Bill text"
        comment = _clean_text(item.get("DocumentComment"))
        label = " - ".join(part for part in (description, comment) if part)
        pdf_link = _clean_text(item.get("PDFLink"))
        html_link = _clean_text(item.get("HTML_Link"))
        if pdf_link:
            versions.append(BillVersion(
                label=f"{label} PDF",
                source_url=urljoin(PUB_ROOT, pdf_link),
                format="pdf",
            ))
        if html_link:
            versions.append(BillVersion(
                label=f"{label} HTML",
                source_url=urljoin(PUB_ROOT, html_link),
                format="html",
            ))
    return versions


def _allowed_bill_number(number: str) -> bool:
    return bool(re.match(r"^(?:A|S)(?:B|R|JR|CR)?\s*\d+$", number, re.IGNORECASE))


def _source_url(session_year: int, number: str) -> str:
    return f"{ROOT}/bill-search/{session_year}/{number.replace(' ', '')}"


def _chamber_for_number(number: str) -> Chamber:
    upper = number.upper()
    if upper.startswith("A"):
        return Chamber.LOWER
    if upper.startswith("S"):
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_from_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "assembly" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _role_from_description(value: object) -> str | None:
    text = _clean_text(value).lower()
    if "co-sponsor" in text or "cosponsor" in text:
        return "cosponsor"
    if "primary" in text or "prime" in text:
        return "primary"
    return None


def _parse_action_date(value: object) -> datetime | None:
    text = _clean_text(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())
