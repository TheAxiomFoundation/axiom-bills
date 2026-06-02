"""CO action-text → normalized_status patterns.

Source: leg.colorado.gov bill history. CO's vocabulary distinguishes
'Governor Signed' from 'Governor Signed Into Law' (the latter is the
post-chaptering canonical signal in practice).
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"governor signed into law", NormalizedStatus.ENACTED),
    (r"governor signed", NormalizedStatus.SIGNED),
    (r"sent to (the )?governor", NormalizedStatus.ENROLLED),
    (r"governor vetoed", NormalizedStatus.VETOED),
    (r"veto override", NormalizedStatus.VETO_OVERRIDDEN),
    (r"signed by (the speaker|the president)", NormalizedStatus.PASSED_BOTH),
    (r"concur.*repass", NormalizedStatus.PASSED_CHAMBER),
    (r"third reading passed", NormalizedStatus.PASSED_CHAMBER),
    (r"second reading.*passed", NormalizedStatus.IN_COMMITTEE),
    (r"laid over", NormalizedStatus.IN_COMMITTEE),
    (r"introduced in (house|senate)", NormalizedStatus.INTRODUCED),
    (r"referred to", NormalizedStatus.IN_COMMITTEE),
    (r"committee on .* (report|refer)", NormalizedStatus.IN_COMMITTEE),
    (r"witness testimony|committee discussion|considered .*amendments", NormalizedStatus.IN_COMMITTEE),
])
