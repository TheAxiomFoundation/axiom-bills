"""New Mexico bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bgeneral appropriation\b|\bfeed bill\b", BillKind.APPROPRIATIONS),
    (r"\bmemorial\b|\bhonor(?:ing)?\b|\brecogniz(?:e|ing)\b|\bcommend(?:ing)?\b", BillKind.CEREMONIAL),
    (r"\brules\b|\badjourn(?:ment)?\b|\bsession expenses\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
