"""RI action-text -> normalized_status patterns.

Source: Rhode Island General Assembly bill history/status search rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"chapter \d+|effective without governor|signed by governor|transmitted to secretary of state",
     NormalizedStatus.ENACTED),
    (r"transmitted to governor", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"withdrawn|indefinitely postponed|held for further study", NormalizedStatus.FAILED),
    (r"read and passed|passed in concurrence|passed as amended|passed sub [a-z]|committee recommends passage",
     NormalizedStatus.PASSED_CHAMBER),
    (r"introduced|referred to|scheduled for|placed on .*calendar|committee recommended|meeting postponed|proposed substitute|committee transferred|committee postponed",
     NormalizedStatus.IN_COMMITTEE),
])
