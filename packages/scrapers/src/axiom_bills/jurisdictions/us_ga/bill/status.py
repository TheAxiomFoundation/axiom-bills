"""Georgia action-text -> normalized_status patterns.

Source: Georgia General Assembly official API at legis.ga.gov.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bact/veto number\b|\bact no\.?\b|\bact\s+\d+\b|\bdate signed by governor\b|"
        r"\bsigned by governor\b|\beffective date\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bsent to governor\b|\btransmitted to governor\b", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bagreed .*amend|\bagreed .*substitute\b", NormalizedStatus.PASSED_BOTH),
    (r"\bagreed to\b|\badopted\b|\bpassed/adopted\b|\bpassed\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bwithdrawn\b|\blost\b|\bfailed\b|\bdefeated\b", NormalizedStatus.FAILED),
    (
        r"\bcommittee\b|\bcommittees?\b|\bfavorably reported\b|\bsecond readers?\b|"
        r"\bthird readers?\b|\bthird read\b|\bread and referred\b|\bread second time\b|\brecommitted\b|"
        r"\btable(?:d)?\b|\bhearing\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bhopper\b|\bfirst readers\b|\bpre[- ]?filed\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
