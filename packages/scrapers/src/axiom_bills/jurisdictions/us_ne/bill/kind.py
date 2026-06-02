"""Nebraska bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"appropriation|appropriations|budget", BillKind.APPROPRIATIONS),
    (r"congratulat(?:e|ing)|honor(?:ing)?|commemorat(?:e|ing)|recogniz(?:e|ing)|memorial", BillKind.CEREMONIAL),
    (r"rules of the legislature|adjourn", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
