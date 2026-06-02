"""Texas action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\beffective (?:immediately|on|date)\b|\bsigned by the governor\b|\bfiled with the secretary of state\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (
        r"\bsent to the governor\b|\breported enrolled\b|\bsigned in the (?:house|senate)\b|"
        r"\benrolled\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bpassed\b|\badopted\b|\bconcurs?\b|\bthird reading\b|\bengross(?:ed|ment)\b|"
        r"\breturned to (?:house|senate)\b|\breceived from the (?:house|senate)\b|"
        r"\bsenate passage(?: as amended)? reported\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bfail(?:ed|s)?\b|\bwithdrawn\b|\blaid on the table\b|\bleft pending\b|"
        r"\bno action taken\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\breferred to\b|\breported favorably\b|\breported unfavorably\b|\brecommended\b|"
        r"\bcommittee\b|\bposting rule suspended\b|\bplaced on\b|\bset on\b|"
        r"\bconsidered\b|\btestimony\b|\bmeeting (?:cancelled|canceled)\b|"
        r"\bamendments?\b|\banalysis distributed\b|\brecord vote\b|\bstatement\(s\) of vote\b|"
        r"\bread\b|\bscheduled for public hearing\b|\bvote recorded in journal\b|"
        r"\breason for vote recorded in journal\b|\bco-sponsor authorized\b|"
        r"\brules suspended\b|\bthree day rule suspended\b|\bprinting rule suspended\b|"
        r"\bordered not printed\b|\bremarks ordered printed\b|\bpostponed\b|"
        r"\bprevious question ordered\b|\bmotion (?:to suspend|prevails)\b|"
        r"\bsubject to art\.?iii sec\.?49a\b|\blaid out as postponed business\b|"
        r"\bamended\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bfiled\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
