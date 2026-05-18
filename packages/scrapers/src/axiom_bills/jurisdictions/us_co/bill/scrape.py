"""Colorado bill scraper — stub.

Colorado publishes bills at https://leg.colorado.gov/bills, with a
filterable list and per-bill history pages. The list page uses a Drupal
view with JSON API endpoints exposed under /views/ajax — easier to hit
than the HTML, but undocumented and may change without notice.

This stub establishes the file shape; full implementation is tracked
separately. It returns an empty ScrapeResult so the CLI exits cleanly
when CO is requested.
"""
from __future__ import annotations

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import ScrapeResult, Session


class ColoradoScraper(BillScraper):
    jurisdiction = "us-co"
    source_name = "leg.colorado.gov"
    min_interval_per_host = 1.5

    def scrape(self) -> ScrapeResult:
        # TODO: list bills via /bills?type=Bill&session=2026A endpoint,
        # then parse per-bill history table for actions. See PE
        # state-legislative-tracker for a working reference scrape, but
        # do not depend on it.
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=Session(name="2026 Regular Session", is_current=True),
            bills=[],
            notes={"status": "stub"},
        )
