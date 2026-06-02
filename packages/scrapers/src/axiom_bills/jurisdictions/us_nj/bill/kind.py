"""New Jersey bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bbudget\b|\bgeneral fund\b", BillKind.APPROPRIATIONS),
    (
        r"\bdesignates?\b.*\bday\b|\bcommemorat(?:e|es|ing)\b|\bhonor(?:s|ing)?\b|"
        r"\bcommend(?:s|ing)?\b|\bmemorializ(?:e|es|ing)\b",
        BillKind.CEREMONIAL,
    ),
    (r"\brules of the\b|\badjourn(?:s|ment)?\b|\borganizes? the legislature\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
