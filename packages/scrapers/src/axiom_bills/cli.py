"""axiom-bills CLI.

```bash
axiom-bills scrape --jurisdiction us --limit 50
axiom-bills scrape --jurisdiction us-ny --limit 50
axiom-bills list
```
"""
from __future__ import annotations

import sys

import click

from ._common.base import BillScraper
from ._common.db import write
from .jurisdictions.us_federal.bill.scrape import FederalScraper
from .jurisdictions.us_ny.bill.scrape import NewYorkScraper
from .jurisdictions.us_co.bill.scrape import ColoradoScraper
from .jurisdictions.us_mn.bill.scrape import MinnesotaScraper

REGISTRY: dict[str, type[BillScraper]] = {
    "us":    FederalScraper,
    "us-ny": NewYorkScraper,
    "us-co": ColoradoScraper,
    "us-mn": MinnesotaScraper,
}


@click.group()
def main() -> None:
    """Bill scrapers for axiom-bills."""


@main.command(name="list")
def list_jurisdictions() -> None:
    """List registered jurisdictions."""
    for code, cls in REGISTRY.items():
        click.echo(f"{code:<8} {cls.source_name}")


@main.command()
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Jurisdiction code to scrape.",
)
@click.option("--limit", "-n", type=int, default=None,
              help="Stop after N bills (smoke testing).")
@click.option("--dry-run", is_flag=True,
              help="Scrape but do not write to Postgres.")
def scrape(jurisdiction: str, limit: int | None, dry_run: bool) -> None:
    """Run a scraper end-to-end."""
    cls = REGISTRY[jurisdiction]
    scraper = cls(limit=limit)
    try:
        result = scraper.scrape()
    finally:
        scraper.close()

    click.echo(f"Scraped {len(result.bills)} bills from {jurisdiction}.")
    if result.notes:
        click.echo(f"Notes: {result.notes}")

    if dry_run:
        click.echo("Dry run — not writing.")
        return

    counts = write(result)
    click.echo(
        f"Wrote: bills_seen={counts['bills_seen']} "
        f"bills_new={counts['bills_new']} actions_new={counts['actions_new']}"
    )


if __name__ == "__main__":
    main()
