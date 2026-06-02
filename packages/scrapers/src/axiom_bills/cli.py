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
from .jurisdictions.us_al.bill.scrape import AlabamaScraper
from .jurisdictions.us_al.bill.status import PATTERNS as AL_PATTERNS
from .jurisdictions.us_al.bill.kind import classify as classify_us_al
from .jurisdictions.us_al.bill.citations import extract as extract_us_al
from .jurisdictions.us_ak.bill.scrape import AlaskaScraper
from .jurisdictions.us_ak.bill.status import PATTERNS as AK_PATTERNS
from .jurisdictions.us_ak.bill.kind import classify as classify_us_ak
from .jurisdictions.us_ak.bill.citations import extract as extract_us_ak
from .jurisdictions.us_ar.bill.scrape import ArkansasScraper
from .jurisdictions.us_ar.bill.status import PATTERNS as AR_PATTERNS
from .jurisdictions.us_ar.bill.kind import classify as classify_us_ar
from .jurisdictions.us_ar.bill.citations import extract as extract_us_ar
from .jurisdictions.us_az.bill.scrape import ArizonaScraper
from .jurisdictions.us_az.bill.status import PATTERNS as AZ_PATTERNS
from .jurisdictions.us_az.bill.kind import classify as classify_us_az
from .jurisdictions.us_az.bill.citations import extract as extract_us_az
from .jurisdictions.us_ca.bill.scrape import CaliforniaScraper
from .jurisdictions.us_ca.bill.status import PATTERNS as CA_PATTERNS
from .jurisdictions.us_ca.bill.kind import classify as classify_us_ca
from .jurisdictions.us_ca.bill.citations import extract as extract_us_ca
from .jurisdictions.us_ct.bill.scrape import ConnecticutScraper
from .jurisdictions.us_ct.bill.status import PATTERNS as CT_PATTERNS
from .jurisdictions.us_ct.bill.kind import classify as classify_us_ct
from .jurisdictions.us_ct.bill.citations import extract as extract_us_ct
from .jurisdictions.us_dc.bill.scrape import DistrictOfColumbiaScraper
from .jurisdictions.us_dc.bill.status import PATTERNS as DC_PATTERNS
from .jurisdictions.us_dc.bill.kind import classify as classify_us_dc
from .jurisdictions.us_dc.bill.citations import extract as extract_us_dc
from .jurisdictions.us_ga.bill.scrape import GeorgiaScraper
from .jurisdictions.us_ga.bill.status import PATTERNS as GA_PATTERNS
from .jurisdictions.us_ga.bill.kind import classify as classify_us_ga
from .jurisdictions.us_ga.bill.citations import extract as extract_us_ga
from .jurisdictions.us_hi.bill.scrape import HawaiiScraper
from .jurisdictions.us_hi.bill.status import PATTERNS as HI_PATTERNS
from .jurisdictions.us_hi.bill.kind import classify as classify_us_hi
from .jurisdictions.us_hi.bill.citations import extract as extract_us_hi
from .jurisdictions.us_ia.bill.scrape import IowaScraper
from .jurisdictions.us_ia.bill.status import PATTERNS as IA_PATTERNS
from .jurisdictions.us_ia.bill.kind import classify as classify_us_ia
from .jurisdictions.us_ia.bill.citations import extract as extract_us_ia
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
from .jurisdictions.us_id.bill.scrape import IdahoScraper
from .jurisdictions.us_id.bill.status import PATTERNS as ID_PATTERNS
from .jurisdictions.us_id.bill.kind import classify as classify_us_id
from .jurisdictions.us_id.bill.citations import extract as extract_us_id
from .jurisdictions.us_il.bill.scrape import IllinoisScraper
from .jurisdictions.us_il.bill.status import PATTERNS as IL_PATTERNS
from .jurisdictions.us_il.bill.kind import classify as classify_us_il
from .jurisdictions.us_il.bill.citations import extract as extract_us_il
from .jurisdictions.us_md.bill.scrape import MarylandScraper
from .jurisdictions.us_md.bill.status import PATTERNS as MD_PATTERNS
from .jurisdictions.us_md.bill.kind import classify as classify_us_md
from .jurisdictions.us_md.bill.citations import extract as extract_us_md
from .jurisdictions.us_ks.bill.scrape import KansasScraper
from .jurisdictions.us_ks.bill.status import PATTERNS as KS_PATTERNS
from .jurisdictions.us_ks.bill.kind import classify as classify_us_ks
from .jurisdictions.us_ks.bill.citations import extract as extract_us_ks
from .jurisdictions.us_ky.bill.scrape import KentuckyScraper
from .jurisdictions.us_ky.bill.status import PATTERNS as KY_PATTERNS
from .jurisdictions.us_ky.bill.kind import classify as classify_us_ky
from .jurisdictions.us_ky.bill.citations import extract as extract_us_ky
from .jurisdictions.us_la.bill.scrape import LouisianaScraper
from .jurisdictions.us_la.bill.status import PATTERNS as LA_PATTERNS
from .jurisdictions.us_la.bill.kind import classify as classify_us_la
from .jurisdictions.us_la.bill.citations import extract as extract_us_la
from .jurisdictions.us_me.bill.scrape import MaineScraper
from .jurisdictions.us_me.bill.status import PATTERNS as ME_PATTERNS
from .jurisdictions.us_me.bill.kind import classify as classify_us_me
from .jurisdictions.us_me.bill.citations import extract as extract_us_me
from .jurisdictions.us_ma.bill.scrape import MassachusettsScraper
from .jurisdictions.us_ma.bill.status import PATTERNS as MA_PATTERNS
from .jurisdictions.us_ma.bill.kind import classify as classify_us_ma
from .jurisdictions.us_ma.bill.citations import extract as extract_us_ma
from .jurisdictions.us_mi.bill.scrape import MichiganScraper
from .jurisdictions.us_mi.bill.status import PATTERNS as MI_PATTERNS
from .jurisdictions.us_mi.bill.kind import classify as classify_us_mi
from .jurisdictions.us_mi.bill.citations import extract as extract_us_mi
from .jurisdictions.us_mn.bill.scrape import MinnesotaScraper
from .jurisdictions.us_mn.bill.status import PATTERNS as MN_PATTERNS
from .jurisdictions.us_mn.bill.kind import classify as classify_us_mn
from .jurisdictions.us_mn.bill.citations import extract as extract_us_mn
from .jurisdictions.us_mo.bill.scrape import MissouriScraper
from .jurisdictions.us_mo.bill.status import PATTERNS as MO_PATTERNS
from .jurisdictions.us_mo.bill.kind import classify as classify_us_mo
from .jurisdictions.us_mo.bill.citations import extract as extract_us_mo
from .jurisdictions.us_ms.bill.scrape import MississippiScraper
from .jurisdictions.us_ms.bill.status import PATTERNS as MS_PATTERNS
from .jurisdictions.us_ms.bill.kind import classify as classify_us_ms
from .jurisdictions.us_ms.bill.citations import extract as extract_us_ms
from .jurisdictions.us_mt.bill.scrape import MontanaScraper
from .jurisdictions.us_mt.bill.status import PATTERNS as MT_PATTERNS
from .jurisdictions.us_mt.bill.kind import classify as classify_us_mt
from .jurisdictions.us_mt.bill.citations import extract as extract_us_mt
from .jurisdictions.us_nh.bill.scrape import NewHampshireScraper
from .jurisdictions.us_nh.bill.status import PATTERNS as NH_PATTERNS
from .jurisdictions.us_nh.bill.kind import classify as classify_us_nh
from .jurisdictions.us_nh.bill.citations import extract as extract_us_nh
from .jurisdictions.us_nj.bill.scrape import NewJerseyScraper
from .jurisdictions.us_nj.bill.status import PATTERNS as NJ_PATTERNS
from .jurisdictions.us_nj.bill.kind import classify as classify_us_nj
from .jurisdictions.us_nj.bill.citations import extract as extract_us_nj
from .jurisdictions.us_nm.bill.scrape import NewMexicoScraper
from .jurisdictions.us_nm.bill.status import PATTERNS as NM_PATTERNS
from .jurisdictions.us_nm.bill.kind import classify as classify_us_nm
from .jurisdictions.us_nm.bill.citations import extract as extract_us_nm
from .jurisdictions.us_nv.bill.scrape import NevadaScraper
from .jurisdictions.us_nv.bill.status import PATTERNS as NV_PATTERNS
from .jurisdictions.us_nv.bill.kind import classify as classify_us_nv
from .jurisdictions.us_nv.bill.citations import extract as extract_us_nv
from .jurisdictions.us_ok.bill.scrape import OklahomaScraper
from .jurisdictions.us_ok.bill.status import PATTERNS as OK_PATTERNS
from .jurisdictions.us_ok.bill.kind import classify as classify_us_ok
from .jurisdictions.us_ok.bill.citations import extract as extract_us_ok
from .jurisdictions.us_pa.bill.scrape import PennsylvaniaScraper
from .jurisdictions.us_pa.bill.status import PATTERNS as PA_PATTERNS
from .jurisdictions.us_pa.bill.kind import classify as classify_us_pa
from .jurisdictions.us_pa.bill.citations import extract as extract_us_pa
from .jurisdictions.us_nc.bill.scrape import NorthCarolinaScraper
from .jurisdictions.us_nc.bill.status import PATTERNS as NC_PATTERNS
from .jurisdictions.us_nc.bill.kind import classify as classify_us_nc
from .jurisdictions.us_nc.bill.citations import extract as extract_us_nc
from .jurisdictions.us_ne.bill.scrape import NebraskaScraper
from .jurisdictions.us_ne.bill.status import PATTERNS as NE_PATTERNS
from .jurisdictions.us_ne.bill.kind import classify as classify_us_ne
from .jurisdictions.us_ne.bill.citations import extract as extract_us_ne
from .jurisdictions.us_nd.bill.scrape import NorthDakotaScraper
from .jurisdictions.us_nd.bill.status import PATTERNS as ND_PATTERNS
from .jurisdictions.us_nd.bill.kind import classify as classify_us_nd
from .jurisdictions.us_nd.bill.citations import extract as extract_us_nd
from .jurisdictions.us_or.bill.scrape import OregonScraper
from .jurisdictions.us_or.bill.status import PATTERNS as OR_PATTERNS
from .jurisdictions.us_or.bill.kind import classify as classify_us_or
from .jurisdictions.us_or.bill.citations import extract as extract_us_or
from .jurisdictions.us_oh.bill.scrape import OhioScraper
from .jurisdictions.us_oh.bill.status import PATTERNS as OH_PATTERNS
from .jurisdictions.us_oh.bill.kind import classify as classify_us_oh
from .jurisdictions.us_oh.bill.citations import extract as extract_us_oh
from .jurisdictions.us_ri.bill.scrape import RhodeIslandScraper
from .jurisdictions.us_ri.bill.status import PATTERNS as RI_PATTERNS
from .jurisdictions.us_ri.bill.kind import classify as classify_us_ri
from .jurisdictions.us_ri.bill.citations import extract as extract_us_ri
from .jurisdictions.us_sc.bill.scrape import SouthCarolinaScraper
from .jurisdictions.us_sc.bill.status import PATTERNS as SC_PATTERNS
from .jurisdictions.us_sc.bill.kind import classify as classify_us_sc
from .jurisdictions.us_sc.bill.citations import extract as extract_us_sc
from .jurisdictions.us_sd.bill.scrape import SouthDakotaScraper
from .jurisdictions.us_sd.bill.status import PATTERNS as SD_PATTERNS
from .jurisdictions.us_sd.bill.kind import classify as classify_us_sd
from .jurisdictions.us_sd.bill.citations import extract as extract_us_sd
from .jurisdictions.us_tn.bill.scrape import TennesseeScraper
from .jurisdictions.us_tn.bill.status import PATTERNS as TN_PATTERNS
from .jurisdictions.us_tn.bill.kind import classify as classify_us_tn
from .jurisdictions.us_tn.bill.citations import extract as extract_us_tn
from .jurisdictions.us_tx.bill.scrape import TexasScraper
from .jurisdictions.us_tx.bill.status import PATTERNS as TX_PATTERNS
from .jurisdictions.us_tx.bill.kind import classify as classify_us_tx
from .jurisdictions.us_tx.bill.citations import extract as extract_us_tx
from .jurisdictions.us_ut.bill.scrape import UtahScraper
from .jurisdictions.us_ut.bill.status import PATTERNS as UT_PATTERNS
from .jurisdictions.us_ut.bill.kind import classify as classify_us_ut
from .jurisdictions.us_ut.bill.citations import extract as extract_us_ut
from .jurisdictions.us_wi.bill.scrape import WisconsinScraper
from .jurisdictions.us_wi.bill.status import PATTERNS as WI_PATTERNS
from .jurisdictions.us_wi.bill.kind import classify as classify_us_wi
from .jurisdictions.us_wi.bill.citations import extract as extract_us_wi
from .jurisdictions.us_wy.bill.scrape import WyomingScraper
from .jurisdictions.us_wy.bill.status import PATTERNS as WY_PATTERNS
from .jurisdictions.us_wy.bill.kind import classify as classify_us_wy
from .jurisdictions.us_wy.bill.citations import extract as extract_us_wy

REGISTRY: dict[str, type[BillScraper]] = {
    "us":    FederalScraper,
    "us-al": AlabamaScraper,
    "us-ak": AlaskaScraper,
    "us-ar": ArkansasScraper,
    "us-az": ArizonaScraper,
    "us-ca": CaliforniaScraper,
    "us-ct": ConnecticutScraper,
    "us-dc": DistrictOfColumbiaScraper,
    "us-ga": GeorgiaScraper,
    "us-hi": HawaiiScraper,
    "us-ia": IowaScraper,
    "us-ny": NewYorkScraper,
    "us-co": ColoradoScraper,
    "us-de": DelawareScraper,
    "us-fl": FloridaScraper,
    "us-id": IdahoScraper,
    "us-il": IllinoisScraper,
    "us-md": MarylandScraper,
    "us-ks": KansasScraper,
    "us-ky": KentuckyScraper,
    "us-la": LouisianaScraper,
    "us-me": MaineScraper,
    "us-ma": MassachusettsScraper,
    "us-mi": MichiganScraper,
    "us-mn": MinnesotaScraper,
    "us-mo": MissouriScraper,
    "us-ms": MississippiScraper,
    "us-mt": MontanaScraper,
    "us-nh": NewHampshireScraper,
    "us-nj": NewJerseyScraper,
    "us-nm": NewMexicoScraper,
    "us-nv": NevadaScraper,
    "us-ok": OklahomaScraper,
    "us-pa": PennsylvaniaScraper,
    "us-nc": NorthCarolinaScraper,
    "us-ne": NebraskaScraper,
    "us-nd": NorthDakotaScraper,
    "us-oh": OhioScraper,
    "us-or": OregonScraper,
    "us-ri": RhodeIslandScraper,
    "us-sc": SouthCarolinaScraper,
    "us-sd": SouthDakotaScraper,
    "us-tn": TennesseeScraper,
    "us-tx": TexasScraper,
    "us-ut": UtahScraper,
    "us-wi": WisconsinScraper,
    "us-wy": WyomingScraper,
}

# Patterns per jurisdiction, used by the `reclassify` command to re-walk
# existing bill_actions in-place when we tune the status vocabulary.
PATTERNS_BY_JURISDICTION = {
    "us":    FEDERAL_PATTERNS,
    "us-al": AL_PATTERNS,
    "us-ak": AK_PATTERNS,
    "us-ar": AR_PATTERNS,
    "us-az": AZ_PATTERNS,
    "us-ca": CA_PATTERNS,
    "us-ct": CT_PATTERNS,
    "us-dc": DC_PATTERNS,
    "us-ga": GA_PATTERNS,
    "us-hi": HI_PATTERNS,
    "us-ia": IA_PATTERNS,
    "us-ny": NY_PATTERNS,
    "us-co": CO_PATTERNS,
    "us-de": DE_PATTERNS,
    "us-fl": FL_PATTERNS,
    "us-id": ID_PATTERNS,
    "us-il": IL_PATTERNS,
    "us-md": MD_PATTERNS,
    "us-ks": KS_PATTERNS,
    "us-ky": KY_PATTERNS,
    "us-la": LA_PATTERNS,
    "us-me": ME_PATTERNS,
    "us-ma": MA_PATTERNS,
    "us-mi": MI_PATTERNS,
    "us-mn": MN_PATTERNS,
    "us-mo": MO_PATTERNS,
    "us-ms": MS_PATTERNS,
    "us-mt": MT_PATTERNS,
    "us-nh": NH_PATTERNS,
    "us-nj": NJ_PATTERNS,
    "us-nm": NM_PATTERNS,
    "us-nv": NV_PATTERNS,
    "us-ok": OK_PATTERNS,
    "us-pa": PA_PATTERNS,
    "us-nc": NC_PATTERNS,
    "us-ne": NE_PATTERNS,
    "us-nd": ND_PATTERNS,
    "us-oh": OH_PATTERNS,
    "us-or": OR_PATTERNS,
    "us-ri": RI_PATTERNS,
    "us-sc": SC_PATTERNS,
    "us-sd": SD_PATTERNS,
    "us-tn": TN_PATTERNS,
    "us-tx": TX_PATTERNS,
    "us-ut": UT_PATTERNS,
    "us-wi": WI_PATTERNS,
    "us-wy": WY_PATTERNS,
}

# Title-to-kind classifiers, used by `reclassify-kinds`.
KIND_CLASSIFIERS = {
    "us":    classify_us,
    "us-al": classify_us_al,
    "us-ak": classify_us_ak,
    "us-ar": classify_us_ar,
    "us-az": classify_us_az,
    "us-ca": classify_us_ca,
    "us-ct": classify_us_ct,
    "us-dc": classify_us_dc,
    "us-ga": classify_us_ga,
    "us-hi": classify_us_hi,
    "us-ia": classify_us_ia,
    "us-ny": classify_us_ny,
    "us-co": classify_us_co,
    "us-de": classify_us_de,
    "us-fl": classify_us_fl,
    "us-id": classify_us_id,
    "us-il": classify_us_il,
    "us-md": classify_us_md,
    "us-ks": classify_us_ks,
    "us-ky": classify_us_ky,
    "us-la": classify_us_la,
    "us-me": classify_us_me,
    "us-ma": classify_us_ma,
    "us-mi": classify_us_mi,
    "us-mn": classify_us_mn,
    "us-mo": classify_us_mo,
    "us-ms": classify_us_ms,
    "us-mt": classify_us_mt,
    "us-nh": classify_us_nh,
    "us-nj": classify_us_nj,
    "us-nm": classify_us_nm,
    "us-nv": classify_us_nv,
    "us-ok": classify_us_ok,
    "us-pa": classify_us_pa,
    "us-nc": classify_us_nc,
    "us-ne": classify_us_ne,
    "us-nd": classify_us_nd,
    "us-oh": classify_us_oh,
    "us-or": classify_us_or,
    "us-ri": classify_us_ri,
    "us-sc": classify_us_sc,
    "us-sd": classify_us_sd,
    "us-tn": classify_us_tn,
    "us-tx": classify_us_tx,
    "us-ut": classify_us_ut,
    "us-wi": classify_us_wi,
    "us-wy": classify_us_wy,
}

# Citation extractors, used by `extract-citations`.
CITATION_EXTRACTORS = {
    "us":    extract_us,
    "us-al": extract_us_al,
    "us-ak": extract_us_ak,
    "us-ar": extract_us_ar,
    "us-az": extract_us_az,
    "us-ca": extract_us_ca,
    "us-ct": extract_us_ct,
    "us-dc": extract_us_dc,
    "us-ga": extract_us_ga,
    "us-hi": extract_us_hi,
    "us-ia": extract_us_ia,
    "us-ny": extract_us_ny,
    "us-co": extract_us_co,
    "us-de": extract_us_de,
    "us-fl": extract_us_fl,
    "us-id": extract_us_id,
    "us-il": extract_us_il,
    "us-md": extract_us_md,
    "us-ks": extract_us_ks,
    "us-ky": extract_us_ky,
    "us-la": extract_us_la,
    "us-me": extract_us_me,
    "us-ma": extract_us_ma,
    "us-mi": extract_us_mi,
    "us-mn": extract_us_mn,
    "us-mo": extract_us_mo,
    "us-ms": extract_us_ms,
    "us-mt": extract_us_mt,
    "us-nh": extract_us_nh,
    "us-nj": extract_us_nj,
    "us-nm": extract_us_nm,
    "us-nv": extract_us_nv,
    "us-ok": extract_us_ok,
    "us-pa": extract_us_pa,
    "us-nc": extract_us_nc,
    "us-ne": extract_us_ne,
    "us-nd": extract_us_nd,
    "us-oh": extract_us_oh,
    "us-or": extract_us_or,
    "us-ri": extract_us_ri,
    "us-sc": extract_us_sc,
    "us-sd": extract_us_sd,
    "us-tn": extract_us_tn,
    "us-tx": extract_us_tx,
    "us-ut": extract_us_ut,
    "us-wi": extract_us_wi,
    "us-wy": extract_us_wy,
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
