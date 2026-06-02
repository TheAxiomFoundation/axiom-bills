"""New Jersey action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bapproved\b|\bsigned by governor\b|\bchapter\b|\bfiled with secretary of state\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto override\b|\boverr(?:idden|ode)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b|\bconditional veto\b|\breconsideration\b", NormalizedStatus.VETOED),
    (
        r"\bpassed both houses\b|\bpassed both\b|\bsubstituted for\b|\bidentical bill passed\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bpassed by (?:the )?(?:assembly|senate)\b|\bpassed assembly\b|\bpassed senate\b|"
        r"\breceived in the (?:assembly|senate)\b|\bsecond reading\b|\bthird reading\b|"
        r"\bconcurred\b|\breturned to (?:assembly|senate)\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\breferred to\b|\breported (?:out of|from)\b|\bcommittee\b|\bpublic hearing\b|"
        r"\bamend(?:ed|ment)?\b|\brecommitted\b|\bre-referred\b|\bwithdrawn from\b|"
        r"\btransferred to\b|\bfiscal note\b|\bcommittee substitute\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (
        r"\bwithdrawn\b|\bfailed\b|\bnot passed\b|\bno action\b|\bpocket veto\b|"
        r"\blaid over\b|\bremoved from agenda\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bintroduced\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
