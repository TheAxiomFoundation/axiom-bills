"""NE action-text -> normalized_status patterns.

Source: Nebraska Legislature bill action history rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"approved by governor|became law|slip law", NormalizedStatus.ENACTED),
    (r"presented to governor|president/speaker signed", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"indefinitely postponed|withdrawn", NormalizedStatus.FAILED),
    (
        r"passed on final reading|adopted|returned by committee|dispensing of reading at large approved",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"advanced to|placed on|referred to|hearing|committee|filed|priority bill|amended into",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"date of introduction|introduced", NormalizedStatus.INTRODUCED),
])
