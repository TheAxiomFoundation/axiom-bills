"""Indiana bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bvehicle bill\b", BillKind.VEHICLE),
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bbudget\b|\bfiscal matters\b", BillKind.APPROPRIATIONS),
    (r"\bcongratulat(?:e|ing|es)\b|\bcommend(?:ing|s)?\b|\bhonor(?:ing|s)?\b|\bmemorial\b", BillKind.CEREMONIAL),
    (r"\brules of the (?:house|senate)\b|\badjourn(?:ment|ing)?\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
