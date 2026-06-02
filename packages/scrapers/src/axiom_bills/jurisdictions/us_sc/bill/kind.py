"""South Carolina bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bgeneral appropriations act\b|\bbudget\b", BillKind.APPROPRIATIONS),
    (
        r"\bcongratulat(?:e|ing|es)\b|\bcommend(?:ing|s)?\b|\bhonor(?:ing|s)?\b|"
        r"\brecogniz(?:e|ing|es)\b|\bmemorial\b|\bexpress (?:the )?sympathy\b",
        BillKind.CEREMONIAL,
    ),
    (r"\brules\b|\bspecial order\b|\badjourn(?:ment)?\b|\bsine die\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
