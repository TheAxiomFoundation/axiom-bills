"""`axiom-bills scrape` for New York: what it stores, what it saves, how it exits."""
from __future__ import annotations

import sqlite3
import traceback
from datetime import date

import httpx
import pytest
from click.testing import CliRunner, Result

from axiom_bills import cli
from axiom_bills._common import db as db_module
from axiom_bills._common.base import BillScraper, ScrapeFailed
from axiom_bills._common.db import read_refresh_state, write_refresh_state
from axiom_bills._common.models import Bill, Chamber, RefreshState, ScrapeResult, Session
from axiom_bills.jurisdictions.us_ny.bill import scrape as ny_module

from .new_york_fakes import KEY, SESSION, FakeOpenLeg, install, make_db, numbered, status

A_CURSOR = "2026-11-06T09:00:00"
# Where a run on the fake's clock noted the time, before any latency.
NOTED_TIME = "2026-11-06T09:58:00"
BILL_LIST = "/bills/2025"


@pytest.fixture
def db(tmp_path, monkeypatch) -> str:
    path = make_db(tmp_path)
    monkeypatch.setattr(cli, "DEFAULT_DB", path)
    monkeypatch.setattr(ny_module, "_current_session_year", lambda: 2025)
    return path


def scrape(*args: str) -> Result:
    return CliRunner().invoke(cli.main, ["scrape", "--jurisdiction", "us-ny", *args])


def saved(db: str) -> RefreshState | None:
    return read_refresh_state("us-ny", SESSION, db)


def save(db: str, *pending: str) -> RefreshState:
    state = RefreshState(feed_cursor=A_CURSOR, pending=list(pending))
    write_refresh_state("us-ny", SESSION, state, db)
    return state


def stored(db: str) -> list[str]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT number FROM bills ORDER BY number").fetchall()
    conn.close()
    return [row[0] for row in rows]


def runs(db: str) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT finished_at, error, bills_seen FROM scrape_runs ORDER BY started_at"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# --- Exit 0: the run got everything ------------------------------------------


def test_a_clean_first_run_exits_0_and_saves_where_it_stands(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1", "A2", "J3"]))

    result = scrape()

    assert result.exit_code == 0, result.output
    assert "bills_seen=3" in result.output
    assert stored(db) == ["A2", "J3", "S1"]
    assert saved(db) == RefreshState(feed_cursor=NOTED_TIME, pending=[])
    assert [(run["error"], run["bills_seen"]) for run in runs(db)] == [(None, 3)]
    assert runs(db)[0]["finished_at"] is not None


def test_a_later_run_fetches_what_changed_and_what_the_last_run_left(db, monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3"])
    api.changes = [("2026-11-06T09:30:00", "S2", 2025)]
    install(monkeypatch, api)
    save(db, "S3")

    result = scrape()

    assert result.exit_code == 0, result.output
    assert stored(db) == ["S2", "S3"]
    assert saved(db) == RefreshState(feed_cursor=NOTED_TIME, pending=[])


def test_a_run_with_nothing_to_do_exits_0_and_moves_the_cursor(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1"]))
    save(db)

    result = scrape()

    assert result.exit_code == 0, result.output
    assert stored(db) == []
    assert saved(db) == RefreshState(feed_cursor=NOTED_TIME, pending=[])


def test_a_removed_bill_counts_as_done_and_stays_in_the_database(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1"]))
    save(db, "S1", "S2")

    result = scrape()

    assert result.exit_code == 0, result.output
    assert "S2" in result.stderr
    assert saved(db).pending == []


# --- Exit 4: out of time, with progress to keep ------------------------------


def test_a_budget_stop_exits_4_keeps_the_bills_and_saves_the_rest(db, monkeypatch) -> None:
    names = list(numbered("S", 10))
    install(monkeypatch, FakeOpenLeg(print_nos=names, latency=20.0))

    # A minute: 20 seconds for the listing, then two bills.
    result = scrape("--time-budget-minutes", "1")

    assert result.exit_code == cli.EXIT_OUT_OF_TIME == 4, result.output
    assert stored(db) == ["S1", "S2"]
    assert saved(db).pending == names[2:]
    assert "Bills still pending: 8" in result.stderr
    # Nothing went wrong, so the run isn't marked as failed.
    assert [run["error"] for run in runs(db)] == [None]


def test_runs_in_turn_finish_a_load_that_no_run_could_finish_alone(db, monkeypatch) -> None:
    names = list(numbered("S", 10))
    api = FakeOpenLeg(print_nos=names, latency=20.0)
    clock = install(monkeypatch, api)

    exit_codes = []
    for _ in range(20):
        result = scrape("--time-budget-minutes", "1")
        exit_codes.append(result.exit_code)
        clock.now += 3_600
        if result.exit_code == 0:
            break

    assert exit_codes[-1] == 0
    assert set(exit_codes[:-1]) == {cli.EXIT_OUT_OF_TIME}
    assert sorted(stored(db)) == sorted(names)
    assert saved(db).pending == []
    # Only the first run reads the whole list.
    assert sum(r.url.path == f"/api/3{BILL_LIST}" for r in api.requests) == 1


# --- Exit 3: something failed, with progress to keep -------------------------


def test_a_failed_bill_exits_3_keeps_the_rest_and_saves_it_for_a_retry(db, monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3"], replies={"S2": status(500)})
    install(monkeypatch, api)

    result = scrape()

    assert result.exit_code == cli.EXIT_BILLS_FAILED == 3, result.output
    assert stored(db) == ["S1", "S3"]
    assert saved(db).pending == ["S2"]
    assert "Scrape failed: Bills that failed: 1" in result.stderr
    assert "Wrote:" not in result.output
    [run] = runs(db)
    assert run["finished_at"] is not None
    assert run["error"].startswith("ScrapeFailed: ")
    assert run["bills_seen"] == 2


def test_a_revoked_key_partway_exits_3_and_saves_every_bill_it_didnt_finish(db, monkeypatch) -> None:
    api = FakeOpenLeg(
        print_nos=["S1", "S2", "S3"], replies={"S2": status(401, error_code=701)}
    )
    install(monkeypatch, api)

    result = scrape()

    assert result.exit_code == 3, result.output
    assert "HTTP 401 (errorCode 701)" in result.stderr
    assert stored(db) == ["S1"]
    assert saved(db).pending == ["S3", "S2"]


def test_running_out_of_time_before_any_bill_exits_3(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1", "S2"], latency=120.0))

    result = scrape("--time-budget-minutes", "1")

    assert result.exit_code == 3, result.output
    assert stored(db) == []
    assert saved(db).pending == ["S1", "S2"]


# --- Exit 1: no work list, or something unexpected ---------------------------


@pytest.mark.parametrize(
    "reply",
    [status(400, error_code=1), status(401, error_code=701), status(500), httpx.ReadTimeout],
    ids=["400", "401", "500", "timeout"],
)
def test_a_listing_that_fails_exits_1_and_saves_nothing(db, monkeypatch, reply) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1"], replies={BILL_LIST: reply}))

    result = scrape()

    assert result.exit_code == 1, result.output
    assert "Couldn't read the bill list to the end" in result.stderr
    assert stored(db) == []
    assert saved(db) is None
    [run] = runs(db)
    assert run["error"].startswith("ScrapeFailed: ")


def test_a_session_with_no_bills_exits_1(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=[]))

    result = scrape()

    assert result.exit_code == 1, result.output
    assert "came back empty" in result.stderr
    assert saved(db) is None


def test_a_feed_that_fails_exits_1_and_keeps_the_last_saved_place(db, monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"], replies={NOTED_TIME: status(500)})
    install(monkeypatch, api)
    before = save(db, "S1")

    result = scrape()

    assert result.exit_code == 1, result.output
    assert "Couldn't read the update feed to the end" in result.stderr
    assert api.bill_requests() == []
    assert saved(db) == before


def test_a_database_failure_stops_the_run_and_saves_no_place(db, monkeypatch) -> None:
    # Saving a place would tell the next run this bill reached the database.
    install(monkeypatch, FakeOpenLeg(print_nos=["S1", "S2", "S3"]))
    before = save(db, "S1", "S2", "S3")
    real = db_module._insert_actions
    calls = []

    def fails_on_the_second_bill(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(db_module, "_insert_actions", fails_on_the_second_bill)

    result = scrape()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, sqlite3.OperationalError)
    assert saved(db) == before
    [run] = runs(db)
    assert run["finished_at"] is not None
    assert run["error"] == "OperationalError: disk full"
    assert run["bills_seen"] == 1


# --- Runs that save no place -------------------------------------------------


def test_a_limit_run_ignores_the_saved_place_and_saves_none(db, monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3"])
    install(monkeypatch, api)
    before = save(db, "A9")

    result = scrape("--limit", "2")

    assert result.exit_code == 0, result.output
    assert stored(db) == ["S1", "S2"]
    assert saved(db) == before
    assert not [r for r in api.requests if "/updates/" in r.url.path]


def test_a_limit_run_on_a_fresh_database_saves_no_place(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1", "S2", "S3"]))

    result = scrape("--limit", "1")

    assert result.exit_code == 0, result.output
    assert stored(db) == ["S1"]
    assert saved(db) is None


def test_a_failure_in_a_limit_run_exits_1_and_saves_no_place(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1", "S2"], replies={"S1": status(500)}))

    result = scrape("--limit", "2")

    assert result.exit_code == 1, result.output
    assert saved(db) is None


def test_a_dry_run_reads_the_saved_place_and_writes_nothing(db, monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"])
    api.changes = [("2026-11-06T09:30:00", "S2", 2025)]
    install(monkeypatch, api)
    before = save(db)

    result = scrape("--dry-run")

    assert result.exit_code == 0, result.output
    assert "Dry run: 1 bills" in result.output
    assert api.bill_names() == ["S2"]
    assert stored(db) == []
    assert runs(db) == []
    assert saved(db) == before


def test_a_dry_run_that_fails_exits_1_with_the_reason(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1"], replies={BILL_LIST: status(401)}))

    result = scrape("--dry-run")

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "HTTP 401" in result.stderr
    assert saved(db) is None


# --- Options -----------------------------------------------------------------


@pytest.mark.parametrize("minutes", ["0", "-1", "nan-ish"])
def test_a_budget_has_to_be_positive(db, monkeypatch, minutes) -> None:
    api = FakeOpenLeg(print_nos=["S1"])
    install(monkeypatch, api)

    result = scrape("--time-budget-minutes", minutes)

    assert result.exit_code == 2
    assert api.requests == []


def test_a_budget_in_minutes_reaches_the_scraper_in_seconds(db, monkeypatch) -> None:
    install(monkeypatch, FakeOpenLeg(print_nos=["S1"]))
    seen = []
    real = ny_module.NewYorkScraper.__init__

    def spying(self, **kwargs):
        seen.append(kwargs)
        real(self, **kwargs)

    monkeypatch.setattr(ny_module.NewYorkScraper, "__init__", spying)

    assert scrape("--time-budget-minutes", "1.5").exit_code == 0
    assert seen[0]["time_budget"] == 90.0


def test_other_scrapers_refuse_a_budget_before_they_start(db, monkeypatch) -> None:
    def never(*args, **kwargs):
        raise AssertionError("the scraper started")

    monkeypatch.setitem(cli.REGISTRY, "us-ca", never)
    monkeypatch.setattr(never, "supports_refresh_state", False, raising=False)

    result = CliRunner().invoke(
        cli.main, ["scrape", "--jurisdiction", "us-ca", "--time-budget-minutes", "5"]
    )

    assert result.exit_code == 2
    assert "doesn't support --time-budget-minutes" in result.output


# --- Other scrapers keep working the way they did ----------------------------


TEST_SESSION = Session(name="Test session", start_date=date(2025, 1, 1), is_current=True)


def _bill(number: str) -> Bill:
    return Bill(
        jurisdiction="us-ca",
        session_name=TEST_SESSION.name,
        chamber=Chamber.LOWER,
        number=number,
        title=f"Title of {number}",
        source_url=f"https://example.test/{number}",
    )


class _Scraper(BillScraper):
    jurisdiction = "us-ca"
    source_name = "Fake"
    failure: Exception | None = None

    def session(self) -> Session:
        return TEST_SESSION


class _Streaming(_Scraper):
    def scrape(self) -> ScrapeResult:  # pragma: no cover - the CLI prefers bills_iter
        raise AssertionError("the CLI should stream")

    def bills_iter(self):
        yield _bill("AB1")
        if self.failure is not None:
            raise self.failure
        yield _bill("AB2")


class _Bulk(_Scraper):
    def scrape(self) -> ScrapeResult:
        if self.failure is not None:
            raise self.failure
        return ScrapeResult(jurisdiction="us-ca", session=TEST_SESSION, bills=[_bill("AB1")])


def _scrape_ca(monkeypatch, scraper: type[_Scraper], failure: Exception | None = None) -> Result:
    monkeypatch.setitem(cli.REGISTRY, "us-ca", scraper)
    monkeypatch.setattr(scraper, "failure", failure)
    return CliRunner().invoke(cli.main, ["scrape", "--jurisdiction", "us-ca"])


def test_a_streaming_scraper_without_state_exits_0_and_saves_nothing(db, monkeypatch) -> None:
    result = _scrape_ca(monkeypatch, _Streaming)

    assert result.exit_code == 0, result.output
    assert stored(db) == ["AB1", "AB2"]
    assert read_refresh_state("us-ca", TEST_SESSION.name, db) is None


def test_a_scraper_without_state_that_reports_a_failure_exits_1(db, monkeypatch) -> None:
    result = _scrape_ca(monkeypatch, _Streaming, ScrapeFailed("some of it failed"))

    assert result.exit_code == 1
    assert "Scrape failed: some of it failed" in result.stderr
    assert stored(db) == ["AB1"]
    assert read_refresh_state("us-ca", TEST_SESSION.name, db) is None


def test_any_other_exception_from_a_streaming_scraper_keeps_its_type(db, monkeypatch) -> None:
    result = _scrape_ca(monkeypatch, _Streaming, ValueError("boom"))

    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert [run["error"] for run in runs(db)] == ["ValueError: boom"]


def test_a_bulk_scraper_still_writes_after_scraping(db, monkeypatch) -> None:
    written = []
    counts = {"bills_seen": 1, "bills_new": 1, "actions_new": 0}
    monkeypatch.setattr(cli, "write", lambda result: written.append(result) or counts)

    result = _scrape_ca(monkeypatch, _Bulk)

    assert result.exit_code == 0, result.output
    assert [bill.number for bill in written[0].bills] == ["AB1"]


def test_a_bulk_scraper_that_reports_a_failure_exits_1(db, monkeypatch) -> None:
    result = _scrape_ca(monkeypatch, _Bulk, ScrapeFailed("all of it failed"))

    assert result.exit_code == 1
    assert "Scrape failed: all of it failed" in result.stderr


def test_only_new_york_keeps_refresh_state_and_each_scraper_declares_it() -> None:
    # `scrape` reads this attribute from whatever the registry holds.
    for code, scraper in cli.REGISTRY.items():
        assert issubclass(scraper, BillScraper), code
        assert scraper.supports_refresh_state == hasattr(scraper, "next_refresh_state"), code
    keeping = [code for code, scraper in cli.REGISTRY.items() if scraper.supports_refresh_state]
    assert keeping == ["us-ny"]


# --- The key stays out of everything the run leaves behind -------------------


@pytest.mark.parametrize(
    "target, reply",
    [
        (BILL_LIST, status(401, error_code=701)),
        (BILL_LIST, httpx.ReadTimeout),
        (BILL_LIST, status(503)),
        ("S1", status(500)),
        ("S1", status(401, error_code=701)),
        ("S1", httpx.ConnectTimeout),
    ],
    ids=["listing 401", "listing timeout", "listing 503", "bill 500", "bill 401", "bill timeout"],
)
def test_no_output_stored_error_or_traceback_shows_the_key(db, monkeypatch, target, reply) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={target: reply})
    install(monkeypatch, api)

    result = scrape()

    assert result.exit_code != 0
    assert any(KEY in str(request.url) for request in api.requests)
    assert KEY not in result.output
    assert KEY not in result.stderr
    assert KEY not in "".join(traceback.format_exception(*result.exc_info))
    assert all(KEY not in run["error"] for run in runs(db))
