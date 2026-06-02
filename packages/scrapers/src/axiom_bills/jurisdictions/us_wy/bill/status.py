"""WY action-text -> normalized_status patterns.

Source: Wyoming Legislature BillReferences.billActions status messages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"assigned chapter number", NormalizedStatus.ENACTED),
    (r"governor signed|signed by governor", NormalizedStatus.SIGNED),
    (r"president signed|speaker signed|assigned number [hs]ea", NormalizedStatus.ENROLLED),
    (r"vetoed", NormalizedStatus.VETOED),
    (r"veto.*override|override.*veto", NormalizedStatus.VETO_OVERRIDDEN),
    (r"failed|died|withdrawn|indefinitely postponed|see mirror bill|no report prior|did not consider",
     NormalizedStatus.FAILED),
    (r"3rd reading:passed|third reading:passed|concur:passed", NormalizedStatus.PASSED_CHAMBER),
    (r"introduced and referred|recommend .*do pass|placed on general file|cow:|2nd reading|referred|rerefer|appointed jcc|received for concurrence|laid back",
     NormalizedStatus.IN_COMMITTEE),
    (r"received for introduction|bill number assigned", NormalizedStatus.INTRODUCED),
])
