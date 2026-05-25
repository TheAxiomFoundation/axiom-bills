"""CO bill kind classifier (initial cut).

Colorado General Assembly uses tributes/joint resolutions for the
ceremonial bucket; appropriations are clearly titled. Filled in as the
CO scraper itself matures.
"""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind


TITLE_PATTERNS = compile_kind_patterns([
    (r"^concerning .* appropriations", BillKind.APPROPRIATIONS),
    (r"^a tribute to", BillKind.CEREMONIAL),
    (r"^memorializing ", BillKind.CEREMONIAL),
    (r"^honoring ", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
