"""New Hampshire bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriat(?:e|ing|ion|ions)|budget|capital budget|state budget\b", BillKind.APPROPRIATIONS),
    (r"\bcommend(?:ing)?|honor(?:ing)?|recogniz(?:e|ing)|memorial\b", BillKind.CEREMONIAL),
    (r"\brules of the (?:house|senate)|adjourn(?:ment)?|sine die\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)

