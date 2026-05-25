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
    # Enactment / executive
    (r"became public law", NormalizedStatus.ENACTED),
    (r"signed by president", NormalizedStatus.SIGNED),
    (r"presented to president", NormalizedStatus.ENROLLED),
    (r"vetoed by president", NormalizedStatus.VETOED),
    (r"veto overridden", NormalizedStatus.VETO_OVERRIDDEN),

    # Cross-chamber motion
    (r"resolving differences", NormalizedStatus.PASSED_BOTH),
    (r"received in the (house|senate)", NormalizedStatus.PASSED_CHAMBER),

    # Chamber passage
    (r"passed[/ ]agreed to in (house|senate)", NormalizedStatus.PASSED_CHAMBER),
    (r"on agreeing to the resolution.*agreed to", NormalizedStatus.PASSED_CHAMBER),
    (r"on passage.*passed", NormalizedStatus.PASSED_CHAMBER),

    # Committee referral — Congress.gov writes "Referred to the House
    # Committee on X" / "Referred to the Subcommittee on Y", so allow any
    # words between "referred to" and "committee".
    (r"referred to .*(committee|subcommittee)", NormalizedStatus.IN_COMMITTEE),

    # Introduction (must come last; "submitted in House" is the
    # resolution-flavored intro action).
    (r"introduced in (house|senate)", NormalizedStatus.INTRODUCED),
    (r"submitted in (house|senate)", NormalizedStatus.INTRODUCED),
])
