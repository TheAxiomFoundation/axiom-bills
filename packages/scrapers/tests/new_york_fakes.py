"""A fake Open Legislation API and a simulated clock for the New York tests.

The fake answers the way the API's docs describe. Nothing here touches a network.
"""
from __future__ import annotations

import sqlite3
import types
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from axiom_bills._common import http as http_module
from axiom_bills._common.base import ScrapeFailed
from axiom_bills._common.models import Bill
from axiom_bills.jurisdictions.us_ny.bill import scrape as ny_module
from axiom_bills.jurisdictions.us_ny.bill.scrape import ET, NewYorkScraper

KEY = "SENTINEL-KEY-VALUE"
SESSION = "2025-2026 Regular Session"
EPOCH = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)
MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"


class SimClock:
    """Stands in for the time module: sleeping moves the clock and costs nothing."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def utc(self) -> datetime:
        return EPOCH + timedelta(seconds=self.now - 1_000.0)


def chamber_of(print_no: str) -> str:
    return "SENATE" if print_no[0] in "SJRB" else "ASSEMBLY"


def full_bill(print_no: str, version: int = 0) -> dict:
    """A single bill from `view=no_fulltext`."""
    return {
        "basePrintNo": print_no,
        "session": 2025,
        "printNo": f"{print_no}A",
        "billType": {"chamber": chamber_of(print_no), "desc": "", "resolution": False},
        "title": f"Title of {print_no} v{version}",
        "activeVersion": "A",
        "amendments": {
            "items": {
                "": {},
                "A": {"coSponsors": {"items": [{"fullName": "Tony Avella"}], "size": 1}},
            },
            "size": 2,
        },
        "actions": {
            "items": [
                {"date": "2025-01-08", "chamber": chamber_of(print_no), "text": "REFERRED TO FINANCE"}
            ],
            "size": 1,
        },
    }


def status(code: int, *, error_code: int | None = None, retry_after: str | None = None) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    body = {"success": False, "message": f"Failed for key {KEY}", "responseType": "error"}
    if error_code is not None:
        body["errorCode"] = error_code
    return httpx.Response(code, headers=headers, json=body)


@dataclass
class FakeOpenLeg:
    """Serves the bill list, the bill update feed and single bills.

    `replies` holds what a path or print number answers instead of its normal
    response: one reply, or a list of them served in turn. A reply can be an
    httpx.Response or an exception class to raise. Requests after a list runs out
    get the normal response.
    """

    print_nos: list[str] = field(default_factory=list)
    replies: dict[str, object] = field(default_factory=dict)
    # (New York time of the change, print number, session year)
    changes: list[tuple[str, str, int]] = field(default_factory=list)
    versions: dict[str, int] = field(default_factory=dict)
    clock: SimClock | None = None
    latency: float = 0.0
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.clock is not None:
            self.clock.now += self.latency
        path = request.url.path.removeprefix("/api/3")
        name = path.rsplit("/", 1)[-1]
        for key in (name, path):
            if key in self.replies:
                reply = self.replies[key]
                if isinstance(reply, list):
                    if not reply:
                        continue
                    reply = reply.pop(0)
                if isinstance(reply, type) and issubclass(reply, Exception):
                    raise reply("simulated", request=request)
                return reply
        if path == "/bills/2025":
            items = [
                {"basePrintNo": n, "session": 2025, "basePrintNoStr": f"{n}-2025"}
                for n in self.print_nos
            ]
            return self._page(request, items)
        if path.startswith("/bills/updates/"):
            return self._page(request, self._tokens(path))
        if name not in self.print_nos:
            return status(404)
        return httpx.Response(
            200,
            json={"success": True, "responseType": "bill",
                  "result": full_bill(name, self.versions.get(name, 0))},
        )

    def _tokens(self, path: str) -> list[dict]:
        start, end = path.removeprefix("/bills/updates/").split("/")
        return [
            {
                "id": {"basePrintNo": name, "session": year, "basePrintNoStr": f"{name}-{year}"},
                "contentType": "BILL",
                "processedDateTime": when,
            }
            for when, name, year in self.changes
            if start <= when < end
        ]

    @staticmethod
    def _page(request: httpx.Request, items: list[dict]) -> httpx.Response:
        limit = int(request.url.params["limit"])
        offset = int(request.url.params["offset"])
        page = items[offset - 1 : offset - 1 + limit]
        return httpx.Response(
            200,
            json={
                "success": True,
                "responseType": "bill-info list" if page else "empty list",
                "total": len(items),
                "offsetStart": offset,
                "offsetEnd": offset - 1 + len(page),
                "limit": limit,
                "result": {"items": page, "size": len(page)},
            },
        )

    def change(self, name: str, when: datetime) -> None:
        """Change a bill at a UTC time, as the API would report it."""
        self.versions[name] = self.versions.get(name, 0) + 1
        label = when.astimezone(ET).replace(tzinfo=None).isoformat(timespec="microseconds")
        self.changes.append((label, name, 2025))

    def bill_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if self._is_bill(r)]

    def bill_names(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[-1] for r in self.bill_requests()]

    @staticmethod
    def _is_bill(request: httpx.Request) -> bool:
        path = request.url.path.removeprefix("/api/3")
        return path.startswith("/bills/2025/")


class _DirectClient:
    """Stands in for httpx.Client, without the cost of building a TLS context."""

    def __init__(self, api: FakeOpenLeg, kwargs: dict) -> None:
        self.api = api
        self.kwargs = kwargs

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        request = httpx.Request(method, url, params=kwargs.get("params"))
        response = self.api(request)
        response.request = request
        return response

    def close(self) -> None:
        pass


def install(mp: pytest.MonkeyPatch, api: FakeOpenLeg, *, real_httpx: bool = False) -> SimClock:
    """Route the New York scraper to the fake, on a simulated clock."""
    clock = api.clock or SimClock()
    api.clock = clock
    mp.setenv("NYSENATE_API_KEY", KEY)
    mp.setattr(http_module, "time", clock)
    mp.setattr(ny_module, "time", clock)
    mp.setattr(ny_module, "_utc_now", clock.utc)
    mp.setattr(
        http_module, "random", types.SimpleNamespace(uniform=lambda low, high: low)
    )
    if real_httpx:
        real_client = httpx.Client
        mp.setattr(
            http_module.httpx,
            "Client",
            lambda **kwargs: real_client(transport=httpx.MockTransport(api)),
        )
    else:
        mp.setattr(http_module.httpx, "Client", lambda **kwargs: _DirectClient(api, kwargs))
    return clock


def scraper_for(**kwargs) -> NewYorkScraper:
    return NewYorkScraper(session_year=2025, **kwargs)


def drain(scraper: NewYorkScraper) -> tuple[list[Bill], ScrapeFailed | None]:
    bills: list[Bill] = []
    try:
        for bill in scraper.bills_iter():
            bills.append(bill)
    except ScrapeFailed as failure:
        return bills, failure
    return bills, None


def make_db(tmp_path: Path) -> str:
    """A fresh database built from every migration, as `make migrate` builds it.

    `make migrate` pipes each file through the sqlite3 shell, which reports a
    statement that fails and carries on with the next one. Some migrations rely
    on that, such as those adding a column an earlier one already added.
    """
    path = str(tmp_path / "bills.sqlite")
    conn = sqlite3.connect(path, isolation_level=None)
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        statement = ""
        for line in migration.read_text().splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError:
                    pass
                statement = ""
    conn.close()
    return path


def numbered(prefix: str, count: int, start: int = 1) -> Iterable[str]:
    return (f"{prefix}{number}" for number in range(start, start + count))
