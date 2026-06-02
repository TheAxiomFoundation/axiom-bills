"""NC action-text -> normalized_status patterns.

Source: North Carolina General Assembly official RSS bill history feeds.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"ch\. sl|session law|became law", NormalizedStatus.ENACTED),
    (r"signed by gov|signed by governor", NormalizedStatus.SIGNED),
    (r"ratified|presented to governor|pres\. to gov|ordered enrolled|enrolled", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"failed|withdrawn|postponed indefinitely", NormalizedStatus.FAILED),
    (r"filed|passed 1st reading|first reading", NormalizedStatus.INTRODUCED),
    (r"passed|adopted|concurred|message sent to (senate|house)|ordered engrossed|engrossed", NormalizedStatus.PASSED_CHAMBER),
    (
        r"ref to com|re-ref|committee|calendar|reported favorably|serial referral|"
        r"committee substitute|amendment|amend tabled|placed on calendar|placed on cal|cal pursuant|"
        r"reptd fav|conf com|message received|ruled material",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
