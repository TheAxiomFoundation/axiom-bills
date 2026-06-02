from __future__ import annotations

from axiom_bills._common.models import BillKind, Chamber, NormalizedStatus
from axiom_bills.jurisdictions.us_nc.bill.citations import extract
from axiom_bills.jurisdictions.us_nc.bill.scrape import (
    parse_bill,
    parse_bill_feed,
    parse_history_feed,
    session_for_year,
)


BILL_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
<guid isPermaLink="true">https://www.ncleg.gov/BillLookup/2025/H1</guid>
<link>https://www.ncleg.gov/BillLookup/2025/H1</link>
<title>HR 1 - House Temporary Rules.</title>
<description>Last action: Adopted (House action)</description>
<pubDate>Wed, 08 Jan 2025 00:00:00 EST</pubDate>
</item>
<item>
<guid isPermaLink="true">https://www.ncleg.gov/BillLookup/2025/H2</guid>
<link>https://www.ncleg.gov/BillLookup/2025/H2</link>
<title>HB 2 - Entry Fees for Interscholastic Sports Events.</title>
<description>Last action: Ref To Com On Rules and Operations of the Senate (Senate action)</description>
<pubDate>Thu, 06 Mar 2025 00:00:00 EST</pubDate>
</item>
</channel></rss>
"""

HISTORY_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item><title>House Chamber: Filed</title><pubDate>Wed, 08 Jan 2025 00:00:00 EST</pubDate></item>
<item><title>House Chamber: Passed 1st Reading</title><pubDate>Wed, 08 Jan 2025 00:00:00 EST</pubDate></item>
<item><title>House Chamber: Added to Calendar</title><pubDate>Wed, 08 Jan 2025 00:00:00 EST</pubDate></item>
<item><title>House Chamber: Adopted</title><pubDate>Wed, 08 Jan 2025 00:00:00 EST</pubDate></item>
</channel></rss>
"""


def test_parse_bill_feed() -> None:
    item = parse_bill_feed(BILL_FEED)[0]

    assert item.number == "HB 2"
    assert item.compact_number == "H2"
    assert item.title == "Entry Fees for Interscholastic Sports Events"
    assert item.last_action.startswith("Ref To Com")


def test_parse_history_feed() -> None:
    item = parse_bill_feed(BILL_FEED)[1]
    actions = parse_history_feed(HISTORY_FEED, fallback=item)

    assert actions[0].normalized_status == NormalizedStatus.INTRODUCED
    assert actions[2].normalized_status == NormalizedStatus.IN_COMMITTEE
    assert actions[-1].normalized_status == NormalizedStatus.PASSED_CHAMBER
    assert actions[-1].chamber == Chamber.LOWER


def test_parse_bill_builds_core_fields() -> None:
    item = parse_bill_feed(BILL_FEED)[0]
    bill = parse_bill(item, parse_history_feed(HISTORY_FEED, fallback=item), session=session_for_year(2025), session_year=2025)

    assert bill.jurisdiction == "us-nc"
    assert bill.number == "HB 2"
    assert bill.chamber == Chamber.LOWER
    assert bill.kind == BillKind.SUBSTANTIVE
    assert bill.versions[0].source_url == "https://www.ncleg.gov/Sessions/2025/Bills/House/PDF/H2v1.pdf"


def test_extracts_north_carolina_citations() -> None:
    assert extract("Amend G.S. 20-37.6 and N.C. Gen. Stat. § 14-415.11.") == [
        ("G.S. 20-37.6", "N.C. Gen. Stat. § 20-37.6"),
        ("N.C. Gen. Stat. § 14-415.11", "N.C. Gen. Stat. § 14-415.11"),
    ]
