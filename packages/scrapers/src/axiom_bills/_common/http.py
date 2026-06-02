"""Shared HTTP client with per-host rate limiting and retries.

The legislative sites we hit have no consistent rate-limit signaling; some
quietly 429 and some just hang up the TCP connection. We enforce a
per-host minimum interval client-side rather than trying to be clever
about Retry-After headers.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class RateLimitedClient:
    """httpx.Client wrapper that holds a min-interval-per-host lock."""

    def __init__(
        self,
        *,
        min_interval_per_host: float = 1.0,
        timeout: float = 30.0,
        user_agent: str = "axiom-bills/0.0.1 (+https://github.com/TheAxiomFoundation/axiom-bills)",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, **(headers or {})},
            follow_redirects=True,
        )
        self._min_interval = min_interval_per_host
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait_for(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = self._min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, url: str, **kwargs) -> httpx.Response:
        self._wait_for(url)
        response = self._client.get(url, **kwargs)
        # Retry on 5xx and 429 but not on 4xx generally.
        if response.status_code >= 500 or response.status_code == 429:
            response.raise_for_status()
        return response

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def post(self, url: str, **kwargs) -> httpx.Response:
        self._wait_for(url)
        response = self._client.post(url, **kwargs)
        if response.status_code >= 500 or response.status_code == 429:
            response.raise_for_status()
        return response

    def get_json(self, url: str, **kwargs):
        return self.get(url, **kwargs).json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RateLimitedClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
