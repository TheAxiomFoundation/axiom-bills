"""New Mexico action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bsgnd by gov\b|\bsigned by governor\b|\bch\.\s*\d+\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b|\bpartial veto\b", NormalizedStatus.VETOED),
    (r"\bpassed/[hs]\b.*\bpassed/[hs]\b|\bh/cncrd\b|\bs/cncrd\b", NormalizedStatus.PASSED_BOTH),
    (r"\bpassed/[hs]\b|\bpassed house\b|\bpassed senate\b", NormalizedStatus.PASSED_CHAMBER),
    (
        r"\b[a-z]{2,6}/[a-z]{2,6}\b|\bcommittee\b|\bdp(?:/a)?\b|\bdnp\b|"
        r"\bcs/dp\b|\bpref\b|\bnot prntd\b|\bapi\b|\bfl/?\b|\bcal\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bfailed\b|\btabled\b|\bnot passed\b|\bwithdrawn\b|\bdied\b", NormalizedStatus.FAILED),
    (r"\bintroduced\b|\bhpref\b|\bspref\b", NormalizedStatus.INTRODUCED),
])
