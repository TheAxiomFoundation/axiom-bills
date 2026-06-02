"""OH action-text -> normalized_status patterns.

Source: Ohio SOLAR/LIS legislation action records.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"governor.?signed", NormalizedStatus.SIGNED),
    (r"signed by governor", NormalizedStatus.SIGNED),
    (r"presented to governor", NormalizedStatus.ENROLLED),
    (r"enrolled", NormalizedStatus.ENROLLED),
    (r"effective", NormalizedStatus.ENACTED),
    (r"filed with secretary of state", NormalizedStatus.ENACTED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"passed", NormalizedStatus.PASSED_CHAMBER),
    (r"concur", NormalizedStatus.PASSED_CHAMBER),
    (r"re-?referred|refer to committee", NormalizedStatus.IN_COMMITTEE),
    (r"reported", NormalizedStatus.IN_COMMITTEE),
    (r"committee", NormalizedStatus.IN_COMMITTEE),
    (r"introduced", NormalizedStatus.INTRODUCED),
])
