"""KS bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"making and concerning appropriations", BillKind.APPROPRIATIONS),
    (r"providing for the adjournment", BillKind.PROCEDURAL),
    (r"congratulating|honoring|commemorating|recognizing", BillKind.CEREMONIAL),
    (r"designating .* memorial", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
