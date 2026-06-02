"""Kentucky action-text -> normalized_status patterns.

Source: Kentucky General Assembly official legislative record pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bacts?\s+ch\.?\s+\d+\b|\bdelivered to secretary of state\b|"
        r"\bsigned by governor\b|\bbecame law\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bdelivered to governor\b|\benrolled\b|\bsigned by (?:speaker|president)\b", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bpassed both houses\b|\bconcurred\b", NormalizedStatus.PASSED_BOTH),
    (r"\b3rd reading, passed\b|\bpassed \d+-\d+\b|\badopted\b", NormalizedStatus.PASSED_CHAMBER),
    (
        r"\bwithdrawn\b|\bfailed\b|\bdefeated\b|\bdead file\b|\bto line for vetoed bills\b|"
        r"\bsine die\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bintroduced\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
    (
        r"\bcommittee\b|\bto rules\b|\breported favorably\b|\bposted for passage\b|"
        r"\breturned to\b|\btaken from\b|\bfloor amendments?\b|\bcommittee substitute\b|"
        r"\bto calendar\b|\breceived in\b|\b1st reading\b|\b2nd reading\b|"
        r"\breassigned to\b|\bpassed over and retained\b|\bto .*\([hs]\)",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
