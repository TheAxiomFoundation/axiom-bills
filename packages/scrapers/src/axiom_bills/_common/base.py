"""BillScraper base class.

Every per-jurisdiction scraper subclasses BillScraper, implements
`scrape()`, and registers itself in axiom_bills.cli.REGISTRY.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .http import RateLimitedClient
from .models import ScrapeResult


class ScrapeFailed(Exception):
    """A scrape didn't get everything it set out to get.

    A streaming scraper raises this after yielding the bills it did get, so its
    caller keeps them and still can't mistake the run for a success. The text
    never holds a URL, because some APIs take their key in the query string.
    """


class BillScraper(ABC):
    jurisdiction: str             # e.g. 'us', 'us-ny'
    source_name: str              # e.g. 'Congress.gov'
    min_interval_per_host: float = 1.0
    verify_tls: bool = True
    # True for a scraper that takes a time_budget, starts from its refresh_state
    # attribute and offers next_refresh_state().
    supports_refresh_state: bool = False

    def __init__(self, *, limit: int | None = None) -> None:
        self.limit = limit
        self.http = RateLimitedClient(
            min_interval_per_host=self.min_interval_per_host,
            verify=self.verify_tls,
        )

    @abstractmethod
    def scrape(self) -> ScrapeResult:
        """Return all bills for the current session.

        Implementations must respect `self.limit` for smoke testing.
        Actions must include normalized_status where the scraper can
        determine it; otherwise leave None and let downstream rollup
        leave the bill at UNKNOWN rather than guessing.
        """

    def close(self) -> None:
        self.http.close()
