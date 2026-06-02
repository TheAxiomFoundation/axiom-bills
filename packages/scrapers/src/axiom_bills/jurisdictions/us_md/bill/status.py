"""Maryland status text → normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"signed by the governor|approved by the governor|enacted under article", NormalizedStatus.SIGNED),
    (r"passed enrolled|returned passed|passed by the general assembly", NormalizedStatus.ENROLLED),
    (r"third reading passed|passed in the (house|senate)|^passed(?: with amendments)?$", NormalizedStatus.PASSED_CHAMBER),
    (r"favorable(?: report| with amendments)?|committee report", NormalizedStatus.IN_COMMITTEE),
    (r"hearing|referred|first reading", NormalizedStatus.IN_COMMITTEE),
    (r"withdrawn|failed|unfavorable report", NormalizedStatus.FAILED),
])
