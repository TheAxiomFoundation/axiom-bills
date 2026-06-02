"""Mississippi action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bapproved by governor\b|\blaw\b|\bchapter\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\benrolled bill signed\b|\breturned for enrolling\b", NormalizedStatus.ENROLLED),
    (r"\bpassed\b|\bconference report adopted\b|\bconcur\b", NormalizedStatus.PASSED_CHAMBER),
    (
        r"\breferred\b|\btitle suff do pass\b|\bdo pass\b|\bamended\b|\bcommittee\b|"
        r"\bdr\s+-|\btransmitted\b|\bimmediate release\b|\btabled\b|"
        r"\bmotion to reconsider\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bdied\b|\bfailed\b", NormalizedStatus.FAILED),
    (r"\bprefiled\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
