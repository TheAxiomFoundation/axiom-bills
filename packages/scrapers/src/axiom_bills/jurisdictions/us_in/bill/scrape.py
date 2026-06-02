"""Indiana bill scraper.

Indiana publishes official bill metadata through the IGA public API.
The API is public but key-gated; callers must send INDIANA_API_KEY as the
`x-api-key` header and request JSON.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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

API_ROOT = "https://api.iga.in.gov"
SITE_ROOT = "https://iga.in.gov"
ET = ZoneInfo("America/Indiana/Indianapolis")


class IndianaScraper(BillScraper):
    jurisdiction = "us-in"
    source_name = "Indiana General Assembly public API"
    min_interval_per_host = 0.5

    def __init__(self, *, session_year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        key = os.environ.get("INDIANA_API_KEY")
        if not key:
            raise RuntimeError(
                "INDIANA_API_KEY not set. Indiana's official API requires an "
                "x-api-key header; see https://docs.api.iga.in.gov/."
            )
        self.api_key = key
        self.session_year = session_year or datetime.now(tz=ET).year

    def scrape(self) -> ScrapeResult:
        session_json = self._get(f"/{self.session_year}")
        session = session_from_api(self.session_year, session_json)
        session_no = session_number(session_json)
        bills: list[Bill] = []
        for stub in self._list_bills():
            bill = self._fetch_bill(stub, session=session, session_no=session_no)
            if bill is not None:
                bills.append(bill)
            if self.limit is not None and len(bills) >= self.limit:
                break
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _list_bills(self):
        payload = self._get(f"/{self.session_year}/bills")
        yield from unpaginate_items(payload, self._get_url)

    def _fetch_bill(self, stub: dict[str, Any], *, session: Session, session_no: str | None) -> Bill | None:
        link = stub.get("link")
        if not link:
            return None
        payload = self._get(link)
        if not payload:
            return None
        actions_link = (payload.get("actions") or {}).get("link")
        actions = list(unpaginate_items(self._get(actions_link), self._get_url)) if actions_link else []
        return parse_bill(payload, actions, session=session, session_no=session_no)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }

    def _get(self, path_or_url: str | None) -> dict[str, Any]:
        if not path_or_url:
            return {}
        return self._get_url(urljoin(API_ROOT, path_or_url))

    def _get_url(self, url: str) -> dict[str, Any]:
        response = self.http.get(url, headers=self._headers())
        if response.status_code == 403:
            raise RuntimeError("Indiana API returned 403; check INDIANA_API_KEY.")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("message") in {"Unauthorized", "Forbidden"}:
            raise RuntimeError("Indiana API rejected INDIANA_API_KEY.")
        return payload


def session_from_api(year: int, payload: dict[str, Any]) -> Session:
    name = _clean_text(payload.get("name")) or f"{year} Indiana General Assembly"
    return Session(
        name=name,
        start_date=_parse_date(payload.get("startDate")) or date(year, 1, 1),
        end_date=_parse_date(payload.get("endDate")) or date(year, 12, 31),
        is_current=year == datetime.now(tz=ET).year,
    )


def session_number(payload: dict[str, Any]) -> str | None:
    match = re.search(r"\bSession\s+(\d+)\b", str(payload.get("name") or ""))
    return match.group(1) if match else None


def unpaginate_items(payload: dict[str, Any], fetch_url) -> list[dict[str, Any]]:
    items = list(payload.get("items") or [])
    next_link = payload.get("nextLink")
    while next_link:
        payload = fetch_url(urljoin(API_ROOT, next_link.replace("per_page=50", "")))
        batch = list(payload.get("items") or [])
        if not batch:
            break
        items.extend(batch)
        next_link = payload.get("nextLink")
    return items


def parse_bill(payload: dict[str, Any], actions_payload: list[dict[str, Any]], *, session: Session, session_no: str | None) -> Bill:
    bill_id = str(payload.get("billName") or payload.get("displayName") or "").upper()
    display_name = correct_bill_identifier(str(payload.get("displayName") or _display_bill_id(bill_id)), payload.get("type"))
    title = _title(payload) or display_name
    latest = payload.get("latestVersion") or {}
    return Bill(
        jurisdiction=IndianaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(payload.get("originChamber")),
        number=display_name,
        title=title,
        summary=_clean_text(latest.get("digest")) or None,
        subjects=_subjects(latest),
        sponsors=_sponsors(payload),
        source_url=web_bill_url(session, display_name, payload.get("type")),
        actions=parse_actions(actions_payload),
        versions=parse_versions(payload, session_no=session_no),
        kind=classify_kind(title),
    )


def correct_bill_identifier(display_name: str, bill_type: object) -> str:
    text = _display_bill_id(display_name)
    if str(bill_type).upper() == "CRES":
        return text.replace("HC ", "HCR ").replace("SC ", "SCR ")
    if str(bill_type).upper() == "JRES":
        return text.replace("HJ ", "HJR ").replace("SJ ", "SJR ")
    return text


def parse_actions(actions_payload: list[dict[str, Any]]) -> list[BillAction]:
    actions: list[BillAction] = []
    for action in actions_payload:
        text = _clean_text(action.get("description"))
        occurred_at = _parse_datetime(action.get("date"))
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber((action.get("chamber") or {}).get("name")),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=urljoin(API_ROOT, action["link"]) if action.get("link") else None,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(payload: dict[str, Any], *, session_no: str | None) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    bill_type = payload.get("type")
    category = "resolutions" if "resolution" in _bill_type_label(bill_type) else "bills"
    year = str(payload.get("year") or "")
    origin = str(payload.get("originChamber") or "").lower()
    for version in payload.get("versions") or []:
        source_url = _version_url(version, session_no=session_no, year=year, origin=origin, category=category)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(
            label=_clean_text(version.get("stageVerbose")) or _clean_text(version.get("name")) or "Bill Text",
            source_url=source_url,
            format="pdf",
        ))
    return versions


def web_bill_url(session: Session, display_name: str, bill_type: object) -> str:
    year = str(session.start_date.year if session.start_date else datetime.now(tz=ET).year)
    prefix, number = _bill_components(display_name)
    segment = {
        "HB": "bills/house",
        "SB": "bills/senate",
        "HR": "resolutions/house/simple",
        "SR": "resolutions/senate/simple",
        "HCR": "resolutions/house/concurrent",
        "SCR": "resolutions/senate/concurrent",
        "HJR": "resolutions/house/joint",
        "SJR": "resolutions/senate/joint",
    }.get(prefix)
    if segment is None:
        segment = "resolutions/house/concurrent" if str(bill_type).upper() == "CRES" else "bills/house"
    return f"{SITE_ROOT}/legislative/{year}/{segment}/{number}"


def _title(payload: dict[str, Any]) -> str | None:
    for value in (
        payload.get("description"),
        (payload.get("latestVersion") or {}).get("shortDescription"),
        payload.get("displayName"),
    ):
        text = _clean_text(value)
        if text and text != "NoneNone":
            return text
    return None


def _subjects(latest: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for item in latest.get("subjects") or []:
        text = _clean_text(item.get("entry") if isinstance(item, dict) else item)
        if text:
            subjects.append(text)
    return subjects


def _sponsors(payload: dict[str, Any]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for key, role in (
        ("authors", "author"),
        ("coauthors", "coauthor"),
        ("sponsors", "sponsor"),
        ("cosponsors", "cosponsor"),
    ):
        for sponsor in payload.get(key) or []:
            name = _clean_text(" ".join(str(sponsor.get(part) or "") for part in ("firstName", "lastName")))
            if name:
                sponsors.append(Sponsor(name=name, role=role))
    return sponsors


def _version_url(version: dict[str, Any], *, session_no: str | None, year: str, origin: str, category: str) -> str | None:
    if session_no and year and origin and version.get("billName") and version.get("printVersionName"):
        return (
            f"{SITE_ROOT}/pdf-documents/{session_no}/{year}/{origin}/"
            f"{category}/{version['billName']}/{version['printVersionName']}.pdf"
        )
    link = version.get("link")
    return urljoin(API_ROOT, f"{link}?format=pdf") if link else None


def _chamber(raw: object) -> Chamber:
    text = str(raw or "").lower()
    if "senate" in text:
        return Chamber.UPPER
    if "governor" in text:
        return Chamber.EXECUTIVE
    return Chamber.LOWER


def _bill_type_label(raw: object) -> str:
    return {
        "BILL": "bill",
        "CRES": "concurrent resolution",
        "JRES": "joint resolution",
        "RES": "resolution",
    }.get(str(raw or "").upper(), str(raw or "").lower())


def _display_bill_id(raw: str) -> str:
    prefix, number = _bill_components(raw)
    return f"{prefix} {number}" if prefix and number else _clean_text(raw)


def _bill_components(raw: str) -> tuple[str, str]:
    text = _clean_text(raw).upper().replace(" ", "")
    match = re.match(r"([A-Z]+)0*(\d+)", text)
    return (match.group(1), match.group(2)) if match else ("", "")


def _parse_datetime(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        day = _parse_date(text)
        return datetime(day.year, day.month, day.day, tzinfo=ET) if day else None
    return parsed.astimezone(ET) if parsed.tzinfo else parsed.replace(tzinfo=ET)


def _parse_date(raw: object) -> date | None:
    if not raw:
        return None
    text = str(raw).split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _clean_text(raw: object) -> str:
    return re.sub(r"\s+", " ", str(raw or "").replace("\xa0", " ")).strip()
