"""Indiana action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bpublic law\b|\bbecame law\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed by the governor\b|\bvetoed\b", NormalizedStatus.VETOED),
    (r"\bsigned by the governor\b", NormalizedStatus.SIGNED),
    (
        r"\bsigned by the president\b|\bsigned by the speaker\b|\benrolled\b|"
        r"\btransmitted to the governor\b",
        NormalizedStatus.ENROLLED,
    ),
    (r"\bpassed both\b|\bconference committee report adopted\b", NormalizedStatus.PASSED_BOTH),
    (
        r"\bthird reading\b.*\bpassed\b|\breread third time\b.*\bpassed\b|"
        r"\badopted\b|\bpassed\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (r"\bfailed\b|\bwithdrawn\b|\bdied\b|\bdefeated\b", NormalizedStatus.FAILED),
    (
        r"\bfirst reading\b|\bsecond reading\b|\breferred\b|\bcommittee\b|"
        r"\breassigned\b|\bamendment\b|\bfiscal note\b|\bcommittee report\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bfiled\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
