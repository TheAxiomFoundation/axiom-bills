"""DC action-text -> normalized_status patterns.

Source: DC Council LIMS official JSON legislation detail API.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bact .* published\b|\blaw number\b|\bbecame law\b|\bpublished in dc register\b|"
        r"\benacted without mayor'?s signature\b|\btransmitted to congress\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bsigned by the mayor\b|\bmayor approved\b", NormalizedStatus.SIGNED),
    (r"\bveto(?:ed)?\b|\breturned unsigned\b", NormalizedStatus.VETOED),
    (r"\btransmitted to mayor\b|\bmayoral review\b|\benrollment\b|\breturned from mayor\b", NormalizedStatus.ENROLLED),
    (r"\bfinal reading\b|\bapproved\b|\badopted\b|\bpassed\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bdisapproved\b|\bwithdrawn\b|\bno action\b|\bfailed\b", NormalizedStatus.FAILED),
    (
        r"\bcommittee\b|\breferred\b|\bhearing\b|\broundtable\b|\bmarkup\b|"
        r"\bfirst reading\b|\bnotice\b|\bretained by the council\b|\bagenda\b|"
        r"\bre-referral\b|\bpostponed\b|\blegislative meeting other\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduced\b|\bintroduction\b", NormalizedStatus.INTRODUCED),
])
