"""MN action-text → normalized_status patterns.

Source: revisor.mn.gov bill status. MN is a biennial state with even-year
session two parts; chapter assignment is the canonical enactment.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"chapter \d+", NormalizedStatus.ENACTED),
    (r"signed by governor|governor approval", NormalizedStatus.SIGNED),
    (r"presented to governor", NormalizedStatus.ENROLLED),
    (r"vetoed by governor", NormalizedStatus.VETOED),
    (r"bill was passed", NormalizedStatus.PASSED_CHAMBER),
    (r"third reading passed", NormalizedStatus.PASSED_CHAMBER),
    (r"introduction and first reading", NormalizedStatus.INTRODUCED),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
    (
        r"author|second reading|third reading|calendar|motion prevailed|conferees|"
        r"committee report|comm report|received from|returned from|special order|"
        r"take from table|taken from table|lay on the table|laid on table|conference committee|"
        r"first reading|rule|substituted|amended|pg\.",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"indefinitely postponed", NormalizedStatus.FAILED),
])
