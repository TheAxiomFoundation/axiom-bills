"""AR action-text -> normalized_status patterns.

Source: Arkansas Legislature official bill status history pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bnow act\b|notification that .* is now act|became act|act no\.?", NormalizedStatus.ENACTED),
    (r"\bsigned by governor\b|approved by governor", NormalizedStatus.SIGNED),
    (r"\btransmitted to the governor\b|governor'?s office", NormalizedStatus.ENROLLED),
    (r"\bto be enrolled\b|correctly enrolled|ordered enrolled|enrolled", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bfailed\b|died\b|withdrawn\b|sine die\b", NormalizedStatus.FAILED),
    (r"returned from the senate as passed|returned from the house as passed|returned to the .* as passed", NormalizedStatus.PASSED_BOTH),
    (r"returned from senate as passed|senate amendment .* concurred", NormalizedStatus.PASSED_BOTH),
    (r"emergency clause adopted", NormalizedStatus.PASSED_CHAMBER),
    (r"\breceived from the house\b|\breceived from the senate\b", NormalizedStatus.PASSED_CHAMBER),
    (r"read the third time and passed and ordered transmitted|passed and ordered transmitted", NormalizedStatus.PASSED_CHAMBER),
    (r"\bread the third time and passed\b|passed as amended", NormalizedStatus.PASSED_CHAMBER),
    (
        r"referred to .*committee|committee on|reported .*committee|placed on .*calendar|"
        r"re-referred|read (?:the )?second time|placed on second reading|amendment .* adopted|"
        r"returned by the committee|do pass|transfers? to|ordered engrossed|engrossed",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bfiled\b|read the first time|introduced", NormalizedStatus.INTRODUCED),
])
