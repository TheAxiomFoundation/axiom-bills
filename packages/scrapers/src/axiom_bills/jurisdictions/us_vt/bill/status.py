"""Vermont action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bgovernor approved\b|\bsigned by governor\b|\bsigned by the governor\b|"
        r"\ballowed to become law without (?:the )?signature\b|"
        r"\ballowed to become law without the signature of the governor\b|"
        r"\bas enacted\b|\bact no\.?\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto message\b", NormalizedStatus.VETOED),
    (
        r"\bdelivered to the governor\b|\bto the governor\b|\benrolled\b|"
        r"\bsigned by speaker\b|\bsigned by president\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bas passed by both\b|\bpassed by both\b|\bpassed both\b|"
        r"\badopted by senate and house\b|\badopted by house and senate\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bpassed (?:house|senate)\b|\bread 3rd time and passed\b|"
        r"\bread third time and passed\b|\b(?:3rd|third) reading ordered\b|"
        r"\badopted\b|\bagreed to\b|\bconcurred in\b|\bpassed in concurrence\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bfailed\b|\brefused\b|\brejected\b|\bstruck\b|\bwithdrawn\b|"
        r"\bdied\b|\badverse report\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\breferred to\b|\bcommittee\b|\breported\b|\brecommendation of amendment\b|"
        r"\bamend(?:ed|ment)\b|\bnotice calendar\b|\bcalendar\b|\bordered to lie\b|"
        r"\baction postponed\b|\brules suspended\b|\bnew business\b|\bfavorable\b|"
        r"\bcommitted\b|\brecommitted\b|\bmessage\b|\bread first time\b|"
        r"\bread 1st time\b|\bread second time\b|\bsecond reading\b|"
        r"\bthird reading\b|\byeas and nays\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\breleased for introduction\b", NormalizedStatus.INTRODUCED),
])
