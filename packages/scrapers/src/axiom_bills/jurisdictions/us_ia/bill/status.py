"""Iowa action-text -> normalized_status patterns.

Source: Iowa Legislature official BillBook action history tables.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bchapter\s+\d+\b|\bapproved by governor\b|\bsigned by governor\b|"
        r"\bbecame law\b|\beffective\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto override\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bsent to governor\b|\bpresented to governor\b|\btransmitted to governor\b|\benrolled\b", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (
        r"\bpassed both\b|\bpassed senate and house\b|\bpassed house and senate\b|"
        r"\bpassed legislature\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bpassed house\b|\bpassed senate\b|\bpassed, yeas\b|\badopted\b|"
        r"\bimmediate message\b|\bsubstituted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bwithdrawn\b|\bindefinitely postponed\b|\bfailed\b|\bstricken\b|"
        r"\blaid over\b|\bnot adopted\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bintroduced\b|\bfirst reading\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
    (
        r"\bcommittee\b|\bsubcommittee\b|\breferred\b|\brecommend(?:s|ing)?\b|"
        r"\bplaced on calendar\b|\battached to similar bill\b|\brenumbered as\b|"
        r"\bamendment\b|\bmeeting\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
