"""MN bill kind classifier (initial cut).

Minnesota uses concurrent resolutions for the ceremonial bucket. Filled
in as the MN scraper matures.
"""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind


TITLE_PATTERNS = compile_kind_patterns([
    (r"appropriating money", BillKind.APPROPRIATIONS),
    (r"^a (house|senate) resolution.*recognizing", BillKind.CEREMONIAL),
    (r"^a concurrent resolution .*(commemorating|honoring|congratulating)",
     BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
