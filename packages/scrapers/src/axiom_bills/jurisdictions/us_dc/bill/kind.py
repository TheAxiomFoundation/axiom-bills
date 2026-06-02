"""District of Columbia bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bbudget|appropriation|fiscal year|capital improvements?|fund(?:ing)?\b", BillKind.APPROPRIATIONS),
    (r"\bceremonial|recognition|honor(?:ing)?|commemorat(?:e|ing)|congratul(?:ate|ating)\b", BillKind.CEREMONIAL),
    (r"\brules of organization|council rules|committee assignment\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
