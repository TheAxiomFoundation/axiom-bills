"""The New York scraper, against a fake of the API its docs describe."""
from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_bills._common.base import ScrapeFailed
from axiom_bills._common.db import write, write_streaming
from axiom_bills._common.http import RetryPolicy
from axiom_bills._common.models import Chamber, RefreshState, ScrapeResult
from axiom_bills.jurisdictions.us_ny.bill.scrape import (
    API_ROOT,
    ET,
    FEED_MARGIN,
    MAX_FAILURES_IN_A_ROW,
    MAX_REMOVALS_IN_A_ROW,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    feed_end,
    feed_start,
)

from .new_york_fakes import (
    EPOCH,
    KEY,
    FakeOpenLeg,
    drain,
    full_bill,
    install,
    make_db,
    numbered,
    scraper_for,
    status,
)

# The API rejects `full=true` on bill listings from December 1, 2026.
REMOVED_LISTING_OPTIONS = {"full", "fullTextFormat"}
BILL_LIST = "/bills/2025"
A_CURSOR = "2026-11-06T09:00:00"


def _state(*pending: str, cursor: str = A_CURSOR) -> RefreshState:
    return RefreshState(feed_cursor=cursor, pending=list(pending))


def _listing_requests(api: FakeOpenLeg) -> list[httpx.Request]:
    return [r for r in api.requests if r.url.path == f"/api/3{BILL_LIST}"]


# --- The bill list -----------------------------------------------------------


def test_the_listing_asks_for_ids_on_every_page_and_omits_the_removed_options(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=list(numbered("S", PAGE_SIZE + 1)))
    install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert failure is None
    assert len(bills) == PAGE_SIZE + 1
    listings = [dict(r.url.params) for r in _listing_requests(api)]
    assert [params["offset"] for params in listings] == ["1", str(PAGE_SIZE + 1)]
    for params in listings:
        assert params["idsOnly"] == "true"
        assert params["limit"] == str(PAGE_SIZE)
        assert params["key"] == KEY
        assert not REMOVED_LISTING_OPTIONS & params.keys()
        # The default order suits us, and the lowercase `desc` this used to send
        # appears nowhere in the docs.
        assert "sort" not in params


def test_each_bill_comes_from_its_own_request_without_its_full_text(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "A2"])
    install(monkeypatch, api)

    result = scraper_for().scrape()

    assert [(r.url.path, dict(r.url.params)) for r in api.bill_requests()] == [
        ("/api/3/bills/2025/S1", {"key": KEY, "view": "no_fulltext"}),
        ("/api/3/bills/2025/A2", {"key": KEY, "view": "no_fulltext"}),
    ]
    assert [bill.number for bill in result.bills] == ["S1", "A2"]
    assert [bill.title for bill in result.bills] == ["Title of S1 v0", "Title of A2 v0"]
    assert [[a.action_text for a in bill.actions] for bill in result.bills] == [
        ["REFERRED TO FINANCE"],
        ["REFERRED TO FINANCE"],
    ]
    assert [[v.label for v in bill.versions] for bill in result.bills] == [
        ["version-original", "version-A"],
        ["version-original", "version-A"],
    ]
    assert [[s.name for s in bill.sponsors] for bill in result.bills] == [
        ["Tony Avella"],
        ["Tony Avella"],
    ]
    assert result.session.name == "2025-2026 Regular Session"


@pytest.mark.parametrize(
    "print_no, chamber",
    [
        ("S1", Chamber.UPPER),
        ("A1", Chamber.LOWER),
        ("J1", Chamber.UPPER),
        ("R1", Chamber.UPPER),
        ("B1", Chamber.UPPER),
        ("K1", Chamber.LOWER),
        ("E1", Chamber.LOWER),
        ("C1", Chamber.LOWER),
    ],
)
def test_the_chamber_comes_from_the_api(monkeypatch, print_no, chamber) -> None:
    api = FakeOpenLeg(print_nos=[print_no])
    install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert failure is None
    assert [bill.chamber for bill in bills] == [chamber]


def test_the_api_decides_the_chamber_even_when_the_prefix_says_otherwise(monkeypatch) -> None:
    body = full_bill("J1")
    body["billType"]["chamber"] = "ASSEMBLY"
    api = FakeOpenLeg(print_nos=["J1"], replies={"J1": httpx.Response(200, json={"result": body})})
    install(monkeypatch, api)

    bills, _ = drain(scraper_for())

    assert [bill.chamber for bill in bills] == [Chamber.LOWER]


@pytest.mark.parametrize(
    "bill_type",
    [None, {}, {"chamber": None}, {"chamber": "JOINT"}, {"chamber": "senate"}],
)
def test_a_chamber_the_api_doesnt_name_fails_the_bill_with_no_guess(monkeypatch, bill_type) -> None:
    body = full_bill("S1")
    body["billType"] = bill_type
    api = FakeOpenLeg(
        print_nos=["S1", "S2"], replies={"S1": httpx.Response(200, json={"result": body})}
    )
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S2"]
    assert failure is not None
    assert scraper.next_refresh_state().pending == ["S1"]


def test_a_limit_stops_the_listing_and_the_run_early(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=list(numbered("S", PAGE_SIZE + 5)))
    install(monkeypatch, api)

    bills, failure = drain(scraper_for(limit=3))

    assert failure is None
    assert [bill.number for bill in bills] == ["S1", "S2", "S3"]
    assert len(_listing_requests(api)) == 1


# --- A list we can't read to the end fails the run ---------------------------


LIST_FAILURES = {
    "400": lambda: status(400, error_code=1),
    "401": lambda: status(401, error_code=701),
    "403": lambda: status(403),
    "404": lambda: status(404),
    "500": lambda: status(500),
    "not json": lambda: httpx.Response(200, text="<html>Sorry</html>"),
    "not an object": lambda: httpx.Response(200, json=[1, 2]),
    "says it failed": lambda: httpx.Response(200, json={"success": False, "result": {"items": []}}),
    "no result": lambda: httpx.Response(200, json={"success": True, "total": 0}),
    "result not an object": lambda: httpx.Response(200, json={"success": True, "result": []}),
    "no total": lambda: httpx.Response(200, json={"success": True, "result": {"items": []}}),
    "total not a number": lambda: httpx.Response(
        200, json={"success": True, "total": "9", "result": {"items": []}}
    ),
    "no items": lambda: httpx.Response(200, json={"success": True, "total": 1, "result": {}}),
    "empty page before the end": lambda: httpx.Response(
        200, json={"success": True, "total": 5, "result": {"items": []}}
    ),
    "item with no print number": lambda: httpx.Response(
        200,
        json={"success": True, "total": 1, "offsetEnd": 1, "result": {"items": [{"session": 2025}]}},
    ),
    "item not an object": lambda: httpx.Response(
        200, json={"success": True, "total": 1, "offsetEnd": 1, "result": {"items": ["S1"]}}
    ),
    "page with no offsetEnd": lambda: httpx.Response(
        200,
        json={"success": True, "total": 2, "result": {"items": [{"basePrintNo": "S1"}]}},
    ),
    "page that doesn't advance": lambda: httpx.Response(
        200,
        json={
            "success": True,
            "total": 2,
            "offsetEnd": 0,
            "result": {"items": [{"basePrintNo": "S1"}]},
        },
    ),
    "read timeout": lambda: httpx.ReadTimeout,
    "connect error": lambda: [httpx.ConnectError] * 5,
    "429 past the ceiling": lambda: status(429, error_code=703, retry_after="3600"),
    "503 past the attempts": lambda: [status(503) for _ in range(5)],
}


@pytest.mark.parametrize("name", LIST_FAILURES)
def test_a_listing_we_cant_read_fails_before_any_bill(monkeypatch, name) -> None:
    api = FakeOpenLeg(print_nos=["S1"], replies={BILL_LIST: LIST_FAILURES[name]()})
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert "bill list" in str(failure)
    assert scraper.next_refresh_state() is None
    assert api.bill_requests() == []


def test_a_listing_that_fails_on_a_later_page_fetches_no_bill(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=list(numbered("S", PAGE_SIZE + 1)))
    first_page = api._page(
        httpx.Request("GET", f"{API_ROOT}{BILL_LIST}", params={"limit": PAGE_SIZE, "offset": 1}),
        [{"basePrintNo": name} for name in api.print_nos],
    )
    api.replies[BILL_LIST] = [first_page, status(500)]
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert scraper.next_refresh_state() is None
    assert api.bill_requests() == []


def test_a_session_with_no_bills_fails_the_run(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=[])
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert "empty" in str(failure)
    assert scraper.next_refresh_state() is None


def test_a_list_that_shrinks_as_we_page_ends_at_the_documented_empty_page(monkeypatch) -> None:
    # The docs warn that lists can change while you page through them.
    first_page = httpx.Response(
        200,
        json={"success": True, "total": 2, "offsetEnd": 1, "result": {"items": [{"basePrintNo": "S1"}]}},
    )
    past_the_end = httpx.Response(
        200, json={"success": True, "total": 1, "result": {"items": [], "size": 0}}
    )
    api = FakeOpenLeg(print_nos=["S1"], replies={BILL_LIST: [first_page, past_the_end]})
    install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert failure is None
    assert [bill.number for bill in bills] == ["S1"]


# --- The update feed ---------------------------------------------------------


def test_a_later_run_reads_the_feed_and_fetches_changes_then_pending(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3", "S4"])
    api.changes = [
        ("2026-11-06T08:30:00", "S3", 2025),
        ("2026-11-06T09:30:00", "S1", 2025),
        ("2026-11-06T09:31:00", "S1", 2025),
        ("2026-11-06T09:32:00", "S2", 2025),
    ]
    clock = install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state("S4", "S2")

    bills, failure = drain(scraper)

    assert failure is None
    assert [bill.number for bill in bills] == ["S3", "S1", "S2", "S4"]
    feed = [r for r in api.requests if "/updates/" in r.url.path]
    end = (clock.utc() - FEED_MARGIN).astimezone(ET).replace(tzinfo=None, microsecond=0)
    assert [r.url.path for r in feed] == [
        f"/api/3/bills/updates/2026-11-06T08:00:00/{end.isoformat()}"
    ]
    assert dict(feed[0].url.params) == {"key": KEY, "limit": str(PAGE_SIZE), "offset": "1"}
    assert _listing_requests(api) == []
    assert scraper.next_refresh_state() == RefreshState(feed_cursor=end.isoformat(), pending=[])


def test_a_real_client_sends_the_feed_range_as_the_docs_show_it(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"])
    install(monkeypatch, api, real_httpx=True)
    scraper = scraper_for()
    scraper.refresh_state = _state()

    drain(scraper)

    assert api.requests[0].url.raw_path.startswith(
        b"/api/3/bills/updates/2026-11-06T08:00:00/2026-11-06T09:58:00?"
    )


def test_the_feed_skips_other_sessions(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"])
    api.changes = [
        ("2026-11-06T09:30:00", "S1", 2023),
        ("2026-11-06T09:31:00", "S2", 2025),
    ]
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state()

    bills, _ = drain(scraper)

    assert [bill.number for bill in bills] == ["S2"]


def test_a_feed_with_no_changes_succeeds_and_moves_the_cursor(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"])
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state()

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is None
    assert scraper.next_refresh_state() == RefreshState(feed_cursor="2026-11-06T09:58:00")


@pytest.mark.parametrize(
    "reply",
    [status(400, error_code=1), status(401, error_code=701), status(500), httpx.ReadTimeout],
)
def test_a_feed_we_cant_read_fails_the_run_and_saves_nothing(monkeypatch, reply) -> None:
    api = FakeOpenLeg(print_nos=["S1"])
    end = "2026-11-06T09:58:00"
    api.replies[f"/bills/updates/2026-11-06T08:00:00/{end}"] = reply
    api.replies[end] = reply
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state("S1")

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert "update feed" in str(failure)
    assert scraper.next_refresh_state() is None


@pytest.mark.parametrize(
    "token",
    [
        {"contentType": "BILL"},
        {"id": None},
        {"id": {"basePrintNo": "S1"}},
        {"id": {"basePrintNo": "S1", "session": "2025"}},
        {"id": {"basePrintNo": "S1", "session": None}},
        {"id": {"session": 2025}},
        "S1",
    ],
)
def test_an_update_we_cant_place_fails_the_run(monkeypatch, token) -> None:
    # Skipping it would lose that change for good, since the cursor moves past it.
    api = FakeOpenLeg(print_nos=["S1"])
    api.replies["2026-11-06T09:58:00"] = httpx.Response(
        200, json={"success": True, "total": 1, "offsetEnd": 1, "result": {"items": [token]}}
    )
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state()

    _, failure = drain(scraper)

    assert failure is not None
    assert scraper.next_refresh_state() is None


def test_a_saved_cursor_that_isnt_a_time_fails_the_run(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"])
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state(cursor="yesterday")

    _, failure = drain(scraper)

    assert failure is not None
    assert "yesterday" in str(failure)
    assert api.requests == []


def test_a_first_run_notes_the_time_before_it_starts_the_load(monkeypatch) -> None:
    # The guide's order: a bill that changes during the load then falls inside the
    # next run's range. The overlap hides a mistake here from any end-to-end check,
    # so look at the cursor itself.
    api = FakeOpenLeg(print_nos=["S1", "S2"], latency=300.0)
    clock = install(monkeypatch, api)
    noted = feed_end(clock.utc())
    scraper = scraper_for()

    drain(scraper)

    assert clock.utc() > EPOCH + timedelta(minutes=10)
    assert scraper.next_refresh_state().feed_cursor == noted.isoformat()


def test_a_later_run_notes_the_time_before_it_reads_the_feed(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"], latency=300.0)
    clock = install(monkeypatch, api)
    noted = feed_end(clock.utc())
    scraper = scraper_for()
    scraper.refresh_state = _state("S1")

    drain(scraper)

    assert scraper.next_refresh_state().feed_cursor == noted.isoformat()


def test_feed_end_sits_two_minutes_back_in_new_york_time_with_no_offset() -> None:
    end = feed_end(datetime(2026, 11, 6, 15, 0, 30, 999, tzinfo=timezone.utc))

    assert end == datetime(2026, 11, 6, 9, 58, 30)
    assert end.tzinfo is None


REPEATED_HOUR = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)  # 1 a.m. EDT
SKIPPED_HOUR = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)    # 2 a.m. EST, 3 a.m. EDT


def _label(instant: datetime) -> datetime:
    return instant.astimezone(ET).replace(tzinfo=None)


@settings(deadline=None, max_examples=300)
@given(
    transition=st.sampled_from([REPEATED_HOUR, SKIPPED_HOUR]),
    load_at=st.integers(-7_200, 7_200),
    # Seconds after the load.
    poll_gaps=st.lists(st.integers(1, 7_200), min_size=1, max_size=8),
    change_offsets=st.lists(st.integers(1, 30_000), min_size=1, max_size=8),
)
def test_consecutive_feed_ranges_miss_no_change_across_a_clock_change(
    transition, load_at, poll_gaps, change_offsets
) -> None:
    load = transition + timedelta(seconds=load_at)
    polls = []
    at = load
    for gap in poll_gaps:
        at += timedelta(seconds=gap)
        polls.append(at)
    # A last poll long after every change and the clock change.
    changes = [load + timedelta(seconds=offset) for offset in change_offsets]
    polls.append(max([*polls, *changes, transition]) + timedelta(hours=3))

    ranges = []
    cursor = feed_end(load)
    for poll in polls:
        end = feed_end(poll)
        ranges.append((poll, feed_start(cursor), end))
        cursor = end

    for _, start, end in ranges:
        assert start < end, "a range has to start before it ends"
    for change in changes:
        label = _label(change)
        assert any(
            change < poll and start <= label < end for poll, start, end in ranges
        ), f"no range covered the change at {change}"


# --- Failures partway through a run ------------------------------------------


@pytest.mark.parametrize(
    "reply, code",
    [
        (status(400, error_code=1), 400),
        (status(401, error_code=701), 401),
        (status(403), 403),
        (status(429, error_code=703, retry_after="3600"), 429),
    ],
)
def test_a_client_error_stops_the_run_at_once_and_keeps_what_it_got(monkeypatch, reply, code) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3", "S4"], replies={"S2": reply})
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1"]
    assert api.bill_names() == ["S1", "S2"]
    assert failure is not None
    assert f"HTTP {code}" in str(failure)
    # The failed bill goes last, so it can't hold up the others.
    assert scraper.next_refresh_state().pending == ["S3", "S4", "S2"]


def test_failures_in_a_row_stop_the_run(monkeypatch) -> None:
    names = list(numbered("S", MAX_FAILURES_IN_A_ROW + 3))
    api = FakeOpenLeg(print_nos=names, replies={n: status(500) for n in names[1:]})
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1"]
    assert len(api.bill_requests()) == 1 + MAX_FAILURES_IN_A_ROW
    assert failure is not None
    state = scraper.next_refresh_state()
    assert set(state.pending) == set(names[1:])
    assert state.pending[-MAX_FAILURES_IN_A_ROW:] == names[1 : 1 + MAX_FAILURES_IN_A_ROW]


def test_scattered_failures_dont_stop_the_run_but_still_fail_it(monkeypatch) -> None:
    names = list(numbered("S", 7))
    api = FakeOpenLeg(print_nos=names, replies={"S2": status(500), "S5": httpx.ReadTimeout})
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1", "S3", "S4", "S6", "S7"]
    assert failure is not None
    assert "Bills that failed: 2" in str(failure)
    assert "HTTP 500" in str(failure)
    assert "ReadTimeout" in str(failure)
    assert scraper.next_refresh_state().pending == ["S2", "S5"]


@pytest.mark.parametrize(
    "reply",
    [
        lambda: httpx.Response(200, json={"success": True}),
        lambda: httpx.Response(200, json={"success": False, "result": full_bill("S1")}),
        lambda: httpx.Response(200, text="not json"),
        lambda: httpx.Response(
            200,
            json={"success": True, "result": {**full_bill("S1"), "actions": {"items": [{"text": "X"}]}}},
        ),
    ],
)
def test_an_answer_we_cant_read_fails_the_bill(monkeypatch, reply) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={"S1": reply()})
    install(monkeypatch, api)
    scraper = scraper_for()

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S2"]
    assert failure is not None
    assert scraper.next_refresh_state().pending == ["S1"]


def test_a_404_counts_as_a_removal_not_a_failure(monkeypatch, capsys) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S3"])
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state("S1", "S2", "S3")

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1", "S3"]
    assert failure is None
    assert scraper.next_refresh_state().pending == []
    assert "S2" in capsys.readouterr().err


def test_a_run_of_404s_stops_the_run_and_keeps_those_bills(monkeypatch) -> None:
    gone = list(numbered("A", MAX_REMOVALS_IN_A_ROW))
    api = FakeOpenLeg(print_nos=["S1", "S2"])
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state("S1", *gone, "S2")

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1"]
    assert failure is not None
    assert "404" in str(failure)
    assert scraper.next_refresh_state().pending == ["S2", *gone]


def test_scattered_404s_dont_add_up(monkeypatch) -> None:
    pending: list[str] = []
    for number in range(1, 26):
        pending += [f"S{number}", f"A{number}"]
    api = FakeOpenLeg(print_nos=[n for n in pending if n.startswith("S")])
    install(monkeypatch, api)
    scraper = scraper_for()
    scraper.refresh_state = _state(*pending)

    bills, failure = drain(scraper)

    assert len(bills) == 25
    assert failure is None


# --- The API's retry guidance, end to end -------------------------------------


def test_the_scraper_runs_on_the_apis_published_limits(monkeypatch) -> None:
    api = FakeOpenLeg()
    install(monkeypatch, api)
    scraper = scraper_for()

    assert scraper.http._min_interval == 0.1
    assert scraper.http._retry_policy == RetryPolicy(
        attempts=5, retry_statuses=frozenset({429, 503}), resend_read_timeouts=False
    )
    assert scraper.http._client.kwargs["timeout"] is REQUEST_TIMEOUT
    assert REQUEST_TIMEOUT.read == 120.0
    assert REQUEST_TIMEOUT.connect == 15.0


def test_a_slow_request_gets_sent_once(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={"S1": httpx.ReadTimeout})
    clock = install(monkeypatch, api)

    bills, _ = drain(scraper_for())

    assert api.bill_names() == ["S1", "S2"]
    assert [bill.number for bill in bills] == ["S2"]
    assert not [slept for slept in clock.sleeps if slept >= 1]


def test_a_connection_that_never_opened_gets_tried_again(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"], replies={"S1": [httpx.ConnectError]})
    install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert api.bill_names() == ["S1", "S1"]
    assert [bill.number for bill in bills] == ["S1"]
    assert failure is None


def test_a_429_waits_as_long_as_it_asks(monkeypatch) -> None:
    api = FakeOpenLeg(
        print_nos=["S1"],
        replies={"S1": [status(429, error_code=703, retry_after="30")]},
    )
    clock = install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert [bill.number for bill in bills] == ["S1"]
    assert failure is None
    assert 30.0 in clock.sleeps


def test_a_503_backs_off_and_gives_up_after_a_few_attempts(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={"S1": [status(503) for _ in range(9)]})
    clock = install(monkeypatch, api)

    bills, failure = drain(scraper_for())

    assert api.bill_names().count("S1") == 5
    assert [slept for slept in clock.sleeps if slept >= 1] == [1.0, 2.0, 4.0, 8.0]
    assert [bill.number for bill in bills] == ["S2"]
    assert failure is not None


def test_a_500_gets_no_retry(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"], replies={"S1": [status(500)]})
    install(monkeypatch, api)

    _, failure = drain(scraper_for())

    assert api.bill_names() == ["S1"]
    assert failure is not None


def test_requests_start_at_least_a_tenth_of_a_second_apart(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=list(numbered("S", 50)))
    clock = install(monkeypatch, api)
    starts: list[float] = []
    serve = api.__class__.__call__

    def stamping(self, request):
        starts.append(clock.now)
        return serve(self, request)

    monkeypatch.setattr(api.__class__, "__call__", stamping)

    drain(scraper_for())

    assert len(starts) == 51
    assert all(later - earlier >= 0.1 - 1e-9 for earlier, later in zip(starts, starts[1:]))


# --- The time budget ----------------------------------------------------------


def test_the_budget_ends_the_run_without_failing_it(monkeypatch) -> None:
    names = list(numbered("S", 100))
    api = FakeOpenLeg(print_nos=names, latency=1.0)
    install(monkeypatch, api)
    scraper = scraper_for(time_budget=10.0)

    bills, failure = drain(scraper)

    assert failure is None
    assert scraper.out_of_time is True
    assert 0 < len(bills) < 100
    assert scraper.next_refresh_state().pending == names[len(bills):]


def test_a_budget_the_run_doesnt_need_changes_nothing(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], latency=1.0)
    install(monkeypatch, api)
    scraper = scraper_for(time_budget=100.0)

    bills, failure = drain(scraper)

    assert failure is None
    assert scraper.out_of_time is False
    assert scraper.next_refresh_state().pending == []
    assert len(bills) == 2


def test_a_retry_that_would_cross_the_budget_ends_the_run(monkeypatch) -> None:
    api = FakeOpenLeg(
        print_nos=["S1", "S2", "S3"],
        replies={"S2": [status(429, error_code=703, retry_after="300")]},
    )
    clock = install(monkeypatch, api)
    scraper = scraper_for(time_budget=60.0)

    bills, failure = drain(scraper)

    assert [bill.number for bill in bills] == ["S1"]
    assert failure is None
    assert scraper.out_of_time is True
    assert scraper.next_refresh_state().pending == ["S2", "S3"]
    assert max(clock.sleeps) < 1


def test_running_out_of_budget_before_any_bill_fails_the_run(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], latency=20.0)
    install(monkeypatch, api)
    scraper = scraper_for(time_budget=10.0)

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert scraper.out_of_time is True
    assert scraper.next_refresh_state().pending == ["S1", "S2"]


def test_a_retry_during_the_listing_that_would_cross_the_budget_fails_the_run(monkeypatch) -> None:
    api = FakeOpenLeg(
        print_nos=["S1"], replies={BILL_LIST: [status(429, retry_after="300")]}
    )
    install(monkeypatch, api)
    scraper = scraper_for(time_budget=60.0)

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert scraper.next_refresh_state() is None


def test_a_listing_too_slow_for_the_budget_stops_at_the_budget(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=list(numbered("S", PAGE_SIZE * 3)), latency=100.0)
    clock = install(monkeypatch, api)
    start = clock.now
    scraper = scraper_for(time_budget=150.0)

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert "time budget" in str(failure)
    assert len(_listing_requests(api)) == 2
    assert clock.now - start < 150.0 + 100.0 + 0.2
    assert scraper.next_refresh_state() is None


def test_a_feed_too_slow_for_the_budget_stops_at_the_budget(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1"], latency=100.0)
    api.changes = [("2026-11-06T09:30:00", "S1", 2025)] * (PAGE_SIZE * 3)
    clock = install(monkeypatch, api)
    start = clock.now
    scraper = scraper_for(time_budget=150.0)
    scraper.refresh_state = _state("S1")

    bills, failure = drain(scraper)

    assert bills == []
    assert failure is not None
    assert "time budget" in str(failure)
    assert clock.now - start < 150.0 + 100.0 + 0.2
    assert scraper.next_refresh_state() is None


# --- Nothing lost, nothing mistaken for success -------------------------------


def test_a_bill_the_caller_didnt_keep_stays_pending(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2", "S3"])
    install(monkeypatch, api)
    scraper = scraper_for()

    stream = scraper.bills_iter()
    first = next(stream)
    second = next(stream)
    # The caller's write of S2 fails here, so it never comes back for S3.
    stream.close()

    assert (first.number, second.number) == ("S1", "S2")
    assert scraper.next_refresh_state().pending == ["S2", "S3"]


def test_scrape_raises_when_a_bill_failed(monkeypatch) -> None:
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={"S1": status(500)})
    install(monkeypatch, api)

    with pytest.raises(ScrapeFailed):
        scraper_for().scrape()


def test_scrape_and_bills_iter_agree(monkeypatch) -> None:
    names = ["S1", "A2", "J3", "K4"]
    install(monkeypatch, FakeOpenLeg(print_nos=names))
    from_scrape = scraper_for().scrape()
    install(monkeypatch, FakeOpenLeg(print_nos=names))
    from_iter = list(scraper_for().bills_iter())

    assert from_scrape.bills == from_iter


def test_the_streaming_and_bulk_writers_store_the_same_bills(monkeypatch, tmp_path) -> None:
    import sqlite3

    names = ["S1", "A2", "J3", "K4"]
    install(monkeypatch, FakeOpenLeg(print_nos=names))
    scraper = scraper_for()
    bills = list(scraper.bills_iter())
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    bulk = make_db(tmp_path / "a")
    streaming = make_db(tmp_path / "b")

    bulk_counts = write(
        ScrapeResult(jurisdiction="us-ny", session=scraper.session(), bills=bills), bulk
    )
    stream_counts = write_streaming("us-ny", scraper.session(), iter(bills), streaming)

    assert bulk_counts == stream_counts

    def stored(path: str) -> list[tuple]:
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT b.chamber, b.number, b.title, b.kind, b.current_status, "
            "a.action_text, a.normalized_status "
            "FROM bills b JOIN bill_actions a ON a.bill_id = b.id ORDER BY b.number"
        ).fetchall()
        conn.close()
        return rows

    assert stored(bulk) == stored(streaming)
    assert len(stored(bulk)) == 4


class _ErrorNamingItsUrl(httpx.ConnectError):
    """httpx promises nothing about what its errors say, so assume the worst."""

    def __init__(self, message: str, *, request: httpx.Request) -> None:
        super().__init__(f"{message}: couldn't reach {request.url}", request=request)


class _ReadErrorNamingItsUrl(httpx.ReadError):
    def __init__(self, message: str, *, request: httpx.Request) -> None:
        super().__init__(f"{message}: lost {request.url}", request=request)


FAILURE_MODES = {
    "listing error naming its url": (BILL_LIST, lambda: [_ErrorNamingItsUrl] * 5),
    "listing read error naming its url": (BILL_LIST, lambda: _ReadErrorNamingItsUrl),
    "bill error naming its url": ("S1", lambda: [_ErrorNamingItsUrl] * 5),
    "bill read error naming its url": ("S1", lambda: _ReadErrorNamingItsUrl),
    "listing 401": (BILL_LIST, lambda: status(401, error_code=701)),
    "listing timeout": (BILL_LIST, lambda: httpx.ReadTimeout),
    "listing connect error": (BILL_LIST, lambda: [httpx.ConnectError] * 5),
    "listing 503s": (BILL_LIST, lambda: [status(503) for _ in range(5)]),
    "listing 429": (BILL_LIST, lambda: status(429, retry_after="3600")),
    "listing not json": (BILL_LIST, lambda: httpx.Response(200, text=f"bad {KEY}")),
    "bill 401": ("S1", lambda: status(401, error_code=701)),
    "bill 500": ("S1", lambda: status(500)),
    "bill 503s": ("S1", lambda: [status(503) for _ in range(5)]),
    "bill 429": ("S1", lambda: status(429, retry_after="3600")),
    "bill timeout": ("S1", lambda: httpx.ReadTimeout),
    "bill connect error": ("S1", lambda: [httpx.ConnectError] * 5),
    "bill too many redirects": ("S1", lambda: httpx.TooManyRedirects),
    "bill not json": ("S1", lambda: httpx.Response(200, text=f"bad {KEY}")),
    "bill unreadable": ("S1", lambda: httpx.Response(200, json={"result": {"title": KEY}})),
    # Each of these names the deadline, so make sure that message stays clean too.
    "listing retry past the budget": (BILL_LIST, lambda: status(429, retry_after="299")),
    "bill retry past the budget, first": ("S1", lambda: status(429, retry_after="299")),
}


@pytest.mark.parametrize("real_httpx", [False, True], ids=["fast", "real httpx"])
@pytest.mark.parametrize("mode", FAILURE_MODES)
def test_no_failure_shows_the_key(monkeypatch, capsys, mode, real_httpx) -> None:
    target, reply = FAILURE_MODES[mode]
    api = FakeOpenLeg(print_nos=["S1", "S2"], replies={target: reply()})
    install(monkeypatch, api, real_httpx=real_httpx)
    budget = 10.0 if "past the budget" in mode else None

    _, failure = drain(scraper_for(time_budget=budget))

    assert failure is not None
    shown = "".join(traceback.format_exception(failure))
    captured = capsys.readouterr()
    assert KEY not in shown
    assert KEY not in captured.out
    assert KEY not in captured.err
    # The API did see the key, so the check above means something.
    assert any(KEY in str(request.url) for request in api.requests)


OUTCOMES = {
    "ok": None,
    "gone": lambda: status(404),
    "500": lambda: status(500),
    "401": lambda: status(401, error_code=701),
    "429": lambda: status(429, retry_after="3600"),
    "timeout": lambda: httpx.ReadTimeout,
    "unreadable": lambda: httpx.Response(200, json={"result": {}}),
    "503, then fine": lambda: [status(503)],
    "503 for good": lambda: [status(503) for _ in range(9)],
    "429 with a wait": lambda: [status(429, retry_after="5")],
    "connect errors": lambda: [httpx.ConnectError] * 9,
}
PRINT_NUMBERS = st.lists(st.integers(1, 60), unique=True, max_size=25).map(
    lambda numbers: [f"S{number}" for number in numbers]
)


@settings(deadline=None, max_examples=300)
@given(
    names=PRINT_NUMBERS,
    outcome_of=st.lists(st.sampled_from(sorted(OUTCOMES)), min_size=60, max_size=60),
    latency=st.sampled_from([0.0, 0.05, 2.0]),
    budget=st.one_of(st.none(), st.floats(0.5, 40)),
    resume=st.booleans(),
    # Bills that show up in the feed as well as the saved list, and print numbers
    # the saved list repeats, must not get fetched twice.
    feed_too=st.integers(0, 3),
    caller_stops_after=st.one_of(st.none(), st.integers(0, 25)),
)
def test_every_bill_a_run_names_ends_up_exactly_one_way(
    names, outcome_of, latency, budget, resume, feed_too, caller_stops_after
) -> None:
    replies = {}
    for name in names:
        reply = OUTCOMES[outcome_of[int(name[1:]) - 1]]
        if reply is not None:
            replies[name] = reply()
    api = FakeOpenLeg(print_nos=list(names), replies=replies, latency=latency)
    api.changes = [("2026-11-06T09:30:00", name, 2025) for name in names[:feed_too]]
    with pytest.MonkeyPatch.context() as mp:
        clock = install(mp, api)
        start = clock.now
        scraper = scraper_for(time_budget=budget)
        if resume:
            scraper.refresh_state = _state(*names, *names[:feed_too])
        kept: list[str] = []
        failure = None
        stream = scraper.bills_iter()
        try:
            for bill in stream:
                if caller_stops_after is not None and len(kept) >= caller_stops_after:
                    stream.close()
                    break
                kept.append(bill.number)
        except ScrapeFailed as error:
            failure = error

    # A run stops within its budget and one more request: the pacing wait, then
    # a request that takes as long as any request here takes.
    if budget is not None:
        assert clock.now - start <= budget + latency + 0.1 + 1e-6

    state = scraper.next_refresh_state()
    if state is None:
        # Only a run that never got its work list has no state, and it kept nothing.
        assert failure is not None
        assert kept == []
        return
    # Every bill the run named ends up kept, removed or pending, and only one of
    # them, whatever the feed and the saved list repeat.
    assert sorted(kept + scraper._removed + state.pending) == sorted(names)
    # A clean finish leaves nothing behind.
    if failure is None and not scraper.out_of_time and caller_stops_after is None:
        assert state.pending == []
    # The run fails if and only if a bill failed, or the budget ran out before any
    # bill came back. A caller that stops early never hears how the run would end.
    if caller_stops_after is None:
        expected = bool(scraper._failed) or (scraper.out_of_time and not kept)
        assert (failure is not None) == expected


def _run(api: FakeOpenLeg, state: RefreshState | None, budget: float | None) -> tuple:
    scraper = scraper_for(time_budget=budget)
    scraper.refresh_state = state
    before = api.clock.now
    bills, failure = drain(scraper)
    return bills, failure, scraper.next_refresh_state() or state, api.clock.now - before


@settings(deadline=None, max_examples=60)
@given(
    count=st.integers(1, 40),
    runs=st.lists(
        st.tuples(
            # Bills that change before the run, as indexes.
            st.lists(st.integers(0, 39), max_size=6),
            # Bills that fail during the run.
            st.lists(st.integers(0, 39), max_size=6),
            st.floats(0.5, 10),
        ),
        max_size=6,
    ),
)
def test_runs_converge_on_the_latest_version_of_every_bill(count, runs) -> None:
    names = [f"S{number}" for number in range(count)]
    api = FakeOpenLeg(print_nos=names, latency=0.2)
    latest_seen: dict[str, str] = {}
    state: RefreshState | None = None
    with pytest.MonkeyPatch.context() as mp:
        clock = install(mp, api)
        for changed, failing, budget in runs:
            clock.now += 600
            for index in changed:
                if index < count:
                    api.change(names[index], clock.utc())
            api.replies = {names[i]: status(500) for i in failing if i < count}
            bills, _, state, _ = _run(api, state, budget)
            latest_seen.update({bill.number: bill.title for bill in bills})
        # One clean run with time to spare, once the API has saved the last change.
        api.replies = {}
        clock.now += 600
        bills, failure, state, _ = _run(api, state, None)
        assert failure is None
        latest_seen.update({bill.number: bill.title for bill in bills})

    assert state.pending == []
    assert latest_seen == {
        name: f"Title of {name} v{api.versions.get(name, 0)}" for name in names
    }


# --- The numbers this design rests on -----------------------------------------


BUDGET_SECONDS = 28 * 60
# The longest a run can pass its budget: one request that takes the whole
# connect and read timeouts.
LONGEST_OVERRUN = REQUEST_TIMEOUT.connect + REQUEST_TIMEOUT.read


@pytest.mark.parametrize(
    "bills_in_session, budget, latency, runs_needed",
    [
        # The real numbers.
        (25_500, BUDGET_SECONDS, 0.3, 5),
        # A tenth of the bills and a tenth of the budget give the same run counts
        # as the real numbers, in a tenth of the test's time. The pacing sets a
        # run's length when the API answers faster than 0.1 seconds.
        (2_550, BUDGET_SECONDS / 10, 0.05, 2),
        (2_550, BUDGET_SECONDS / 10, 0.5, 8),
    ],
)
def test_a_full_load_spreads_across_runs_that_each_fit_the_budget(
    monkeypatch, bills_in_session, budget, latency, runs_needed
) -> None:
    names = [f"S{number}" for number in range(bills_in_session)]
    api = FakeOpenLeg(print_nos=names, latency=latency)
    clock = install(monkeypatch, api)

    fetched: list[str] = []
    state: RefreshState | None = None
    run_count = 0
    while state is None or state.pending:
        clock.now += 3_600
        bills, failure, state, took = _run(api, state, budget)
        assert failure is None
        assert took <= budget + LONGEST_OVERRUN
        fetched.extend(bill.number for bill in bills)
        run_count += 1
        assert run_count <= runs_needed

    assert run_count == runs_needed
    assert fetched == names

    # With the load done, a routine run fetches only what changed.
    clock.now += 3_600
    for name in names[:40]:
        api.change(name, clock.utc() - timedelta(minutes=30))
    api.requests.clear()
    bills, failure, state, took = _run(api, state, budget)
    assert failure is None
    assert [bill.number for bill in bills] == names[:40]
    assert len(api.requests) == 41
    assert took < 60
    assert state.pending == []


def test_a_budget_of_28_minutes_caps_a_run_at_16800_bills(monkeypatch) -> None:
    names = [f"S{number}" for number in range(20_000)]
    api = FakeOpenLeg(print_nos=names, latency=0.0)
    install(monkeypatch, api)

    bills, failure, state, _ = _run(api, None, BUDGET_SECONDS)

    assert failure is None
    assert 16_700 <= len(bills) <= 16_800
    assert len(state.pending) == len(names) - len(bills)
