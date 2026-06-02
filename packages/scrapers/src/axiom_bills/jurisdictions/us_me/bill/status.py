"""Maine action-text -> normalized_status patterns.

Source: Maine Legislature official bill directory and LawMakerWeb pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bemergency enacted\b|\bgovernor'?s action: .*signed\b|"
        r"\bsigned by (?:the )?governor\b|\bpublic law chapter\b|"
        r"\bresolve chapter\b|\bprivate and special law chapter\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bheld by the governor\b", NormalizedStatus.ENROLLED),
    (
        r"\bpassed to be enacted\b|\bfinally passed\b|\bsent to the governor\b|"
        r"\bpassed to be engrossed.*in concurrence\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bpassed to be engrossed\b|\bpassage to be engrossed\b|"
        r"\bpassed to be adopted\b|\baccepted\b|\bread and adopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bdied\b|\bdead\b|\bindefinite postponement\b|\bindefinitely postponed\b|"
        r"\bplaced in legislative files\b|\bought not to pass\b|"
        r"\bleave to withdraw\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bordered printed\b|\breferred to\b|\bcommittee\b|\bsuggested\b", NormalizedStatus.INTRODUCED),
    (
        r"\btabled\b|\bunfinished business\b|\breports? read\b|\bread once\b|"
        r"\bsecond reading\b|\bamendment\b|\breconsider\b|\bcarried over\b|"
        r"\bspecial appropriations table\b|\bspecial highway table\b|"
        r"\bsent for concurrence\b|"
        r"\bordered sent forthwith\b|\broll call\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
