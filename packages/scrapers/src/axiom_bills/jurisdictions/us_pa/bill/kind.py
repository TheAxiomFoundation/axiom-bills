"""Pennsylvania bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bfiscal code\b|\bgeneral fund\b|\bbudget\b", BillKind.APPROPRIATIONS),
    (
        r"\bcongratulat(?:e|ing|es)\b|\bcommend(?:ing|s)?\b|\bmemorial\b|"
        r"\bhonor(?:ing|s)?\b|\brecogniz(?:e|ing|es)\b|\bcondolence\b",
        BillKind.CEREMONIAL,
    ),
    (r"\brules of the (?:house|senate)\b|\badjourn(?:ment)?\b|\bsession\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
