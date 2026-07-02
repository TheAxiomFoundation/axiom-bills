"""Federal bill scraper (Congress.gov API).

Docs: https://api.congress.gov/

Auth: free API key at https://api.congress.gov/sign-up/. The key goes in
the CONGRESS_API_KEY env var. Generous rate limits (5000/hour).

We pull bills + actions for the current Congress. Bill text versions are
recorded as references (URL + format) but not downloaded here — text
fetch is a separate pipeline stage that runs only on status-changing
events.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Iterator
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

API_ROOT = "https://api.congress.gov/v3"

# Bill type codes Congress.gov uses → our chamber. Joint resolutions are
# either-chamber but originate from one; for the prototype we collapse
# them into the originating chamber's bucket.
TYPE_CHAMBER: dict[str, Chamber] = {
    "hr": Chamber.LOWER,    # House bill
    "s":  Chamber.UPPER,    # Senate bill
    "hjres": Chamber.LOWER,
    "sjres": Chamber.UPPER,
    "hconres": Chamber.LOWER,
    "sconres": Chamber.UPPER,
    "hres": Chamber.LOWER,
    "sres": Chamber.UPPER,
}

# Display formatting: 'hr' + '1234' → 'H.R.1234'
TYPE_DISPLAY: dict[str, str] = {
    "hr": "H.R.", "s": "S.",
    "hjres": "H.J.Res.", "sjres": "S.J.Res.",
    "hconres": "H.Con.Res.", "sconres": "S.Con.Res.",
    "hres": "H.Res.", "sres": "S.Res.",
}

ET = ZoneInfo("America/New_York")


def _action_text_chamber(text: str) -> Chamber | None:
    lo = text.lower()
    if "house" in lo:
        return Chamber.LOWER
    if "senate" in lo:
        return Chamber.UPPER
    if "president" in lo:
        return Chamber.EXECUTIVE
    return None


def _parse_action_datetime(action: dict) -> datetime:
    """Congress.gov returns actionDate (always) and actionTime (sometimes)."""
    date_str = action["actionDate"]
    time_str = action.get("actionTime")
    if time_str:
        iso = f"{date_str}T{time_str}"
    else:
        iso = f"{date_str}T00:00:00"
    return datetime.fromisoformat(iso).replace(tzinfo=ET)


class FederalScraper(BillScraper):
    jurisdiction = "us"
    source_name = "Congress.gov"
    # Congress.gov allows 5,000 requests/hour. 0.2s (18,000/hr) blew
    # through that in ~17 minutes on a full refresh, after which the API
    # stalls connections until the window resets — the run bled out on
    # ReadTimeouts. 0.75s ≈ 4,800/hr stays inside the budget for runs of
    # any length.
    min_interval_per_host = 0.75

    def __init__(self, *, congress: int | None = None, limit: int | None = None,
                 bill_ids: list[str] | None = None,
                 since: datetime | None = None) -> None:
        super().__init__(limit=limit)
        api_key = os.environ.get("CONGRESS_API_KEY")
        if not api_key:
            raise RuntimeError(
                "CONGRESS_API_KEY not set. Get a free key at "
                "https://api.congress.gov/sign-up/"
            )
        self.api_key = api_key
        self.congress = congress or _current_congress()
        # When set, scrape only these specific bills instead of paginating
        # the recent-updates feed. Each id is "<type>/<number>" e.g.
        # "hr/7024". Useful for targeted backfills like pulling a known
        # tax bill into the index.
        self.bill_ids = bill_ids
        # When set, stop paginating once Congress.gov returns a bill whose
        # updateDate is older than this cursor. Skips the bulk of the
        # 6500+-bill Congress on routine refresh runs.
        self.since = since

    def session(self) -> Session:
        return Session(name=f"{self.congress}th Congress", is_current=True)

    def scrape(self) -> ScrapeResult:
        """Bulk-mode entrypoint (used by tests and one-shot backfills).

        Routine refreshes should iterate `bills_iter()` and commit per bill
        so a crash mid-scrape doesn't lose everything.
        """
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=self.session(),
            bills=list(self.bills_iter()),
        )

    def bills_iter(self) -> Iterator[Bill]:
        """Yield bills one at a time. Progress goes to stderr.

        Internal pagination breaks early on the since-cursor so refresh
        runs don't traverse the entire Congress every time.
        """
        if self.bill_ids:
            for raw in self.bill_ids:
                bill_type, _, number = raw.partition("/")
                stub = {"type": bill_type, "number": number}
                full = self._fetch_bill(stub)
                if full is not None:
                    print(f"  fetched {full.number}", file=sys.stderr, flush=True)
                    yield full
            return

        count = 0
        for stub in self._list_bills():
            full = self._fetch_bill(stub)
            if full is None:
                continue
            count += 1
            print(f"  [{count}] {full.number}", file=sys.stderr, flush=True)
            yield full
            if self.limit is not None and count >= self.limit:
                return

    def _list_bills(self):
        """Paginate the recent-bills endpoint for the active Congress.

        Sorted by updateDate desc. If a `since` cursor is set, stop the
        moment we see a bill older than it — that's the rest of the
        Congress, unchanged since our last successful refresh, and not
        worth touching.
        """
        offset = 0
        page_size = 250
        while True:
            url = f"{API_ROOT}/bill/{self.congress}"
            params = {
                "api_key": self.api_key,
                "format": "json",
                "limit": page_size,
                "offset": offset,
                "sort": "updateDate desc",
            }
            payload = self.http.get_json(url, params=params)
            stubs = payload.get("bills", [])
            if not stubs:
                return
            for stub in stubs:
                if self.since is not None:
                    upd = stub.get("updateDate")
                    if upd and _parse_update_date(upd) < self.since:
                        return
                yield stub
            offset += page_size
            if self.limit is not None and offset >= self.limit:
                return
            if not payload.get("pagination", {}).get("next"):
                return

    def _fetch_bill(self, stub: dict) -> Bill | None:
        bill_type = stub["type"].lower()
        number = stub["number"]
        chamber = TYPE_CHAMBER.get(bill_type)
        if chamber is None:
            return None

        url = f"{API_ROOT}/bill/{self.congress}/{bill_type}/{number}"
        try:
            detail = self.http.get_json(url, params={"api_key": self.api_key, "format": "json"})
        except Exception:
            return None
        body = detail.get("bill", {})

        actions = list(self._fetch_actions(bill_type, number))
        versions = list(self._fetch_text_versions(bill_type, number))

        sponsors = [
            Sponsor(
                name=s.get("fullName") or s.get("name") or "Unknown",
                role="primary",
                party=s.get("party"),
                # Congress.gov returns district as an int; coerce to str.
                district=str(s.get("district") or s.get("state") or "") or None,
            )
            for s in body.get("sponsors", [])
        ]

        title = body.get("title")
        return Bill(
            jurisdiction=self.jurisdiction,
            session_name=f"{self.congress}th Congress",
            chamber=chamber,
            number=f"{TYPE_DISPLAY[bill_type]}{number}",
            title=title,
            summary=_first_summary(body),
            subjects=_subjects(body),
            sponsors=sponsors,
            source_url=f"https://www.congress.gov/bill/{self.congress}th-congress/"
                       f"{_url_slug(bill_type)}/{number}",
            actions=actions,
            versions=versions,
            kind=classify_kind(title),
        )

    def _fetch_actions(self, bill_type: str, number: int):
        url = f"{API_ROOT}/bill/{self.congress}/{bill_type}/{number}/actions"
        payload = self.http.get_json(
            url, params={"api_key": self.api_key, "format": "json", "limit": 250}
        )
        for action in payload.get("actions", []):
            text = action.get("text", "").strip()
            if not text:
                continue
            yield BillAction(
                occurred_at=_parse_action_datetime(action),
                chamber=_action_text_chamber(text),
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            )

    def _fetch_text_versions(self, bill_type: str, number: int):
        url = f"{API_ROOT}/bill/{self.congress}/{bill_type}/{number}/text"
        try:
            payload = self.http.get_json(
                url, params={"api_key": self.api_key, "format": "json"}
            )
        except Exception:
            return
        for version in payload.get("textVersions", []):
            label = (version.get("type") or "Unknown").strip().lower().replace(" ", "-")
            for fmt in version.get("formats", []):
                normalized = _normalize_format(fmt.get("type", ""))
                yield BillVersion(
                    label=f"{label}-{normalized}",
                    source_url=fmt["url"],
                    format=normalized,
                )


def _normalize_format(raw: str) -> str:
    """Congress.gov format names → our short keys.

    'Formatted Text' → 'html', 'Formatted XML' → 'xml', etc. Keeps the
    text-fetcher's prefer_format ordering ('html', 'xml', 'txt') working
    without it having to know about Congress.gov-specific labels.
    """
    lower = (raw or "").strip().lower()
    if lower in ("formatted text", "html"):
        return "html"
    if lower in ("formatted xml", "xml", "united states legislative markup"):
        return "xml"
    if lower in ("pdf",):
        return "pdf"
    if lower in ("text", "txt", "plain text"):
        return "txt"
    return lower or "unknown"


def _first_summary(body: dict) -> str | None:
    summaries = body.get("summaries", {})
    if isinstance(summaries, dict):
        items = summaries.get("summary") or summaries.get("count")
    else:
        items = summaries
    if isinstance(items, list) and items:
        return items[0].get("text")
    return None


def _subjects(body: dict) -> list[str]:
    raw = body.get("subjects", {})
    if isinstance(raw, dict):
        legislative = raw.get("legislativeSubjects", []) or []
        policy = raw.get("policyArea", {})
        names = [s.get("name") for s in legislative if s.get("name")]
        if isinstance(policy, dict) and policy.get("name"):
            names.append(policy["name"])
        return names
    return []


def _url_slug(bill_type: str) -> str:
    return {
        "hr": "house-bill",
        "s": "senate-bill",
        "hjres": "house-joint-resolution",
        "sjres": "senate-joint-resolution",
        "hconres": "house-concurrent-resolution",
        "sconres": "senate-concurrent-resolution",
        "hres": "house-resolution",
        "sres": "senate-resolution",
    }.get(bill_type, bill_type)


def _parse_update_date(s: str) -> datetime:
    """Congress.gov's updateDate is sometimes 'YYYY-MM-DD', sometimes ISO.

    Returns a naive datetime in local time so it can be compared directly
    against the naive `started_at` we read out of SQLite (those rows are
    written by datetime('now') and stored without tz).
    """
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromisoformat(s + "T00:00:00")
    if dt.tzinfo is not None:
        dt = dt.astimezone(ET).replace(tzinfo=None)
    return dt


def _current_congress() -> int:
    """Congress numbering: 119th Congress runs 2025-01-03 → 2027-01-03."""
    year = datetime.now().year
    # Congresses are biennial starting 1789. Each spans two years; the
    # Nth Congress begins Jan 3 of the odd year 1789 + 2*(N-1).
    base = 1789
    # Bias so a year like 2026 (mid-119th) returns 119.
    return ((year - base) // 2) + 1
