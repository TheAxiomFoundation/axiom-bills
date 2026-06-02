"""Michigan action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bassigned pa\s+\d+['’]\d{2}\b|\bassigned pa\s+\d+\b|"
        r"\bfiled with secretary of state\b|"
        r"\bapproved by (?:the )?governor\b|\bsigned by (?:the )?governor\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bpresented to the governor\b|\bordered enrolled\b|\benrolled\b", NormalizedStatus.ENROLLED),
    (
        r"\bpassed by (?:house|senate)\b|\breturned from (?:house|senate)\b|"
        r"\bpassed;? given immediate effect\b|\bpassed roll call\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\breported with recommendation\b|\breferred to\b|\bcommittee\b|"
        r"\bsecond reading\b|\bthird reading\b|\bread a second time\b|"
        r"\bread a third time\b|\bsubstitute\b|\bamend(?:ed|ment)\b|"
        r"\btransmitted\b|\breceived\b|\bbill electronically reproduced\b|"
        r"\bplaced on\b|\brules? suspended\b|\broll call\b|"
        r"\btitle (?:amended|agreed to)\b|\bfull title\b|"
        r"\brecommendation concurred in\b|\breturned to house\b|"
        r"\blaid over one day\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\bread a first time\b", NormalizedStatus.INTRODUCED),
    (r"\bdefeated\b|\bfailed\b|\bpostponed indefinitely\b", NormalizedStatus.FAILED),
])
