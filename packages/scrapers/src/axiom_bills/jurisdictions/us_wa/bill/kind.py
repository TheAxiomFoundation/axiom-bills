"""Washington bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (
        r"\bappropriat(?:e|es|ing|ion|ions)\b|\bbudget\b|\bcapital budget\b|"
        r"\boperating budget\b|\btransportation budget\b",
        BillKind.APPROPRIATIONS,
    ),
    (
        r"\bcommend(?:ing|s)?\b|\bcongratulat(?:e|ing|es)\b|\bhonor(?:ing|s)?\b|"
        r"\bmemorial\b|\brecogniz(?:e|ing|es)\b|\bin memory of\b",
        BillKind.CEREMONIAL,
    ),
    (
        r"\badjourn(?:ment|ing)?\b|\brules of the (?:house|senate)\b|"
        r"\bjoint rules\b|\bcutoff dates\b",
        BillKind.PROCEDURAL,
    ),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
