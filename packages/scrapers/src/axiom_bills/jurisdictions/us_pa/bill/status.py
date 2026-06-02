"""Pennsylvania action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bact no\.|\bapproved by the governor\b|\bbecame law\b|\bsigned by the governor\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (r"\bsigned in (?:house|senate)\b", NormalizedStatus.SIGNED),
    (r"\bpresented to the governor\b|\bin the hands of the governor\b", NormalizedStatus.ENROLLED),
    (
        r"\bthird consideration and final passage\b|\bfinal passage\b|"
        r"\bpassed finally\b|\badopted\b|\bconcurred in\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bdefeated\b|\bnot agreed to\b|\bfailed\b|\bwithdrawn\b|\bremoved from calendar\b|"
        r"\bdropped from calendar\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\breferred to\b|\bre-?referred to\b|\bre-?committed to\b|\breported as\b|"
        r"\breported with request\b|\bcorrective reprint\b|"
        r"\bfirst consideration\b|\bsecond consideration\b|\blaid on the table\b|"
        r"\bremoved from table\b|\bamended\b|\bset on the calendar\b|\bre-?reported\b|"
        r"\bin the (?:house|senate)\b|\bprinter's no\.\b|\bremarks see\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b", NormalizedStatus.INTRODUCED),
])
