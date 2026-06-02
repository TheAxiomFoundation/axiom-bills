"""Hawaii action-text -> normalized_status patterns.

Source: Hawaii State Legislature official measure status pages and reports.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bact\s+\d+\b|\bapproved by governor\b|\bsigned by governor\b|"
        r"\bbecame law\b|\bwithout governor'?s signature\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\btransmitted to governor\b|\bdelivered to governor\b|\bto governor\b", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bpassed final reading\b|\bpassed third reading\b|\bpassed second reading\b|\badopted\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bpassed legislature\b|\btransmitted to governor\b", NormalizedStatus.PASSED_BOTH),
    (r"\bdeferred\b|\bnot adopted\b|\bfailed\b|\bheld\b", NormalizedStatus.FAILED),
    (
        r"\breferred\b|\bre-referred\b|\bcommittee\b|\breport adopted\b|\bheard\b|"
        r"\bhearing\b|\bscheduled\b|\bdecision making\b|\bcarried over\b|"
        r"\breported from\b|\brecommend(?:ing|ation)\b|\bnotice\b|\bconferees?\b|"
        r"\bdisagrees?\b|\breturned from\b|\breceived from\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\bpass(?:ed)? first reading\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
