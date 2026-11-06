from __future__ import annotations

from axiom_bills._common.models import Chamber
from axiom_bills.jurisdictions.us_ny.bill.scrape import API_ROOT, NewYorkScraper

# The API deprecates these on bill listings and rejects `full=true` from
# December 1, 2026. Its notice asks clients to stop sending them.
REMOVED_LISTING_OPTIONS = {"full", "fullTextFormat"}


class FakeHttp:
    """Serves listing pages and single bills, and records every request."""

    def __init__(self, *, print_nos: list[str], page_size: int = 500) -> None:
        self.print_nos = print_nos
        self.page_size = page_size
        self.requests: list[tuple[str, dict]] = []

    def get_json(self, url: str, *, params: dict) -> dict:
        self.requests.append((url, dict(params)))
        if url == f"{API_ROOT}/bills/2025":
            start = params["offset"] - 1
            page = self.print_nos[start : start + self.page_size]
            return {
                "total": len(self.print_nos),
                "result": {"items": [{"basePrintNo": print_no} for print_no in page]},
            }
        print_no = url.rsplit("/", 1)[-1]
        return {
            "result": {
                "title": f"Title of {print_no}",
                "actions": {
                    "items": [
                        {
                            "date": "2025-01-08",
                            "chamber": "SENATE" if print_no.startswith("S") else "ASSEMBLY",
                            "text": "REFERRED TO FINANCE",
                        }
                    ]
                },
            }
        }

    def listing_requests(self) -> list[dict]:
        return [params for url, params in self.requests if url == f"{API_ROOT}/bills/2025"]


def _scraper(monkeypatch, fake: FakeHttp) -> NewYorkScraper:
    monkeypatch.setenv("NYSENATE_API_KEY", "test-key")
    scraper = NewYorkScraper(session_year=2025)
    scraper.http = fake
    return scraper


def test_new_york_listing_omits_the_removed_options_on_every_page(monkeypatch) -> None:
    fake = FakeHttp(print_nos=[f"S{number}" for number in range(1, 502)])
    scraper = _scraper(monkeypatch, fake)

    assert len(list(scraper._list_bills())) == 501

    listings = fake.listing_requests()
    assert [params["offset"] for params in listings] == [1, 501]
    for params in listings:
        assert not REMOVED_LISTING_OPTIONS & params.keys()


def test_new_york_scrape_builds_each_bill_from_its_own_request(monkeypatch) -> None:
    fake = FakeHttp(print_nos=["S1", "A2"])
    scraper = _scraper(monkeypatch, fake)

    result = scraper.scrape()

    single_bill_requests = [
        (url, params) for url, params in fake.requests if url != f"{API_ROOT}/bills/2025"
    ]
    assert single_bill_requests == [
        (f"{API_ROOT}/bills/2025/S1", {"key": "test-key"}),
        (f"{API_ROOT}/bills/2025/A2", {"key": "test-key"}),
    ]
    assert [bill.number for bill in result.bills] == ["S1", "A2"]
    assert [bill.chamber for bill in result.bills] == [Chamber.UPPER, Chamber.LOWER]
    assert [bill.title for bill in result.bills] == ["Title of S1", "Title of A2"]
    assert [bill.actions[0].action_text for bill in result.bills] == [
        "REFERRED TO FINANCE",
        "REFERRED TO FINANCE",
    ]
