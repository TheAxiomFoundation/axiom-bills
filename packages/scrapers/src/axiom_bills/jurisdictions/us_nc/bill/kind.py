"""North Carolina bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"appropriat(?:e|ion|ing)|budget", BillKind.APPROPRIATIONS),
    (r"honor(?:ing)?|commemorat(?:e|ing)|congratulat(?:e|ing)|recogniz(?:e|ing)", BillKind.CEREMONIAL),
    (r"temporary rules|joint rules|adjourn|recess", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
