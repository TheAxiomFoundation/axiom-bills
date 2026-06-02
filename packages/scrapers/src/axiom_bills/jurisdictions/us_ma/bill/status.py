"""MA action-text -> normalized_status patterns.

Source: Massachusetts Legislature public API document history records.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"signed by the governor|governor signed", NormalizedStatus.SIGNED),
    (r"chapter \d+ of the acts", NormalizedStatus.ENACTED),
    (r"enacted and laid before|enacted", NormalizedStatus.ENROLLED),
    (r"veto", NormalizedStatus.VETOED),
    (r"adverse report|ought not to pass|no further action|sent to study|study order|placed on file", NormalizedStatus.FAILED),
    (r"read third|passed to be engrossed|passed to be enacted|senate concurred", NormalizedStatus.PASSED_CHAMBER),
    (
        r"referred to|hearing scheduled|hearing rescheduled|reporting date extended|accompanied|"
        r"reported favorably|reported, in part|reported on the residue|new draft|committee|rules suspended|discharged",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"petition|filed|received", NormalizedStatus.INTRODUCED),
])
