"""Iowa bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|ion|ions)|budget|supplemental aid\b", BillKind.APPROPRIATIONS),
    (r"\bcongratulat(?:e|ing)|commend(?:ing)?|honor(?:ing)?|recogniz(?:e|ing)|memorializ", BillKind.CEREMONIAL),
    (r"\brules of the (?:house|senate)|code of ethics|adjourn(?:ment)?|recess\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)

