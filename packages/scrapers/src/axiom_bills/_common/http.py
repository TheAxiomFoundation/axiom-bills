"""Shared HTTP client with per-host rate limiting and retries.

The legislative sites we hit signal rate limits inconsistently: some quietly
429 and some just hang up the TCP connection. So we always enforce a per-host
minimum interval client-side, and when a response says how long to wait
(Retry-After), we never retry sooner than it asks.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

# Backoff doubles from one second, up to this.
MAX_BACKOFF_SECONDS = 120.0
# A wait runs up to this fraction over its base, so that clients which failed
# together don't all come back together.
MAX_JITTER_FRACTION = 0.25


@dataclass(frozen=True)
class RetryPolicy:
    """Which failures a RateLimitedClient retries, and how many times.

    The defaults suit any source that publishes no rules of its own. A scraper
    whose API does publish them passes its own policy.
    """

    # 6 attempts wait 1, 2, 4, 8 and 16 seconds between them, and each attempt
    # can take the client's whole timeout, so a default client rides out about
    # 3.5 minutes of stalled requests. 4 attempts capped at 30s killed a
    # 58-minute full federal refresh when Congress.gov had a slow spell — one
    # lost run costs far more than a few minutes of patience.
    attempts: int = 6
    # A response that asks for a longer wait than this gets no retry: we won't
    # come back sooner than it asks, and one request can't hold a run that long.
    max_retry_after_seconds: float = 300.0
    # The statuses to retry. None means every 5xx and 429.
    retry_statuses: frozenset[int] | None = None
    # Whether to resend a request that timed out waiting for its response. The
    # server may still be working on it, which counts against some APIs' limits.
    resend_read_timeouts: bool = True

    def retries_status(self, status_code: int) -> bool:
        if self.retry_statuses is not None:
            return status_code in self.retry_statuses
        return status_code >= 500 or status_code == 429

    def resends(self, error: httpx.TransportError) -> bool:
        return self.resend_read_timeouts or not isinstance(error, httpx.ReadTimeout)


class RetryDeadlineReached(Exception):
    """A retry would have slept past the deadline its caller set."""


def retry_after_seconds(response: httpx.Response) -> float | None:
    """The wait a response's Retry-After asks for, or None if we can't read one."""
    raw = response.headers.get("Retry-After", "").strip()
    if raw.isascii() and raw.isdigit():
        try:
            return float(int(raw))
        except (ValueError, OverflowError):
            # More digits than a number can hold: it asks for longer than we'd wait.
            return float("inf")
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _status_error(response: httpx.Response) -> httpx.HTTPStatusError:
    # raise_for_status() writes the whole URL into its message, and several of
    # our APIs take their key in the query string, so tracebacks would print it.
    request = response.request
    return httpx.HTTPStatusError(
        f"HTTP {response.status_code} from {request.url.copy_with(query=None)}",
        request=request,
        response=response,
    )


def _retry_delay(error: Exception, attempt: int, policy: RetryPolicy) -> float | None:
    """Seconds to wait after a failed attempt, or None if we shouldn't retry."""
    wait = min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
    if isinstance(error, httpx.HTTPStatusError):
        asked = retry_after_seconds(error.response)
        if asked is not None:
            if asked > policy.max_retry_after_seconds:
                return None
            wait = max(wait, asked)
    return wait * (1 + random.uniform(0, MAX_JITTER_FRACTION))


class RateLimitedClient:
    """httpx.Client wrapper that holds a min-interval-per-host lock."""

    def __init__(
        self,
        *,
        min_interval_per_host: float = 1.0,
        timeout: float | httpx.Timeout = 30.0,
        user_agent: str = "axiom-bills/0.0.1 (+https://github.com/TheAxiomFoundation/axiom-bills)",
        headers: dict[str, str] | None = None,
        verify: bool = True,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, **(headers or {})},
            follow_redirects=True,
            verify=verify,
        )
        self._min_interval = min_interval_per_host
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()
        self._retry_policy = retry_policy
        # time.monotonic() value a retry may not sleep past. None means no limit.
        self.retry_deadline: float | None = None

    def _wait_for(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = self._min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send a request, retrying what the policy allows.

        Returns any response whose status the policy doesn't retry, so callers
        still see a 400 or a 404 and decide for themselves. Raises the last
        error once it runs out of attempts.
        """
        policy = self._retry_policy
        attempt = 1
        while True:
            self._wait_for(url)
            try:
                response = self._client.request(method, url, **kwargs)
                if not policy.retries_status(response.status_code):
                    return response
                raise _status_error(response)
            except httpx.HTTPStatusError as error:
                delay = None if attempt >= policy.attempts else _retry_delay(error, attempt, policy)
                if delay is None:
                    raise
            except httpx.TransportError as error:
                if attempt >= policy.attempts or not policy.resends(error):
                    raise
                delay = _retry_delay(error, attempt, policy)
            if self.retry_deadline is not None and time.monotonic() + delay >= self.retry_deadline:
                raise RetryDeadlineReached(
                    f"{method} attempt {attempt} failed with {delay:.0f}s to wait, past the deadline"
                ) from None
            time.sleep(delay)
            attempt += 1

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs):
        return self.get(url, **kwargs).json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RateLimitedClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
