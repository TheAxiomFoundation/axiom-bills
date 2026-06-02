"""Georgia bill scraper.

The General Assembly publishes official bill search, detail, action, and
document metadata through the JSON API used by legis.ga.gov.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime
from typing import Any

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

ROOT = "https://www.legis.ga.gov"
API_ROOT = f"{ROOT}/api"
DEFAULT_SESSION_ID = 1033
DEFAULT_PAGE_SIZE = 100
OBSCURE_KEY = "jVEXFFwSu36BwwcP83xYgxLAhLYmKk"


class GeorgiaScraper(BillScraper):
    jurisdiction = "us-ga"
    source_name = "legis.ga.gov official JSON API"
    min_interval_per_host = 0.2

    def __init__(
        self,
        *,
        session_id: int | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        limit: int | None = None,
    ) -> None:
        super().__init__(limit=limit)
        self.session_id = session_id
        self.page_size = page_size
        self._token: str | None = None

    def scrape(self) -> ScrapeResult:
        session = self._session()
        bills: list[Bill] = []
        for summary in self._search_results(session_id=self._session_id(session)):
            detail = self._get_json(f"legislation/detail/{summary['legislationId']}")
            bills.append(parse_bill(detail, session=session))
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session_id(self, session: Session) -> int:
        match = re.search(r"\((\d+)\)$", session.name)
        return int(match.group(1)) if match else DEFAULT_SESSION_ID

    def _session(self) -> Session:
        sessions = self._get_json("sessions")
        selected = None
        if self.session_id is not None:
            selected = next((item for item in sessions if item.get("id") == self.session_id), None)
        if selected is None:
            selected = next((item for item in sessions if item.get("isCurrent")), None)
        if selected is None:
            selected = sessions[0]
        return session_from_api(selected)

    def _search_results(self, *, session_id: int):
        page = 0
        seen: set[int] = set()
        while True:
            response = self._post_json(
                f"Legislation/Search/{self.page_size}/{page}",
                {"sessionId": session_id},
            )
            results = response.get("results") or []
            if not results:
                break
            for item in results:
                legislation_id = item.get("legislationId")
                if not legislation_id or legislation_id in seen:
                    continue
                seen.add(legislation_id)
                yield item
                if self.limit is not None and len(seen) >= self.limit:
                    return
            result_count = int(response.get("resultCount") or 0)
            if (page + 1) * self.page_size >= result_count:
                break
            page += 1

    def _get_json(self, endpoint: str) -> Any:
        response = self.http.get(_api_url(endpoint), headers=self._headers())
        if response.status_code == 401:
            self._token = None
            response = self.http.get(_api_url(endpoint), headers=self._headers())
        response.raise_for_status()
        return response.json()

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> Any:
        response = self.http.post(_api_url(endpoint), json=payload, headers=self._headers())
        if response.status_code == 401:
            self._token = None
            response = self.http.post(_api_url(endpoint), json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._auth_token()}"}

    def _auth_token(self) -> str:
        if self._token:
            return self._token
        milliseconds = str(int(time.time() * 1000))
        digest = hashlib.sha512(f"QFpCwKfd7f{OBSCURE_KEY}letvarconst{milliseconds}".encode()).hexdigest()
        response = self.http.get(
            _api_url("authentication/token"),
            params={"key": digest, "ms": milliseconds},
        )
        response.raise_for_status()
        self._token = response.json()
        return self._token


def session_from_api(item: dict[str, Any]) -> Session:
    years = [int(year) for year in re.findall(r"\b(20\d{2})\b", _clean_text(item.get("description")))]
    start = years[0] if years else datetime.now().year
    end = years[-1] if years else start
    return Session(
        name=f"{_clean_text(item.get('description'))} ({item.get('id')})",
        start_date=date(start, 1, 1),
        end_date=date(end, 12, 31),
        is_current=bool(item.get("isCurrent")),
    )


def parse_bill(detail: dict[str, Any], *, session: Session) -> Bill:
    number = bill_number(detail)
    title = _clean_text(detail.get("title")) or number
    summary = _clean_text(detail.get("firstReader")) or title
    return Bill(
        jurisdiction=GeorgiaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(detail.get("chamber")),
        number=number,
        title=title,
        summary=summary,
        subjects=[title] if title else [],
        sponsors=parse_sponsors(detail),
        source_url=f"{ROOT}/legislation/{detail['id']}",
        actions=parse_actions(detail),
        versions=parse_versions(detail),
        kind=classify_kind(title),
    )


def bill_number(detail: dict[str, Any]) -> str:
    chamber = _chamber_short(detail.get("chamber") or detail.get("chamberType"))
    document_type = _document_type_short(detail.get("documentType"))
    number = _clean_text(detail.get("number"))
    suffix = _clean_text(detail.get("suffix"))
    return _clean_text(f"{chamber}{document_type} {number}{suffix}")


def parse_sponsors(detail: dict[str, Any]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for row in sorted(detail.get("sponsors") or [], key=lambda item: item.get("sequence") or 0):
        name = _clean_name(row.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        sponsors.append(Sponsor(
            name=name,
            role=_sponsor_role(row.get("sponsorType")),
            district=_clean_text(row.get("district")) or None,
        ))
    return sponsors


def parse_actions(detail: dict[str, Any]) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in detail.get("statusHistory") or []:
        occurred_at = _parse_datetime(row.get("date"))
        text = _clean_text(row.get("name"))
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_text(text) or _chamber(detail.get("chamber")),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=f"{ROOT}/legislation/{detail['id']}",
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(detail: dict[str, Any]) -> list[BillVersion]:
    session_library = _clean_text((detail.get("session") or {}).get("library")).strip("/")
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for row in sorted(detail.get("versions") or [], key=lambda item: item.get("versionNumber") or 0):
        version_id = row.get("id")
        if not version_id or not session_library:
            continue
        url = f"{API_ROOT}/legislation/document/{session_library}/{version_id}"
        if url in seen:
            continue
        seen.add(url)
        label = _clean_text(row.get("name")) or f"version {row.get('versionNumber')}"
        versions.append(BillVersion(label=label, source_url=url, format="pdf"))
    return versions


def _api_url(endpoint: str) -> str:
    return f"{API_ROOT}/{endpoint.strip('/')}"


def _chamber(value: Any) -> Chamber:
    if value == 1:
        return Chamber.LOWER
    if value == 2:
        return Chamber.UPPER
    return Chamber.JOINT


def _chamber_short(value: Any) -> str:
    if value == 1:
        return "H"
    if value == 2:
        return "S"
    return "J"


def _document_type_short(value: Any) -> str:
    if value == 2:
        return "R"
    return "B"


def _chamber_from_text(text: str) -> Chamber | None:
    lowered = text.lower()
    if "governor" in lowered:
        return Chamber.EXECUTIVE
    if "house" in lowered:
        return Chamber.LOWER
    if "senate" in lowered:
        return Chamber.UPPER
    return None


def _sponsor_role(value: Any) -> str:
    if value == 2:
        return "cosponsor"
    return "primary"


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Z]+)\s+(\d+)(.*)", number)
    if not match:
        return (number, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_name(value: Any) -> str:
    return _clean_text(value).rstrip(",")

