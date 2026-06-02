"""UT bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"base budget|appropriations?", BillKind.APPROPRIATIONS),
    (r"joint resolution.*rules", BillKind.PROCEDURAL),
    (r"honoring|recognizing|commemorating|congratulating", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
