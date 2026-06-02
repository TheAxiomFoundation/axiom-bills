"""Delaware bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"bond and capital improvements act", BillKind.APPROPRIATIONS),
    (r"grants-in-aid", BillKind.APPROPRIATIONS),
    (r"appropriat", BillKind.APPROPRIATIONS),
    (r"^recognizing\b", BillKind.CEREMONIAL),
    (r"^commending\b", BillKind.CEREMONIAL),
    (r"^designating\b", BillKind.CEREMONIAL),
    (r"^proclaiming\b", BillKind.CEREMONIAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
