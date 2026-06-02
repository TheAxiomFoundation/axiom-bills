"""UT action-text -> normalized_status patterns.

Source: Utah Legislature per-bill actionHistoryList entries.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"governor signed", NormalizedStatus.SIGNED),
    (r"to governor", NormalizedStatus.ENROLLED),
    (r"enrolled", NormalizedStatus.ENROLLED),
    (r"lieutenant governor", NormalizedStatus.ENACTED),
    (r"filed", NormalizedStatus.ENACTED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto override", NormalizedStatus.VETO_OVERRIDDEN),
    (r"3rd reading.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"2nd reading.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"final passage", NormalizedStatus.PASSED_CHAMBER),
    (r"1st reading.*introduced", NormalizedStatus.INTRODUCED),
    (r"numbered bill publicly distributed", NormalizedStatus.INTRODUCED),
    (r"to standing committee", NormalizedStatus.IN_COMMITTEE),
    (r"committee report", NormalizedStatus.IN_COMMITTEE),
    (r"held in committee", NormalizedStatus.IN_COMMITTEE),
])
