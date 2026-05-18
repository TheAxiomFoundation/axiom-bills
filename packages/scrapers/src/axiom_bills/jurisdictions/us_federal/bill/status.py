"""Federal action-text → normalized_status patterns.

Congress.gov action text is comparatively well-structured because it
originates from the Library of Congress's own controlled vocabulary. We
still match conservatively: when unsure, return None and let the bill
sit at UNKNOWN rather than guess.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

# Ordered most-specific → least-specific. First match wins.
PATTERNS = compile_patterns([
    (r"became public law", NormalizedStatus.ENACTED),
    (r"signed by president", NormalizedStatus.SIGNED),
    (r"presented to president", NormalizedStatus.ENROLLED),
    (r"vetoed by president", NormalizedStatus.VETOED),
    (r"veto overridden", NormalizedStatus.VETO_OVERRIDDEN),
    (r"passed[/ ]agreed to in (house|senate)", NormalizedStatus.PASSED_CHAMBER),
    (r"resolving differences", NormalizedStatus.PASSED_BOTH),
    (r"referred to (the )?(committee|subcommittee)", NormalizedStatus.IN_COMMITTEE),
    (r"introduced in (house|senate)", NormalizedStatus.INTRODUCED),
])
