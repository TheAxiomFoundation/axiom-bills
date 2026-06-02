"""WI action-text -> normalized_status patterns.

Source: Wisconsin Legislature proposal history rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"published|report approved by the governor", NormalizedStatus.ENACTED),
    (r"governor approved", NormalizedStatus.SIGNED),
    (r"signed by governor", NormalizedStatus.SIGNED),
    (r"presented to (?:the )?governor", NormalizedStatus.ENROLLED),
    (r"enrolled", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override", NormalizedStatus.VETO_OVERRIDDEN),
    (r"passed", NormalizedStatus.PASSED_CHAMBER),
    (r"concurred", NormalizedStatus.PASSED_CHAMBER),
    (r"received from senate|ordered immediately messaged", NormalizedStatus.PASSED_CHAMBER),
    (r"failed to pass|failed to concur", NormalizedStatus.FAILED),
    (r"introduced", NormalizedStatus.INTRODUCED),
    (r"read first time", NormalizedStatus.INTRODUCED),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
    (r"public hearing", NormalizedStatus.IN_COMMITTEE),
    (r"executive action", NormalizedStatus.IN_COMMITTEE),
    (r"report passage recommended", NormalizedStatus.IN_COMMITTEE),
    (
        r"fiscal estimate|available for scheduling|^read$|read a second time|"
        r"ordered to a third reading|rules suspended|calendar|cosponsor|coauthor|"
        r"amendment|lrb correction|report .*requested|report .*received|"
        r"report .*recommended|report .*without recommendation|read a third time|"
        r"call the question|special order of business|decision of the chair|"
        r"agency briefing|withdrawn from joint committee",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
