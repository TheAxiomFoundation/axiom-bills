"""OR bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"^in memoriam:", BillKind.CEREMONIAL),
    (r"^(commends|congratulates|honors|recognizes|celebrates)\b", BillKind.CEREMONIAL),
    (r"appropriat(es|ing) moneys?", BillKind.APPROPRIATIONS),
    (r"declares an emergency", BillKind.SUBSTANTIVE),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
