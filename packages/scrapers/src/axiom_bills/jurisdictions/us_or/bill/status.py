"""OR action-text -> normalized_status patterns.

Source: Oregon Legislative Information System MeasureHistoryActions.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"chapter \d+", NormalizedStatus.ENACTED),
    (r"governor signed", NormalizedStatus.SIGNED),
    (r"signed by governor", NormalizedStatus.SIGNED),
    (r"filed with secretary of state", NormalizedStatus.ENACTED),
    (r"enrolled", NormalizedStatus.ENROLLED),
    (r"president signed", NormalizedStatus.ENROLLED),
    (r"speaker signed", NormalizedStatus.ENROLLED),
    (r"third reading.*carried", NormalizedStatus.PASSED_CHAMBER),
    (r"third reading.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"rules suspended.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"repass.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"failed", NormalizedStatus.FAILED),
    (r"withdrawn", NormalizedStatus.FAILED),
    (r"introduction and first reading", NormalizedStatus.INTRODUCED),
    (r"first reading", NormalizedStatus.INTRODUCED),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
    (r"recommendation: do pass", NormalizedStatus.IN_COMMITTEE),
    (r"public hearing", NormalizedStatus.IN_COMMITTEE),
    (r"work session", NormalizedStatus.IN_COMMITTEE),
])
