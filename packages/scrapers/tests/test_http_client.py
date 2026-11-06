"""The shared client's retries, on a simulated clock with no network."""
from __future__ import annotations

import types
from collections.abc import Callable

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_bills._common import http as http_module
from axiom_bills._common.base import BillScraper
from axiom_bills._common.http import (
    MAX_JITTER_FRACTION,
    RateLimitedClient,
    RetryDeadlineReached,
    RetryPolicy,
    retry_after_seconds,
)

URL = "https://api.example.test/bills?key=SECRET-KEY-VALUE"
READ_TIMEOUT_STRICT = RetryPolicy(resend_read_timeouts=False)
# Each example builds real httpx clients, which takes hundreds of milliseconds
# on a busy host, so a per-example deadline would only measure the host.
CLIENT_EXAMPLES = settings(deadline=None, max_examples=50)


class SimClock:
    """Stands in for the time module: sleeping moves the clock and costs nothing."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _install(
    mp: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    policy: RetryPolicy = RetryPolicy(),
    min_interval: float = 0.0,
    jitter: float = 0.0,
) -> tuple[RateLimitedClient, SimClock]:
    clock = SimClock()
    mp.setattr(http_module, "time", clock)
    mp.setattr(
        http_module,
        "random",
        types.SimpleNamespace(uniform=lambda low, high: low + (high - low) * jitter),
    )
    client = RateLimitedClient(min_interval_per_host=min_interval, retry_policy=policy)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, clock


def _serve(*replies):
    """A handler that serves replies in order; an exception class gets raised."""
    remaining = list(replies)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = remaining.pop(0)
        if isinstance(reply, type) and issubclass(reply, Exception):
            raise reply("simulated", request=request)
        return reply

    handler.seen = seen
    return handler


def _status(code: int, retry_after: str | None = None) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return httpx.Response(code, headers=headers, json={"success": code < 400})


def test_a_429_waits_as_long_as_retry_after_asks(monkeypatch) -> None:
    handler = _serve(_status(429, "30"), _status(200))
    client, clock = _install(monkeypatch, handler)

    assert client.get(URL).status_code == 200

    assert clock.sleeps == [30.0]
    assert len(handler.seen) == 2


def test_a_503_waits_at_least_its_retry_after_and_keeps_backing_off(monkeypatch) -> None:
    handler = _serve(_status(503, "3"), _status(503), _status(503), _status(200))
    client, clock = _install(monkeypatch, handler)

    assert client.get(URL).status_code == 200

    assert clock.sleeps == [3.0, 2.0, 4.0]


def test_jitter_adds_to_a_wait_and_never_shortens_it(monkeypatch) -> None:
    handler = _serve(_status(429, "30"), _status(200))
    client, clock = _install(monkeypatch, handler, jitter=1.0)

    client.get(URL)

    assert clock.sleeps == [30.0 * (1 + MAX_JITTER_FRACTION)]


def test_the_default_policy_keeps_every_scrapers_patience(monkeypatch) -> None:
    handler = _serve(*[_status(502)] * 6)
    client, clock = _install(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        client.get(URL)

    assert len(handler.seen) == 6
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_the_default_policy_resends_read_timeouts(monkeypatch) -> None:
    handler = _serve(*[httpx.ReadTimeout] * 5, _status(200))
    client, clock = _install(monkeypatch, handler)

    assert client.get(URL).status_code == 200

    assert len(handler.seen) == 6
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_a_scraper_gets_the_default_policy_unless_it_asks_otherwise() -> None:
    class Plain(BillScraper):
        jurisdiction = "us-xx"
        source_name = "test"

        def scrape(self):
            raise NotImplementedError

    scraper = Plain()
    try:
        assert scraper.http._retry_policy == RetryPolicy()
    finally:
        scraper.close()


def test_a_strict_policy_never_resends_a_read_timeout(monkeypatch) -> None:
    handler = _serve(httpx.ReadTimeout)
    client, clock = _install(monkeypatch, handler, policy=READ_TIMEOUT_STRICT)

    with pytest.raises(httpx.ReadTimeout):
        client.get(URL)

    assert len(handler.seen) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError])
def test_a_strict_policy_still_resends_what_never_reached_a_slow_server(monkeypatch, error) -> None:
    handler = _serve(error, _status(200))
    client, _ = _install(monkeypatch, handler, policy=READ_TIMEOUT_STRICT)

    assert client.get(URL).status_code == 200

    assert len(handler.seen) == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_other_client_errors_come_straight_back(monkeypatch, code) -> None:
    handler = _serve(_status(code))
    client, clock = _install(monkeypatch, handler)

    assert client.get(URL).status_code == code

    assert len(handler.seen) == 1
    assert clock.sleeps == []


def test_a_policy_can_narrow_the_statuses_it_retries(monkeypatch) -> None:
    policy = RetryPolicy(retry_statuses=frozenset({429, 503}))
    handler = _serve(_status(500))
    client, clock = _install(monkeypatch, handler, policy=policy)

    assert client.get(URL).status_code == 500

    assert len(handler.seen) == 1
    assert clock.sleeps == []


def test_a_wait_longer_than_we_accept_gets_no_early_retry(monkeypatch) -> None:
    handler = _serve(_status(429, "3600"))
    client, clock = _install(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.get(URL)

    assert caught.value.response.status_code == 429
    assert len(handler.seen) == 1
    assert clock.sleeps == []


def test_a_retry_stops_before_it_would_sleep_past_the_deadline(monkeypatch) -> None:
    handler = _serve(_status(429, "30"), _status(200))
    client, clock = _install(monkeypatch, handler)
    client.retry_deadline = clock.now + 29

    with pytest.raises(RetryDeadlineReached):
        client.get(URL)

    assert len(handler.seen) == 1
    assert clock.sleeps == []


def test_a_retry_that_fits_before_the_deadline_goes_ahead(monkeypatch) -> None:
    handler = _serve(_status(429, "30"), _status(200))
    client, clock = _install(monkeypatch, handler)
    client.retry_deadline = clock.now + 31

    assert client.get(URL).status_code == 200

    assert clock.sleeps == [30.0]


def test_post_takes_the_same_retries(monkeypatch) -> None:
    handler = _serve(_status(503, "5"), _status(200))
    client, clock = _install(monkeypatch, handler)

    assert client.post(URL, content=b"{}").status_code == 200

    assert [request.method for request in handler.seen] == ["POST", "POST"]
    assert clock.sleeps == [5.0]


@pytest.mark.parametrize(
    "replies",
    [
        [_status(500)] * 6,
        [_status(429, "3600")],
    ],
)
def test_a_status_error_keeps_the_query_string_out_of_its_text(monkeypatch, replies) -> None:
    client, _ = _install(monkeypatch, _serve(*replies))

    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.get(URL)

    assert "SECRET-KEY-VALUE" not in str(caught.value)
    assert "api.example.test/bills" in str(caught.value)


def test_retry_after_reads_an_http_date(monkeypatch) -> None:
    class Later(http_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 6, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(http_module, "datetime", Later)
    response = _status(429, "Fri, 06 Nov 2026 12:00:45 GMT")

    assert retry_after_seconds(response) == 45.0


def test_retry_after_in_the_past_asks_for_no_wait() -> None:
    assert retry_after_seconds(_status(429, "Thu, 01 Jan 2015 00:00:00 GMT")) == 0.0


@pytest.mark.parametrize("raw", ["", "soon", "-5", "1.5", "NaN", "inf", "٣"])
def test_retry_after_ignores_what_it_cannot_read(raw) -> None:
    response = httpx.Response(429, headers=[(b"Retry-After", raw.encode("utf-8"))])

    assert retry_after_seconds(response) is None


def test_retry_after_is_none_when_the_response_sends_none() -> None:
    assert retry_after_seconds(_status(429)) is None


def test_retry_after_with_absurdly_many_digits_is_too_long_to_wait() -> None:
    assert retry_after_seconds(_status(429, "9" * 5000)) == float("inf")


def _header_safe() -> st.SearchStrategy[str]:
    return st.text(st.characters(min_codepoint=32, max_codepoint=126), max_size=40)


@settings(deadline=None)
@given(_header_safe())
def test_retry_after_never_raises_and_never_goes_negative(raw) -> None:
    seconds = retry_after_seconds(_status(429, raw))

    assert seconds is None or seconds >= 0


FAILURES = st.lists(
    st.tuples(
        st.sampled_from([429, 500, 502, 503, 504]),
        st.one_of(st.none(), st.integers(0, 400), st.sampled_from(["soon", "1.5", ""])),
    ),
    min_size=1,
    max_size=9,
)


@CLIENT_EXAMPLES
@given(failures=FAILURES, jitter=st.floats(0, 1))
def test_every_retry_honours_retry_after_backoff_and_the_attempt_limit(failures, jitter) -> None:
    replies = [_status(code, None if asked is None else str(asked)) for code, asked in failures]
    handler = _serve(*replies, _status(200))
    with pytest.MonkeyPatch.context() as mp:
        client, clock = _install(mp, handler, jitter=jitter)
        try:
            client.get(URL)
        except httpx.HTTPStatusError:
            pass

    assert len(handler.seen) <= RetryPolicy().attempts
    assert len(clock.sleeps) == len(handler.seen) - 1
    for index, slept in enumerate(clock.sleeps):
        # The wait the old tenacity policy would have used: this is the patience
        # every scraper relies on, so no retry may come sooner than it did.
        old_wait = max(1.0, min(2.0**index, 120.0))
        asked = failures[index][1]
        asked = asked if isinstance(asked, int) else 0
        assert asked <= RetryPolicy().max_retry_after_seconds
        assert slept >= old_wait
        assert slept >= asked
        assert slept <= max(old_wait, asked) * (1 + MAX_JITTER_FRACTION)


@CLIENT_EXAMPLES
@given(
    latencies=st.lists(st.floats(0, 3), min_size=1, max_size=40),
    min_interval=st.floats(0.01, 2),
)
def test_requests_never_start_closer_together_than_the_minimum_interval(
    latencies, min_interval
) -> None:
    starts: list[float] = []
    remaining = list(latencies)
    with pytest.MonkeyPatch.context() as mp:

        def handler(request: httpx.Request) -> httpx.Response:
            starts.append(clock.now)
            clock.now += remaining.pop(0)
            return _status(200)

        client, clock = _install(mp, handler, min_interval=min_interval)
        for _ in latencies:
            client.get(URL)

    # Rounding in the simulated clock can shave a few ulps off a gap.
    assert all(
        later - earlier >= min_interval - 1e-9 for earlier, later in zip(starts, starts[1:])
    )
