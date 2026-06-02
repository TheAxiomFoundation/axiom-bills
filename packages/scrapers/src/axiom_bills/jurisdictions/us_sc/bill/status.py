"""South Carolina action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bact no\.|\bsigned by governor\b|\bapproved by governor\b|\bbecame law\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (r"\bratified\b|\bsent to governor\b|\bpresented to governor\b", NormalizedStatus.ENROLLED),
    (
        r"\bread third time\b|\bthird reading\b|\bsent to (?:senate|house)\b|"
        r"\breturned to (?:senate|house)\b|\badopted\b|\bconcurred\b|\bpassed\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (r"\brejected\b|\bfailed\b|\btabled\b|\bdied\b|\bcontinued\b", NormalizedStatus.FAILED),
    (
        r"\breferred to\b|\bcommittee report\b|\bfavorable\b|\bamended\b|\bread second time\b|"
        r"\broll call\b|\brecall(?:ed)?\b|\bscrivener's error\b|\brecommitted\b|"
        r"\bcarried over\b|\bdebate adjourned\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\bread first time\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
