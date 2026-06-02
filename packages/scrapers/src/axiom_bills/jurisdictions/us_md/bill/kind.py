"""Maryland bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"budget bill|capital budget|operating budget", BillKind.APPROPRIATIONS),
    (r"bond initiative", BillKind.APPROPRIATIONS),
    (r"^celebrating\b|^commemorating\b|^congratulating\b", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
