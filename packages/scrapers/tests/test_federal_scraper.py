from __future__ import annotations

from axiom_bills.jurisdictions.us_federal.bill.scrape import FederalScraper


class FakeHttp:
    def __init__(self) -> None:
        self.params = None

    def get_json(self, url: str, *, params: dict) -> dict:
        self.params = params
        return {"bills": [], "pagination": {}}


def test_federal_listing_requests_update_date_desc(monkeypatch) -> None:
    monkeypatch.setenv("CONGRESS_API_KEY", "test-key")
    scraper = FederalScraper(congress=119)
    fake = FakeHttp()
    scraper.http = fake

    assert list(scraper._list_bills()) == []
    assert fake.params is not None
    assert fake.params["sort"] == "updateDate desc"
