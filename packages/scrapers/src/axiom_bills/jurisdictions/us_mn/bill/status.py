"""MN action-text → normalized_status patterns.

Source: revisor.mn.gov bill status. MN is a biennial state with even-year
session two parts; chapter assignment is the canonical enactment.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"chapter \d+", NormalizedStatus.ENACTED),
    (r"signed by governor", NormalizedStatus.SIGNED),
    (r"presented to governor", NormalizedStatus.ENROLLED),
    (r"vetoed by governor", NormalizedStatus.VETOED),
    (r"third reading passed", NormalizedStatus.PASSED_CHAMBER),
    (r"introduction and first reading", NormalizedStatus.INTRODUCED),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
])
