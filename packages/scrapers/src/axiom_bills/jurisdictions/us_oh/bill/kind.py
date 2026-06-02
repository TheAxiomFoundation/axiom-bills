"""OH bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"make appropriations", BillKind.APPROPRIATIONS),
    (r"capital appropriations", BillKind.APPROPRIATIONS),
    (r"honor|honoring|congratulat|commemorat|recogniz", BillKind.CEREMONIAL),
    (r"name .* memorial", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
