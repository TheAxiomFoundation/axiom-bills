"""SD action-text -> normalized_status patterns.

Source: South Dakota Legislature bill action log records.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"signed by the governor", NormalizedStatus.SIGNED),
    (r"delivered to the governor", NormalizedStatus.ENROLLED),
    (r"signed by the (speaker|president)", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"failed|lost|deferred to .* legislative day", NormalizedStatus.FAILED),
    (r"do pass|passed|concurred", NormalizedStatus.PASSED_CHAMBER),
    (r"first read.*referred|referred to", NormalizedStatus.IN_COMMITTEE),
    (r"scheduled for hearing|motion to amend", NormalizedStatus.IN_COMMITTEE),
    (r"first read|introduced", NormalizedStatus.INTRODUCED),
])
