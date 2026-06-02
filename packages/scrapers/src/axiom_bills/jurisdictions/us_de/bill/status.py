"""Delaware feed/action text → normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"governor signed|signed by governor", NormalizedStatus.SIGNED),
    (r"house passed|senate passed|passed chamber", NormalizedStatus.PASSED_CHAMBER),
    (r"out of committee|reported out of committee", NormalizedStatus.IN_COMMITTEE),
    (r"committee", NormalizedStatus.IN_COMMITTEE),
    (r"introduced", NormalizedStatus.INTRODUCED),
    (r"stricken", NormalizedStatus.FAILED),
])
