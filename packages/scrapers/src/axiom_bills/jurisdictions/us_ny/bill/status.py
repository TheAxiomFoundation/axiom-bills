"""NY action-text → normalized_status patterns.

NYSenate actions come from the Legislative Retrieval System (LRS). The
vocabulary is reasonably stable but has senate-specific quirks: 'signed
chap.XYZ of 2026' is the canonical enactment signal; 'delivered to
governor' is what we record as ENROLLED. Order matters — most specific
first.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"signed chap\.?\s*\d+", NormalizedStatus.ENACTED),
    (r"approved by governor", NormalizedStatus.SIGNED),
    (r"delivered to governor", NormalizedStatus.ENROLLED),
    (r"vetoed memo", NormalizedStatus.VETOED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"override of veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"returned to (senate|assembly)", NormalizedStatus.PASSED_BOTH),
    (r"substituted", NormalizedStatus.PASSED_BOTH),
    (r"passed (senate|assembly)", NormalizedStatus.PASSED_CHAMBER),
    (r"3rd reading cal\.", NormalizedStatus.PASSED_CHAMBER),
    (r"reported and committed", NormalizedStatus.IN_COMMITTEE),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
    (r"reference changed", NormalizedStatus.IN_COMMITTEE),
    (r"to attorney-general for opinion", NormalizedStatus.IN_COMMITTEE),
    (r"committed to (rules|ways and means|finance)", NormalizedStatus.IN_COMMITTEE),
])
