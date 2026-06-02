"""ID action-text -> normalized_status patterns.

Source: Idaho Legislature per-bill history rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"session law chapter", NormalizedStatus.ENACTED),
    (r"reported signed by governor|signed by governor", NormalizedStatus.SIGNED),
    (r"delivered to governor|transmitted to governor|reported enrolled|signed by speaker|signed by president",
     NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"failed|not pass|held in committee|died", NormalizedStatus.FAILED),
    (r"passed\b|returned from .* passed", NormalizedStatus.PASSED_CHAMBER),
    (r"introduced|read first time", NormalizedStatus.INTRODUCED),
    (r"do pass recommendation|referred to|reported printed|committee|read second time|hold place",
     NormalizedStatus.IN_COMMITTEE),
])
