"""Virginia bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (
        r"\bappropriat(?:e|es|ing|ion|ions)\b|\bbudget bill\b|\bgeneral fund\b|"
        r"\bstate budget\b",
        BillKind.APPROPRIATIONS,
    ),
    (
        r"\bcommending\b|\bcongratulat(?:e|ing|es)\b|\bhonor(?:ing|s)?\b|"
        r"\bmemorial\b|\bcelebrat(?:e|ing|es)\b|\bexpress(?:es)? sympathy\b",
        BillKind.CEREMONIAL,
    ),
    (r"\brules of the (?:house|senate)\b|\badjourn(?:ment)?\b|\bsine die\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
