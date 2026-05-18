"""Minnesota bill scraper — stub.

MN revisor publishes bill-status data via
https://www.revisor.mn.gov/bills/status_search.php and individual bill
pages. Bulk daily XML drops exist for journals; bill metadata is
HTML-only and stable enough to parse with selectolax.

This stub establishes the file shape; full implementation is tracked
separately.
"""
from __future__ import annotations

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import ScrapeResult, Session


class MinnesotaScraper(BillScraper):
    jurisdiction = "us-mn"
    source_name = "revisor.mn.gov"
    min_interval_per_host = 1.5

    def scrape(self) -> ScrapeResult:
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=Session(name="93rd Legislature, 2026 Regular", is_current=True),
            bills=[],
            notes={"status": "stub"},
        )
