"""Louisiana action-text -> normalized_status patterns.

Source: Louisiana Legislature official bill detail pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bact\s+no\.?\s+\d+\b|\bbecomes act\b|\bsigned by the governor\b|"
        r"\beffective date\b|\bsent to the secretary of state\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (
        r"\bsent to the governor\b|\bsent to the governor for executive approval\b|"
        r"\benrolled\b|\bsigned by the (?:speaker|president)\b",
        NormalizedStatus.ENROLLED,
    ),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (
        r"\bconcurred in\b|\bconference committee report\b|\breceived from the "
        r"(?:house|senate) without amendments\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bfinally passed\b|\bpassed by a vote\b|\bpassed,? ordered to\b|"
        r"\bpassed to third reading and final passage\b|\badopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bwithdrawn\b|\bfailed\b|\bdefeated\b|\bindefinitely postponed\b|"
        r"\bdied\b|\bvote\s*-\s*final passage\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bprefiled\b|\bintroduced\b|\bfirst appeared\b", NormalizedStatus.INTRODUCED),
    (
        r"\breferred to\b|\bcommittee\b|\breported\b|\bamended\b|"
        r"\bamendments\b|\bordered engrossed\b|\bcalendar\b|\bread by title\b|"
        r"\breceived in\b|\breceived from\b|\bnotice\b|"
        r"\bpassed to 3rd reading\b|\bplaced on\b|\bscheduled for\b|"
        r"\bmade special order\b|\bconferees appointed\b|\bbecomes [hs]b\s+\d+\b|"
        r"\blegislative bureau\b|\blies over\b|\brules suspended\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
