"""Nevada bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|es|ing|ion|ions)\b|\bbudget\b|\bgeneral fund\b", BillKind.APPROPRIATIONS),
    (
        r"\bcommemorat(?:e|es|ing)\b|\bhonor(?:s|ing)?\b|\bcommend(?:s|ing)?\b|"
        r"\bmemorializ(?:e|es|ing)\b|\burges? congress\b|\bcongratulat(?:e|es|ing)\b",
        BillKind.CEREMONIAL,
    ),
    (
        r"\badopts? (?:the )?(?:standing |joint )?rules\b|\brules of the\b|"
        r"\badjourn(?:s|ment)?\b|\blegislative operations\b",
        BillKind.PROCEDURAL,
    ),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
