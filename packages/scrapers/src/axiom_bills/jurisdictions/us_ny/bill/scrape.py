"""New York bill scraper (NYSenate Open Legislation API).

Docs: https://legislation.nysenate.gov/static/docs/html/

Auth: free API key at https://legislation.nysenate.gov/. From December 1,
2026 the API allows each key 10 requests a second and 4 in progress at once.
We send one request at a time, each at least 0.1 seconds after the last, which
its rate limit guidance says stays within both.

NY uses biennial sessions: '2025-2026'. The session_year used in the API
is the odd starting year (2025 for the 2025-2026 session). Bill IDs in
NY are e.g. 'S1234' (Senate) and 'A1234' (Assembly).

A refresh follows the API's "Keeping up with changes" guide. The first run for
a session notes the time, lists every bill and fetches as many as its time
budget allows. Each later run asks the update feed what changed since the last
run's noted time, then fetches those bills and the ones earlier runs left
behind. `next_refresh_state` says where the next run picks up.

`bills_iter` yields what it can and raises ScrapeFailed at the end if any bill
failed. It raises before yielding anything if it can't read a list to the end.
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from axiom_bills._common.base import BillScraper, ScrapeFailed
from axiom_bills._common.http import (
    RateLimitedClient,
    RetryDeadlineReached,
    RetryPolicy,
)
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillVersion,
    Chamber,
    RefreshState,
    ScrapeResult,
    Session,
    Sponsor,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

API_ROOT = "https://legislation.nysenate.gov/api/3"
ET = ZoneInfo("America/New_York")
CHAMBERS = {"SENATE": Chamber.UPPER, "ASSEMBLY": Chamber.LOWER}

# The API caps a list page at 1000 items.
PAGE_SIZE = 1000
# The API counts a request as in progress until it finishes, even after a client
# stops waiting, so give a slow one time to finish.
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
# The API says to retry a 429 or a 503, give up after a few attempts, and leave
# other errors alone, and a resent slow request only adds to the 4 in progress.
RETRY_POLICY = RetryPolicy(
    attempts=5,
    retry_statuses=frozenset({429, 503}),
    resend_read_timeouts=False,
)

# The API says to end each feed range two minutes in the past, which leaves time
# for changes it's still saving.
FEED_MARGIN = timedelta(minutes=2)
# Each range reaches an hour behind where the last one ended, because the feed's
# New York times carry no offset. When the clocks go back, a change in the
# repeated hour can carry an earlier time than a range we already read.
FEED_OVERLAP = timedelta(hours=1)

# This many failures in a row means the API is down, not that some bills are bad.
MAX_FAILURES_IN_A_ROW = 3
# The API says a 404 means the bill was removed, but a run of them more likely
# means we're asking for the wrong thing.
MAX_REMOVALS_IN_A_ROW = 10
PROGRESS_EVERY = 500


def _current_session_year() -> int:
    """NY biennial sessions start on odd years."""
    y = datetime.now().year
    return y if y % 2 == 1 else y - 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def feed_end(now: datetime) -> datetime:
    """Where a feed range read at `now` ends: New York time, with no offset."""
    return (now - FEED_MARGIN).astimezone(ET).replace(tzinfo=None, microsecond=0)


def feed_start(cursor: datetime) -> datetime:
    """Where a feed range starts, given where the last one ended."""
    return cursor - FEED_OVERLAP


class _ApiCallFailed(Exception):
    """An API call failed. The text gives a reason and never the URL, which holds the key."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.status = status

    @property
    def stops_the_run(self) -> bool:
        # Every later request would meet the same thing: a revoked key, a request
        # the API now refuses, or a rate limit that outlasted our retries.
        return self.status is not None and 400 <= self.status < 500 and self.status != 404


def _base_print_no(item: object) -> str:
    print_no = item.get("basePrintNo") if isinstance(item, dict) else None
    if not isinstance(print_no, str) or not print_no:
        raise _ApiCallFailed("a list item with no print number")
    return print_no


class NewYorkScraper(BillScraper):
    jurisdiction = "us-ny"
    source_name = "NYSenate Open Legislation"
    min_interval_per_host = 0.1
    supports_refresh_state = True

    def __init__(
        self,
        *,
        session_year: int | None = None,
        limit: int | None = None,
        time_budget: float | None = None,
    ) -> None:
        super().__init__(limit=limit)
        key = os.environ.get("NYSENATE_API_KEY")
        if not key:
            raise RuntimeError(
                "NYSENATE_API_KEY not set. Get a free key at "
                "https://legislation.nysenate.gov/"
            )
        self.api_key = key
        self.session_year = session_year or _current_session_year()
        self.http.close()
        self.http = RateLimitedClient(
            min_interval_per_host=self.min_interval_per_host,
            timeout=REQUEST_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self.time_budget = time_budget
        self._deadline: float | None = None
        # What the last run saved. None loads the whole session.
        self.refresh_state: RefreshState | None = None
        # True once the time budget ended the run with bills still to fetch.
        self.out_of_time = False
        self._feed_cursor: str | None = None
        # An ordered set: the bills this run hasn't finished with.
        self._unfinished: dict[str, None] = {}
        self._fetched = 0
        self._removed: list[str] = []
        self._failed: list[str] = []
        self._failure_reasons: Counter[str] = Counter()
        self._failures_in_a_row = 0
        self._removals_in_a_row = 0
        self._stop_reason: str | None = None

    def session(self) -> Session:
        return Session(
            name=f"{self.session_year}-{self.session_year + 1} Regular Session",
            start_date=date(self.session_year, 1, 1),
            end_date=date(self.session_year + 1, 12, 31),
            is_current=True,
        )

    def scrape(self) -> ScrapeResult:
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=self.session(),
            bills=list(self.bills_iter()),
        )

    def bills_iter(self) -> Iterator[Bill]:
        started = time.monotonic()
        if self.time_budget is not None:
            self._deadline = started + self.time_budget
        self.http.retry_deadline = self._deadline
        self._plan()
        planned = len(self._unfinished)
        for print_no in list(self._unfinished):
            if self.limit is not None and self._fetched >= self.limit:
                break
            if self._past_deadline():
                self.out_of_time = True
                break
            try:
                bill = self._fetch_bill(print_no)
            except RetryDeadlineReached:
                self.out_of_time = True
                break
            except _ApiCallFailed as failure:
                self._record_failure(print_no, failure)
                if self._stop_reason is not None:
                    break
                continue
            yield bill
            # The caller came back for the next bill, so it kept this one. If its
            # write had failed, this bill would stay in the next run's pending list.
            del self._unfinished[print_no]
            self._fetched += 1
            self._failures_in_a_row = 0
            self._removals_in_a_row = 0
            if self._fetched % PROGRESS_EVERY == 0:
                self._report(started, f"of {planned}")
        self._finish(started)

    def _past_deadline(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    def next_refresh_state(self) -> RefreshState | None:
        """Where the next run picks up, or None if this run never got its work list.

        Bills that failed go last, so that they can't crowd out the others.
        """
        if self._feed_cursor is None:
            return None
        return RefreshState(
            feed_cursor=self._feed_cursor,
            pending=[*self._unfinished, *self._failed],
        )

    def _plan(self) -> None:
        """Work out which bills this run fetches, or raise ScrapeFailed."""
        # The guide says to note the time before loading anything: a bill that
        # changes during the load then shows up in the next run's feed range.
        end = feed_end(_utc_now())
        saved = self.refresh_state
        try:
            if saved is None:
                names = self._list_session_bills()
            else:
                names = [*self._changed_bills(saved.feed_cursor, end), *saved.pending]
        except (_ApiCallFailed, RetryDeadlineReached) as error:
            what = "the bill list" if saved is None else "the update feed"
            raise ScrapeFailed(f"Couldn't read {what} to the end: {error}") from None
        if saved is None and not names:
            raise ScrapeFailed(f"The bill list for session {self.session_year} came back empty")
        self._unfinished = dict.fromkeys(names)
        self._feed_cursor = end.isoformat()

    def _list_session_bills(self) -> list[str]:
        names: list[str] = []
        items = self._read_list(f"/bills/{self.session_year}", {"idsOnly": "true"})
        for item in items:
            names.append(_base_print_no(item))
            if self.limit is not None and len(names) >= self.limit:
                break
        return names

    def _changed_bills(self, cursor: str, end: datetime) -> list[str]:
        try:
            start = feed_start(datetime.fromisoformat(cursor))
        except ValueError:
            raise _ApiCallFailed(f"the saved cursor {cursor!r} isn't a time") from None
        names: list[str] = []
        for token in self._read_list(
            f"/bills/updates/{start.isoformat()}/{end.isoformat()}", {}
        ):
            bill_id = token.get("id") if isinstance(token, dict) else None
            session = bill_id.get("session") if isinstance(bill_id, dict) else None
            # Skipping an update we can't place would lose that change for good.
            if type(session) is not int:
                raise _ApiCallFailed("an update with no session year")
            if session == self.session_year:
                names.append(_base_print_no(bill_id))
        return names

    def _read_list(self, path: str, params: dict[str, str]) -> Iterator[object]:
        """Every item of a paged list, read the way the API's conventions page says."""
        offset = 1
        while True:
            if self._past_deadline():
                raise _ApiCallFailed(f"the time budget ran out at item {offset}")
            payload = self._get_api(path, {**params, "limit": PAGE_SIZE, "offset": offset})
            total = payload.get("total")
            items = payload["result"].get("items")
            if type(total) is not int or not isinstance(items, list):
                raise _ApiCallFailed("a list page with no total or items")
            if not items:
                if offset > total:
                    return
                raise _ApiCallFailed(f"an empty list page at {offset} of {total}")
            yield from items
            offset_end = payload.get("offsetEnd")
            if type(offset_end) is not int or offset_end < offset:
                raise _ApiCallFailed(f"a list page at {offset} with no usable offsetEnd")
            if offset_end >= total:
                return
            offset = offset_end + 1

    def _get_api(self, path: str, params: dict) -> dict:
        """The JSON body of one successful API call, or _ApiCallFailed."""
        query = {"key": self.api_key, **params}
        try:
            response = self.http.get(f"{API_ROOT}{path}", params=query)
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise _ApiCallFailed(f"HTTP {status}", status=status) from None
        except httpx.HTTPError as error:
            raise _ApiCallFailed(type(error).__name__) from None
        status = response.status_code
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if status != 200:
            code = payload.get("errorCode") if isinstance(payload, dict) else None
            detail = f" (errorCode {code})" if type(code) is int else ""
            raise _ApiCallFailed(f"HTTP {status}{detail}", status=status)
        if not isinstance(payload, dict):
            raise _ApiCallFailed("a body that isn't a JSON object")
        if payload.get("success") is False:
            raise _ApiCallFailed("a body that says it failed")
        if not isinstance(payload.get("result"), dict):
            raise _ApiCallFailed("a body with no result")
        return payload

    def _fetch_bill(self, print_no: str) -> Bill:
        path = f"/bills/{self.session_year}/{print_no}"
        payload = self._get_api(path, {"view": "no_fulltext"})
        try:
            return self._bill_from(payload["result"], print_no)
        except Exception as error:
            # A shape we can't read fails this bill, and the run reports it.
            raise _ApiCallFailed(f"a bill we can't read: {type(error).__name__}") from None

    def _bill_from(self, result: dict, print_no: str) -> Bill:
        title = result.get("title")
        return Bill(
            jurisdiction=self.jurisdiction,
            session_name=self.session().name,
            chamber=CHAMBERS[result["billType"]["chamber"]],
            number=print_no,
            title=title,
            summary=result.get("summary"),
            subjects=_subjects(result),
            sponsors=self._sponsors(result),
            source_url=f"https://www.nysenate.gov/legislation/bills/"
                       f"{self.session_year}/{print_no}",
            actions=list(self._actions(result)),
            versions=self._versions(result, print_no),
            kind=classify_kind(title),
        )

    def _record_failure(self, print_no: str, failure: _ApiCallFailed) -> None:
        del self._unfinished[print_no]
        if failure.status == 404:
            self._removed.append(print_no)
            self._removals_in_a_row += 1
            self._failures_in_a_row = 0
            if self._removals_in_a_row >= MAX_REMOVALS_IN_A_ROW:
                self._failed.extend(self._removed[-MAX_REMOVALS_IN_A_ROW:])
                del self._removed[-MAX_REMOVALS_IN_A_ROW:]
                self._failure_reasons[str(failure)] += MAX_REMOVALS_IN_A_ROW
                self._stop_reason = f"{MAX_REMOVALS_IN_A_ROW} bills in a row returned HTTP 404"
            return
        self._failed.append(print_no)
        self._failure_reasons[str(failure)] += 1
        self._failures_in_a_row += 1
        self._removals_in_a_row = 0
        if failure.stops_the_run:
            self._stop_reason = f"{failure} on {print_no} would stop any later request too"
        elif self._failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
            self._stop_reason = f"{MAX_FAILURES_IN_A_ROW} bills in a row failed"

    def _report(self, started: float, of: str) -> None:
        elapsed = time.monotonic() - started
        pace = elapsed / self._fetched if self._fetched else 0.0
        print(
            f"  [{self._fetched} {of}] {elapsed:.0f}s, {pace:.3f}s a bill",
            file=sys.stderr,
            flush=True,
        )

    def _finish(self, started: float) -> None:
        pending = len(self._unfinished) + len(self._failed)
        self._report(
            started,
            f"fetched, {len(self._removed)} removed, {len(self._failed)} failed, "
            f"{pending} pending",
        )
        if self._removed:
            print(
                f"  The API no longer has: {', '.join(self._removed[:20])}"
                + (" and more" if len(self._removed) > 20 else ""),
                file=sys.stderr,
                flush=True,
            )
        if self._failed:
            reasons = ", ".join(
                f"{reason} x{count}" for reason, count in self._failure_reasons.most_common()
            )
            stopped = f" Stopped early: {self._stop_reason}." if self._stop_reason else ""
            raise ScrapeFailed(
                f"Bills that failed: {len(self._failed)}, starting with "
                f"{', '.join(self._failed[:5])}. Reasons: {reasons}.{stopped}"
            )
        if self.out_of_time and not self._fetched:
            raise ScrapeFailed("The time budget ran out before the run fetched a bill")

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
