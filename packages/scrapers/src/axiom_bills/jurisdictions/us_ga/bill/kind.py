"""Georgia bill kind classifier."""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind

TITLE_PATTERNS = compile_kind_patterns([
    (r"\bappropriation|appropriations|budget|supplemental budget|fiscal year\b", BillKind.APPROPRIATIONS),
    (
        r"\brecogniz(?:e|ing)|commend(?:ing)?|congratulat(?:e|ing)|honor(?:ing)?|"
        r"\bin memory|invite(?:d)?|special day\b",
        BillKind.CEREMONIAL,
    ),
    (r"\brules of the (?:house|senate)|committee(?:s)?;? create|adjourn|sine die\b", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)

