"""New York bill scraper (NYSenate Open Legislation API).

Docs: https://legislation.nysenate.gov/static/docs/html/

Auth: free API key at https://legislation.nysenate.gov/. Limits are
generous; we keep min-interval to 0.5s to be polite.

NY uses biennial sessions: '2025-2026'. The session_year used in the API
is the odd starting year (2025 for the 2025-2026 session). Bill IDs in
NY are e.g. 'S1234' (Senate) and 'A1234' (Assembly).
"""
from __future__ import annotations

import os
from datetime import date, datetime
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

API_ROOT = "https://legislation.nysenate.gov/api/3"
ET = ZoneInfo("America/New_York")


def _current_session_year() -> int:
    """NY biennial sessions start on odd years."""
    y = datetime.now().year
    return y if y % 2 == 1 else y - 1


def _chamber_for_print_no(print_no: str) -> Chamber:
    # 'S1234' / 'S1234A' → upper; 'A1234' → lower.
    return Chamber.UPPER if print_no.upper().startswith("S") else Chamber.LOWER


class NewYorkScraper(BillScraper):
    jurisdiction = "us-ny"
    source_name = "NYSenate Open Legislation"
    min_interval_per_host = 0.5

    def __init__(self, *, session_year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        key = os.environ.get("NYSENATE_API_KEY")
        if not key:
            raise RuntimeError(
                "NYSENATE_API_KEY not set. Get a free key at "
                "https://legislation.nysenate.gov/"
            )
        self.api_key = key
        self.session_year = session_year or _current_session_year()

    def scrape(self) -> ScrapeResult:
        session = Session(
            name=f"{self.session_year}-{self.session_year + 1} Regular Session",
            start_date=date(self.session_year, 1, 1),
            end_date=date(self.session_year + 1, 12, 31),
            is_current=True,
        )
        bills: list[Bill] = []
        for stub in self._list_bills():
            full = self._fetch_bill(stub["basePrintNo"])
            if full is None:
                continue
            bills.append(full)
            if self.limit is not None and len(bills) >= self.limit:
                break
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session,
            bills=bills,
        )

    def _list_bills(self):
        offset = 1            # NY API uses 1-based offset
        page_size = 500
        while True:
            url = f"{API_ROOT}/bills/{self.session_year}"
            params = {
                "key": self.api_key,
                "limit": page_size,
                "offset": offset,
                "full": "false",
                "sort": "publishedDateTime:desc",
            }
            payload = self.http.get_json(url, params=params)
            items = payload.get("result", {}).get("items", [])
            if not items:
                return
            for item in items:
                yield item
            if self.limit is not None and offset + page_size > self.limit + 1:
                return
            total = payload.get("total", 0)
            offset += page_size
            if offset > total:
                return

    def _fetch_bill(self, print_no: str) -> Bill | None:
        url = f"{API_ROOT}/bills/{self.session_year}/{print_no}"
        try:
            payload = self.http.get_json(url, params={"key": self.api_key})
        except Exception:
            return None
        result = payload.get("result")
        if not result:
            return None

        actions = list(self._actions(result))
        sponsors = self._sponsors(result)
        versions = self._versions(result, print_no)

        title = result.get("title")
        return Bill(
            jurisdiction=self.jurisdiction,
            session_name=f"{self.session_year}-{self.session_year + 1} Regular Session",
            chamber=_chamber_for_print_no(print_no),
            number=print_no,
            title=title,
            summary=result.get("summary"),
            subjects=_subjects(result),
            sponsors=sponsors,
            source_url=f"https://www.nysenate.gov/legislation/bills/"
                       f"{self.session_year}/{print_no}",
            actions=actions,
            versions=versions,
            kind=classify_kind(title),
        )

    def _actions(self, result: dict):
        for entry in result.get("actions", {}).get("items", []) or []:
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            occurred_at = datetime.fromisoformat(entry["date"]).replace(tzinfo=ET)
            chamber = Chamber.UPPER if entry.get("chamber") == "SENATE" else Chamber.LOWER
            yield BillAction(
                occurred_at=occurred_at,
                chamber=chamber,
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            )

    def _sponsors(self, result: dict) -> list[Sponsor]:
        sponsors: list[Sponsor] = []
        primary = result.get("sponsor", {}).get("member") or {}
        if primary:
            sponsors.append(
                Sponsor(
                    name=primary.get("fullName") or primary.get("shortName") or "Unknown",
                    role="primary",
                    district=primary.get("districtCode") and str(primary["districtCode"]),
                )
            )
        co = result.get("amendments", {}).get("items", {}) or {}
        active_id = result.get("activeVersion") or ""
        active = co.get(active_id) or {}
        for c in active.get("coSponsors", {}).get("items", []) or []:
            sponsors.append(
                Sponsor(
                    name=c.get("fullName") or c.get("shortName") or "Unknown",
                    role="cosponsor",
                )
            )
        return sponsors

    def _versions(self, result: dict, print_no: str) -> list[BillVersion]:
        versions: list[BillVersion] = []
        amendments = result.get("amendments", {}).get("items", {}) or {}
        for amendment_id, body in amendments.items():
            label = f"version-{amendment_id or 'original'}"
            url = (
                f"https://legislation.nysenate.gov/api/3/bills/"
                f"{self.session_year}/{print_no}/amendment/{amendment_id or ''}"
            )
            versions.append(BillVersion(label=label, source_url=url, format="json"))
        return versions


def _subjects(result: dict) -> list[str]:
    raw = result.get("subjects", {}).get("items") or []
    return [s for s in raw if isinstance(s, str)]
