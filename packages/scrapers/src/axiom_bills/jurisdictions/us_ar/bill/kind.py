"""Arkansas bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriation|appropriations|fiscal year|general appropriation\b", BillKind.APPROPRIATIONS),
    (r"\bcommend(?:ing)?|congratul(?:ate|ating)|honor(?:ing)?|memoriali[sz](?:e|ing)|recogniz(?:e|ing)\b", BillKind.CEREMONIAL),
    (r"\brules of the house|rules of the senate|joint rules|organizational session\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
