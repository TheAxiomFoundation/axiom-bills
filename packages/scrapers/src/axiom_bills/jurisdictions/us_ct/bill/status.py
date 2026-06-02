"""CT action-text -> normalized_status patterns.

Source: Connecticut General Assembly official bill status pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bpublic act\b|\btransmitted to the secretary of state\b", NormalizedStatus.ENACTED),
    (r"\bsigned by (?:the )?governor\b|signed by governor", NormalizedStatus.SIGNED),
    (r"\bline item vetoed\b|\bvetoed by (?:the )?governor\b", NormalizedStatus.VETOED),
    (r"\btransmitted to (?:the )?governor\b|transmitted by secretary of the state to governor", NormalizedStatus.ENROLLED),
    (r"\bin concurrence\b", NormalizedStatus.PASSED_BOTH),
    (r"\b(?:house|senate) passed\b|\bbill passed\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bfailed\b|\bwithdrawn\b|\bno action\b", NormalizedStatus.FAILED),
    (
        r"\breferred\b|\bcommittee\b|\bfavorable report\b|\bfile number\b|\bcalendar number\b|"
        r"\bfiled with legislative commissioners\b|\btabled for the calendar\b|"
        r"\bjoint favor(?:able|ably)\b|\bamendment\b|\brejected\b|\brules suspended\b|"
        r"\bemergency certification\b|\bimmediate transmittal\b|\bpublic hearing\b|"
        r"\breported out of legislative commissioners\b|\bmoved to foot of the calendar\b|"
        r"\breserved for subject matter public hearing\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\braised bill\b|\bnew bill\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
