"""axiom-bills CLI.

```bash
axiom-bills scrape --jurisdiction us --limit 50
axiom-bills scrape --jurisdiction us-ny --limit 50
axiom-bills list
```
"""
from __future__ import annotations

import click

from ._common.base import BillScraper
from ._common.db import (
    DEFAULT_DB,
    connect,
    last_successful_scrape,
    write,
    write_streaming,
)
from ._common.models import NormalizedStatus, STATUS_ORDER
from ._common.status import match_first
from .jurisdictions.us_federal.bill.scrape import FederalScraper
from .jurisdictions.us_federal.bill.status import PATTERNS as FEDERAL_PATTERNS
from .jurisdictions.us_federal.bill.kind import classify as classify_us
from .jurisdictions.us_federal.bill.citations import extract as extract_us
from .jurisdictions.us_ny.bill.scrape import NewYorkScraper
from .jurisdictions.us_ny.bill.status import PATTERNS as NY_PATTERNS
from .jurisdictions.us_ny.bill.kind import classify as classify_us_ny
from .jurisdictions.us_ny.bill.citations import extract as extract_us_ny
from .jurisdictions.us_co.bill.scrape import ColoradoScraper
from .jurisdictions.us_co.bill.status import PATTERNS as CO_PATTERNS
from .jurisdictions.us_co.bill.kind import classify as classify_us_co
from .jurisdictions.us_co.bill.citations import extract as extract_us_co
from .jurisdictions.us_de.bill.scrape import DelawareScraper
from .jurisdictions.us_de.bill.status import PATTERNS as DE_PATTERNS
from .jurisdictions.us_de.bill.kind import classify as classify_us_de
from .jurisdictions.us_de.bill.citations import extract as extract_us_de
from .jurisdictions.us_fl.bill.scrape import FloridaScraper
from .jurisdictions.us_fl.bill.status import PATTERNS as FL_PATTERNS
from .jurisdictions.us_fl.bill.kind import classify as classify_us_fl
from .jurisdictions.us_fl.bill.citations import extract as extract_us_fl
from .jurisdictions.us_md.bill.scrape import MarylandScraper
from .jurisdictions.us_md.bill.status import PATTERNS as MD_PATTERNS
from .jurisdictions.us_md.bill.kind import classify as classify_us_md
from .jurisdictions.us_md.bill.citations import extract as extract_us_md
from .jurisdictions.us_ks.bill.scrape import KansasScraper
from .jurisdictions.us_ks.bill.status import PATTERNS as KS_PATTERNS
from .jurisdictions.us_ks.bill.kind import classify as classify_us_ks
from .jurisdictions.us_ks.bill.citations import extract as extract_us_ks
from .jurisdictions.us_mn.bill.scrape import MinnesotaScraper
from .jurisdictions.us_mn.bill.status import PATTERNS as MN_PATTERNS
from .jurisdictions.us_mn.bill.kind import classify as classify_us_mn
from .jurisdictions.us_mn.bill.citations import extract as extract_us_mn
from .jurisdictions.us_or.bill.scrape import OregonScraper
from .jurisdictions.us_or.bill.status import PATTERNS as OR_PATTERNS
from .jurisdictions.us_or.bill.kind import classify as classify_us_or
from .jurisdictions.us_or.bill.citations import extract as extract_us_or
from .jurisdictions.us_oh.bill.scrape import OhioScraper
from .jurisdictions.us_oh.bill.status import PATTERNS as OH_PATTERNS
from .jurisdictions.us_oh.bill.kind import classify as classify_us_oh
from .jurisdictions.us_oh.bill.citations import extract as extract_us_oh
from .jurisdictions.us_sd.bill.scrape import SouthDakotaScraper
from .jurisdictions.us_sd.bill.status import PATTERNS as SD_PATTERNS
from .jurisdictions.us_sd.bill.kind import classify as classify_us_sd
from .jurisdictions.us_sd.bill.citations import extract as extract_us_sd
from .jurisdictions.us_ut.bill.scrape import UtahScraper
from .jurisdictions.us_ut.bill.status import PATTERNS as UT_PATTERNS
from .jurisdictions.us_ut.bill.kind import classify as classify_us_ut
from .jurisdictions.us_ut.bill.citations import extract as extract_us_ut
from .jurisdictions.us_wi.bill.scrape import WisconsinScraper
from .jurisdictions.us_wi.bill.status import PATTERNS as WI_PATTERNS
from .jurisdictions.us_wi.bill.kind import classify as classify_us_wi
from .jurisdictions.us_wi.bill.citations import extract as extract_us_wi

REGISTRY: dict[str, type[BillScraper]] = {
    "us":    FederalScraper,
    "us-ny": NewYorkScraper,
    "us-co": ColoradoScraper,
    "us-de": DelawareScraper,
    "us-fl": FloridaScraper,
    "us-md": MarylandScraper,
    "us-ks": KansasScraper,
    "us-mn": MinnesotaScraper,
    "us-oh": OhioScraper,
    "us-or": OregonScraper,
    "us-sd": SouthDakotaScraper,
    "us-ut": UtahScraper,
    "us-wi": WisconsinScraper,
}

# Patterns per jurisdiction, used by the `reclassify` command to re-walk
# existing bill_actions in-place when we tune the status vocabulary.
PATTERNS_BY_JURISDICTION = {
    "us":    FEDERAL_PATTERNS,
    "us-ny": NY_PATTERNS,
    "us-co": CO_PATTERNS,
    "us-de": DE_PATTERNS,
    "us-fl": FL_PATTERNS,
    "us-md": MD_PATTERNS,
    "us-ks": KS_PATTERNS,
    "us-mn": MN_PATTERNS,
    "us-oh": OH_PATTERNS,
    "us-or": OR_PATTERNS,
    "us-sd": SD_PATTERNS,
    "us-ut": UT_PATTERNS,
    "us-wi": WI_PATTERNS,
}

# Title-to-kind classifiers, used by `reclassify-kinds`.
KIND_CLASSIFIERS = {
    "us":    classify_us,
    "us-ny": classify_us_ny,
    "us-co": classify_us_co,
    "us-de": classify_us_de,
    "us-fl": classify_us_fl,
    "us-md": classify_us_md,
    "us-ks": classify_us_ks,
    "us-mn": classify_us_mn,
    "us-oh": classify_us_oh,
    "us-or": classify_us_or,
    "us-sd": classify_us_sd,
    "us-ut": classify_us_ut,
    "us-wi": classify_us_wi,
}

# Citation extractors, used by `extract-citations`.
CITATION_EXTRACTORS = {
    "us":    extract_us,
    "us-ny": extract_us_ny,
    "us-co": extract_us_co,
    "us-de": extract_us_de,
    "us-fl": extract_us_fl,
    "us-md": extract_us_md,
    "us-ks": extract_us_ks,
    "us-mn": extract_us_mn,
    "us-oh": extract_us_oh,
    "us-or": extract_us_or,
    "us-sd": extract_us_sd,
    "us-ut": extract_us_ut,
    "us-wi": extract_us_wi,
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
@click.option("--congress", type=int, default=None,
              help="Federal-only: target a specific Congress number "
                   "(118 = 2023-2024). Defaults to current.")
@click.option("--bill", multiple=True,
              help="Federal-only: scrape specific bills by id like "
                   "'hr/7024' (repeatable). When set, skips the "
                   "recent-updates listing.")
@click.option("--dry-run", is_flag=True,
              help="Scrape but do not write to Postgres.")
def scrape(jurisdiction: str, limit: int | None, congress: int | None,
           bill: tuple[str, ...], dry_run: bool) -> None:
    """Run a scraper end-to-end."""
    cls = REGISTRY[jurisdiction]
    kwargs: dict = {"limit": limit}
    if congress is not None and jurisdiction == "us":
        kwargs["congress"] = congress
    if bill and jurisdiction == "us":
        kwargs["bill_ids"] = list(bill)
    if jurisdiction == "us" and not bill:
        # Routine refresh: cap the pagination using the last successful
        # scrape as a since-cursor. A targeted --bill run skips this so
        # backfills aren't accidentally clipped.
        since = last_successful_scrape(jurisdiction)
        if since is not None:
            kwargs["since"] = since
            click.echo(f"Refresh since {since.isoformat()} (set --bill to bypass).")
    scraper = cls(**kwargs)

    if dry_run:
        bills = list(scraper.bills_iter()) if hasattr(scraper, "bills_iter") \
                else scraper.scrape().bills
        scraper.close()
        click.echo(f"Dry run: {len(bills)} bills (not writing).")
        return

    try:
        # Federal scraper streams bills one at a time and we commit per
        # bill so a network blip can't lose 6500-bill of work. Other
        # jurisdictions still use the bulk path.
        if hasattr(scraper, "bills_iter") and hasattr(scraper, "session"):
            counts = write_streaming(
                jurisdiction, scraper.session(), scraper.bills_iter()
            )
        else:
            result = scraper.scrape()
            counts = write(result)
    finally:
        scraper.close()

    click.echo(
        f"Wrote: bills_seen={counts['bills_seen']} "
        f"bills_new={counts['bills_new']} actions_new={counts['actions_new']}"
    )


@main.command()
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Re-walk existing actions for this jurisdiction.",
)
def reclassify(jurisdiction: str) -> None:
    """Re-run the status patterns against actions already in the DB.

    Use this after tuning patterns in jurisdictions/<code>/bill/status.py
    so existing rows pick up the new classifications without a full
    re-scrape. Updates bill_actions.normalized_status in place, then
    rolls up bills.current_status.
    """
    patterns = PATTERNS_BY_JURISDICTION[jurisdiction]
    reclassified = 0
    bills_touched = 0
    with connect(DEFAULT_DB) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.bill_id, a.action_text, a.normalized_status
            FROM bill_actions a
            JOIN bills b ON b.id = a.bill_id
            WHERE b.jurisdiction = ?
            """,
            (jurisdiction,),
        ).fetchall()

        affected_bill_ids: set[str] = set()
        for row in rows:
            status = match_first(row["action_text"], patterns)
            new_value = status.value if status else None
            if new_value != row["normalized_status"]:
                conn.execute(
                    "UPDATE bill_actions SET normalized_status = ? WHERE id = ?",
                    (new_value, row["id"]),
                )
                reclassified += 1
                affected_bill_ids.add(row["bill_id"])

        # Roll up current_status for every affected bill.
        for bill_id in affected_bill_ids:
            actions = conn.execute(
                """
                SELECT normalized_status, occurred_at
                FROM bill_actions
                WHERE bill_id = ? AND normalized_status IS NOT NULL
                """,
                (bill_id,),
            ).fetchall()
            if not actions:
                conn.execute(
                    "UPDATE bills SET current_status = 'unknown', current_status_at = NULL WHERE id = ?",
                    (bill_id,),
                )
                bills_touched += 1
                continue
            best_rank = -1
            best: tuple[str, str] | None = None
            for a in actions:
                status_enum = NormalizedStatus(a["normalized_status"])
                rank = STATUS_ORDER[status_enum]
                if rank > best_rank:
                    best_rank = rank
                    best = (status_enum.value, a["occurred_at"])
            if best is not None:
                conn.execute(
                    "UPDATE bills SET current_status = ?, current_status_at = ? WHERE id = ?",
                    (best[0], best[1], bill_id),
                )
                bills_touched += 1

    click.echo(
        f"Reclassified {reclassified} actions across {bills_touched} bills "
        f"in {jurisdiction}."
    )


@main.command(name="fetch-texts")
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Download bill text for bills in this jurisdiction.",
)
@click.option("--limit", "-n", type=int, default=None,
              help="Stop after N bills fetched.")
def fetch_texts(jurisdiction: str, limit: int | None) -> None:
    """Download bill text from bill_versions URLs into bill_texts.

    Prefers HTML > XML > TXT formats. PDFs are skipped in the prototype.
    Re-running is idempotent — already-stored rows are only rewritten
    when the SHA changes.
    """
    from ._common.text_fetcher import fetch_for_jurisdiction
    counts = fetch_for_jurisdiction(jurisdiction, limit=limit)
    click.echo(
        f"Bills seen: {counts['bills_seen']}  "
        f"versions: {counts['versions_seen']}  "
        f"fetched: {counts['fetched']}  "
        f"skipped: {counts['skipped']}"
    )


@main.command(name="precompute-diffs")
@click.option("--jurisdiction", "-j", default=None,
              help="Limit to one jurisdiction code (e.g. 'us').")
def precompute_diffs(jurisdiction: str | None) -> None:
    """Compute the diff JSON payload for every bill and store on the
    bill row. The frontend reads this directly — no API at runtime."""
    from ._common.diff_precompute import precompute_all
    counts = precompute_all(jurisdiction=jurisdiction)
    click.echo(
        f"  bills processed: {counts['bills']}\n"
        f"  with sections:   {counts['with_sections']}\n"
        f"  with applied ops:{counts['with_ops']}"
    )


@main.command(name="propose-llm-variants")
@click.option("--jurisdiction", "-j", default=None)
@click.option("--limit", "-n", type=int, default=None,
              help="Stop after N successful proposals.")
@click.option("--dry-run", is_flag=True,
              help="Call the LLM but don't write proposals to the DB.")
def propose_llm_variants(jurisdiction: str | None, limit: int | None,
                         dry_run: bool) -> None:
    """LLM-assisted Tier 3: draft patched YAML for structural variants.

    Walks every variant where tier is 'list' or 'structural' and
    patched_yaml is null, calls Claude with the baseline YAML + bill's
    amendment text, validates the response, and stores it as the
    proposed re-encoding. Requires ANTHROPIC_API_KEY in env.
    """
    from ._common.variants_llm import propose_all
    counts = propose_all(jurisdiction=jurisdiction, limit=limit, dry_run=dry_run)
    for k, v in sorted(counts.items()):
        click.echo(f"  {k:<12} {v}")


@main.command(name="precompute-variants")
@click.option("--jurisdiction", "-j", default=None)
def precompute_variants(jurisdiction: str | None) -> None:
    """Compute rule_variants for every bill whose ops touch an encoding."""
    from ._common.variants import compute_all
    totals = compute_all(jurisdiction=jurisdiction)
    for k, v in sorted(totals.items()):
        click.echo(f"  {k:<14} {v}")


@main.command(name="sync-supabase")
def sync_supabase() -> None:
    """Push local SQLite → Supabase Postgres (bills schema).

    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY env vars. The service-
    role key is the *only* credential allowed to write into the bills
    schema; the frontend uses the anon key for reads.
    """
    from ._common.supabase_sync import sync
    from ._common.db import DEFAULT_DB
    counts = sync(DEFAULT_DB)
    for table, n in counts.items():
        click.echo(f"  {table:<22} {n}")


@main.command(name="fetch-corpus")
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Fetch corpus provisions for bills in this jurisdiction.",
)
def fetch_corpus(jurisdiction: str) -> None:
    """Pull axiom-corpus text for every citation extracted from bills.

    Idempotent and incremental: skips citations whose corpus provision is
    already cached locally. Use --force inside the Python module to bust
    the cache when corpus releases a new version.
    """
    from ._common.corpus_client import fetch
    bills = []
    with connect(DEFAULT_DB) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT c.citation
              FROM bill_citations c
              JOIN bills b ON b.id = c.bill_id
             WHERE b.jurisdiction = ?
            """,
            (jurisdiction,),
        ).fetchall()
        bills = [row["citation"] for row in rows]
    found = 0
    missing = 0
    for citation in bills:
        prov = fetch(citation)
        if prov is not None:
            found += 1
        else:
            missing += 1
    click.echo(
        f"Citations: {len(bills)}  cached/fetched: {found}  not-in-corpus: {missing}"
    )


@main.command(name="extract-citations")
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Extract citations from existing bills in this jurisdiction.",
)
def extract_citations(jurisdiction: str) -> None:
    """Run the citation extractor over existing bills + bill_texts.

    Idempotent: replaces all citations for each bill before writing the
    new pass. Re-run after tuning the per-jurisdiction patterns or after
    `fetch-texts` brings in more full-text material.
    """
    from ._common.citation_writer import extract_for_jurisdiction
    counts = extract_for_jurisdiction(
        jurisdiction, CITATION_EXTRACTORS[jurisdiction]
    )
    click.echo(
        f"Bills: {counts['bills']}  "
        f"summary-hits: {counts['summary_hits']}  "
        f"text-hits: {counts['text_hits']}  "
        f"rows: {counts['rows_written']}"
    )


@main.command(name="index-encodings")
@click.option("--repo", required=True, type=click.Path(exists=True, file_okay=False),
              help="Path to a local rulespec-* clone (e.g. ~/rulespec-us).")
@click.option("--jurisdiction", "-j", default="us", show_default=True,
              help="Jurisdiction these encodings belong to.")
@click.option("--repo-name", default=None,
              help="Repo identifier stored in axiom_encodings.repo. "
                   "Defaults to the directory name of --repo.")
def index_encodings(repo: str, jurisdiction: str, repo_name: str | None) -> None:
    """Walk a rulespec-* repo and index its YAML inventory."""
    from pathlib import Path
    from ._common.encodings import index_repo
    repo_path = Path(repo).resolve()
    name = repo_name or repo_path.name
    counts = index_repo(repo_path, jurisdiction=jurisdiction, repo_name=name)
    click.echo(
        f"Indexed {name}: scanned={counts['scanned']} "
        f"indexed={counts['indexed']} skipped={counts['skipped']}"
    )


@main.command(name="reclassify-kinds")
@click.option(
    "--jurisdiction", "-j", required=True,
    type=click.Choice(list(REGISTRY)),
    help="Re-classify bill kinds for this jurisdiction.",
)
def reclassify_kinds(jurisdiction: str) -> None:
    """Re-run the kind classifier against existing bills.

    Use after tuning jurisdictions/<code>/bill/kind.py. Updates
    bills.kind in place; no re-scrape required.
    """
    classify = KIND_CLASSIFIERS[jurisdiction]
    changed = 0
    with connect(DEFAULT_DB) as conn:
        rows = conn.execute(
            "SELECT id, title, kind FROM bills WHERE jurisdiction = ?",
            (jurisdiction,),
        ).fetchall()
        for row in rows:
            new_kind = classify(row["title"]).value
            if new_kind != row["kind"]:
                conn.execute(
                    "UPDATE bills SET kind = ? WHERE id = ?",
                    (new_kind, row["id"]),
                )
                changed += 1
    click.echo(f"Reclassified {changed} bills in {jurisdiction}.")


if __name__ == "__main__":
    main()
