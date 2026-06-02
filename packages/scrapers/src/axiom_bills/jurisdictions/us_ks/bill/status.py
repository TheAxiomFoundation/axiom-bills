"""KS action-text -> normalized_status patterns.

Source: Kansas KLISS bill_status history entries.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"published in the kansas register", NormalizedStatus.ENACTED),
    (r"approved by governor", NormalizedStatus.SIGNED),
    (r"enrolled and presented to governor", NormalizedStatus.ENROLLED),
    (r"vetoed by governor", NormalizedStatus.VETOED),
    (r"veto sustained", NormalizedStatus.VETOED),
    (r"veto overridden", NormalizedStatus.VETO_OVERRIDDEN),
    (r"passed as amended", NormalizedStatus.PASSED_CHAMBER),
    (r"final action.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"emergency final action.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"conference committee report was adopted", NormalizedStatus.PASSED_CHAMBER),
    (r"stricken from calendar", NormalizedStatus.FAILED),
    (r"withdrawn from calendar", NormalizedStatus.FAILED),
    (r"introduced", NormalizedStatus.INTRODUCED),
    (r"referred to committee", NormalizedStatus.IN_COMMITTEE),
    (r"hearing:", NormalizedStatus.IN_COMMITTEE),
    (r"committee report", NormalizedStatus.IN_COMMITTEE),
])
