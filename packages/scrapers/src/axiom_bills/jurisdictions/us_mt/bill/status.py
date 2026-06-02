"""Montana action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bchapter number assigned\b|\bbecame law\b|\bsigned by governor\b|"
        r"\bapproved by governor\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (
        r"\benrolled\b|\btransmitted to governor\b|\breturned from enrolling\b|"
        r"\bsigned by (?:speaker|president)\b|\bsent to enrolling\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bthird reading passed\b|\bsecond reading passed\b|\bpassed\b|"
        r"\bconcurred\b|\bconference committee report adopted\b|"
        r"\btransmitted to (?:house|senate)\b|\breturned to (?:house|senate)\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\breferred\b|\bcommittee\b|\bhearing\b|\btable(?:d)?\b|"
        r"\bamend(?:ed|ment)?\b|\bfiscal note\b|\breport\b|\bblast\b|"
        r"\bscheduled for (?:2nd|3rd) reading\b|\bpass consideration\b|"
        r"\bplaced on (?:2nd|3rd) reading\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (
        r"\bdied\b|\bfailed\b|\bprobably dead\b|\bcanceled\b|\badverse committee\b|"
        r"\bpostponed indefinitely\b|\bindefinitely postponed\b|"
        r"\bmissed deadline\b|\bbill withdrawn\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\bintroduced\b|\bfirst reading\b|\bdraft\b|\bprefiled\b|\bdrafter assigned\b",
        NormalizedStatus.INTRODUCED,
    ),
])
