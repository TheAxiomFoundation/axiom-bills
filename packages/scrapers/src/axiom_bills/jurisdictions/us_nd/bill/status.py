"""ND action-text -> normalized_status patterns.

Source: North Dakota Legislative Branch static bills JSON action records.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"filed with secretary of state", NormalizedStatus.ENACTED),
    (r"governor signed|signed by governor", NormalizedStatus.SIGNED),
    (r"delivered to governor|sent to governor", NormalizedStatus.ENROLLED),
    (r"signed by (president|speaker)", NormalizedStatus.ENROLLED),
    (r"veto", NormalizedStatus.VETOED),
    (r"failed in (house|senate)|failed|do not pass", NormalizedStatus.FAILED),
    (
        r"second reading, passed|concurred|conference committee report adopted|emergency clause carried",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (r"introduced|first reading", NormalizedStatus.INTRODUCED),
    (
        r"committee|reported back|amendment|rereferred|laid over|received from|returned to|not concurred|"
        r"refused to concur|division",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
