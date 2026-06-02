"""Oklahoma action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bapproved by gov(?:ernor)?\b|\bbecomes law without governor's signature\b|"
        r"\blaw w/o gov sig\b|\bsigned by gov(?:ernor)?\b|"
        r"\bfiled with sec(?:retary)? state\b|\bchapter(?:ed)?\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto override\b|\boverride(?:n)?\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (
        r"\bto governor\b|\btransmitted to governor\b|\bsent to governor\b|"
        r"\benrolled, signed\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bpassed.*\bhouse\b.*\bpassed.*\bsenate\b|"
        r"\bpassed.*\bsenate\b.*\bpassed.*\bhouse\b|"
        r"\bconference committee report adopted\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bthird reading\b.*\bpassed\b|\bpassed\b|\bayes:\s*\d+\s+nays:\s*\d+\b|"
        r"\bengrossed\b|"
        r"\bsent to (?:house|senate)\b|\breturned to (?:house|senate)\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bmeasure failed\b|\bfailed\b|\bdied\b|\bstricken\b|\bwithdrawn\b|"
        r"\bmotion expired\b|\bnot adopted\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\bref(?:erred)? to\b|\breferred\b|\bcommittee\b|\brec cr\b|\bdpcs\b|"
        r"\bdo pass\b|\bgeneral order\b|\bcalendar\b|\bamended\b|\bsa's\b|"
        r"\bconf granted\b|\bconf req\b|\btitle (?:stricken|restored)\b|"
        r"\bsecond reading\b|\bfrom printer\b|\brecalled from engrossment\b|"
        r"\bnotice served to reconsider\b|\bremove as coauthor\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\bfirst reading\b|\bauthored by\b|\bcoauthored by\b", NormalizedStatus.INTRODUCED),
])
