"""Illinois action-text -> normalized_status patterns.

Source: Illinois General Assembly official bill status action tables.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bpublic act\b|\bgovernor approved\b|\bsigned by governor\b|"
        r"\beffective date\b|\bbecame law\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bsent to (?:the )?governor\b|\bpresented to governor\b", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (
        r"\bpassed both houses\b|\badopted both houses\b|\bhouse concurs\b|"
        r"\bsenate concurs\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bthird reading\b.*\bpassed\b|\bpassed\b|\badopted\b|\bconcurrence\b|"
        r"\bdo pass\b|\bfloor amendment adopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bfailed\b|\bwithdrawn\b|\bheld\b|\btable\b|\bpursuant to rule\b|"
        r"\bsession sine die\b|\bno further action\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\breferred to\b|\brules committee\b|\bassignments\b|\bcommittee\b|\bsubcommittee\b|"
        r"\bpostponed\b|\bre-referred\b|\bassigned to\b|\bsponsor removed\b|"
        r"\bco-sponsor\b|\badded as\b|\bchief sponsor\b|\bchief senate sponsor\b|"
        r"\bsecond reading\b|\bplaced on calendar\b|\barriv(?:e|ed) in\b|"
        r"\breading/passage deadline\b|\bchair rules\b|\bfloor amendment\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bprefiled\b|\bfirst reading\b|\bfiled\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
