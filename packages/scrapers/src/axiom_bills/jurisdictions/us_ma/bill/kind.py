"""Massachusetts bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"appropriat(?:e|ion|ing)|supplemental budget", BillKind.APPROPRIATIONS),
    (r"commemorat(?:e|ing)|congratulat(?:e|ing)|honor(?:ing)?|recogniz(?:e|ing)", BillKind.CEREMONIAL),
    (r"study order|joint rules|rules of the", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
