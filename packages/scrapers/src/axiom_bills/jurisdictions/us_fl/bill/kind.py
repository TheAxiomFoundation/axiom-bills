"""Florida bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"appropriation|appropriations|implementing the .* budget", BillKind.APPROPRIATIONS),
    (r"relief of ", BillKind.CEREMONIAL),
    (r"congratulat(?:e|ing)|honor(?:ing)?|recogniz(?:e|ing)|memorial", BillKind.CEREMONIAL),
    (r"adopting the rules|joint rules|extension of legislative session", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
