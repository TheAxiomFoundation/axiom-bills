"""AL action-text -> normalized_status patterns.

Source: Alabama Legislature ALISON official GraphQL instrument history.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\benacted\b|act \d{4}-\d+", NormalizedStatus.ENACTED),
    (r"\bsigned by governor\b|governor'?s signature", NormalizedStatus.SIGNED),
    (r"\bdelivered to governor\b|transmitted to governor|signature requested", NormalizedStatus.ENROLLED),
    (r"\benrolled\b|ready to enroll", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bindefinitely postponed\b|failed\b|withdrawn\b", NormalizedStatus.FAILED),
    (r"\bthird reading in second house\b|passed second house", NormalizedStatus.PASSED_BOTH),
    (r"\bthird reading in house of origin\b|read a third time and pass|engrossed", NormalizedStatus.PASSED_CHAMBER),
    (r"\badopted roll call\b|motion to adopt - adopted", NormalizedStatus.PASSED_CHAMBER),
    (
        r"pending committee action|referred to .* committee|reported out of committee|"
        r"placed on the calendar|second time and placed on the calendar|committee",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"amendment offered|intended to vote|carried over", NormalizedStatus.IN_COMMITTEE),
    (r"\bfirst reading\b|read for the first time|prefiled|introduced", NormalizedStatus.INTRODUCED),
])
