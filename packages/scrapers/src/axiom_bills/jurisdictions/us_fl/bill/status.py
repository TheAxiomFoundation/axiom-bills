"""FL action-text -> normalized_status patterns.

Source: Florida Senate bill-history rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"chapter no\.", NormalizedStatus.ENACTED),
    (r"approved by governor|signed by governor", NormalizedStatus.SIGNED),
    (r"presented to governor|ordered enrolled|signed by officers", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"died|withdrawn|laid on table", NormalizedStatus.FAILED),
    (r"passed;|passed\b|concurred", NormalizedStatus.PASSED_CHAMBER),
    (r"referred to|committee agenda|favorable by|cs by\b|cs by-|placed on calendar|special order calendar|pending reference review",
     NormalizedStatus.IN_COMMITTEE),
    (r"filed|introduced|1st reading|read 1st time", NormalizedStatus.INTRODUCED),
])
