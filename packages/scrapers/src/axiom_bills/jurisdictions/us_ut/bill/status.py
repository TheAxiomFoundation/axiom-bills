"""UT action-text -> normalized_status patterns.

Source: Utah Legislature per-bill actionHistoryList entries.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"governor signed", NormalizedStatus.SIGNED),
    (r"to governor", NormalizedStatus.ENROLLED),
    (r"enrolled", NormalizedStatus.ENROLLED),
    (r"signed by (?:president|speaker)|sent for enrolling|received .* for enrolling", NormalizedStatus.ENROLLED),
    (r"lieutenant governor", NormalizedStatus.ENACTED),
    (r"filed", NormalizedStatus.ENACTED),
    (r"vetoed|line item veto", NormalizedStatus.VETOED),
    (r"veto override", NormalizedStatus.VETO_OVERRIDDEN),
    (r"strike enacting clause|\bfailed\b", NormalizedStatus.FAILED),
    (r"3rd reading.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"2nd reading.*passed", NormalizedStatus.PASSED_CHAMBER),
    (r"final passage", NormalizedStatus.PASSED_CHAMBER),
    (
        r"passed (?:2nd|3rd) reading|to (?:senate|house)|received from (?:senate|house)|"
        r"concurs? with .*amendment",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (r"bill numbered but not distributed|received bill from legislative research", NormalizedStatus.INTRODUCED),
    (r"1st reading.*introduced", NormalizedStatus.INTRODUCED),
    (r"numbered bill publicly distributed", NormalizedStatus.INTRODUCED),
    (r"to standing committee", NormalizedStatus.IN_COMMITTEE),
    (r"committee report", NormalizedStatus.IN_COMMITTEE),
    (r"held(?: in committee)?", NormalizedStatus.IN_COMMITTEE),
    (
        r"(?:2nd|3rd) reading|fiscal note|comm - favorable recommendation|placed on|calendar|"
        r"rules to|circled|uncircled|substitut|amendment|comm rpt|not considered|"
        r"lifted from rules|returned to rules|floor amendment|fiscal (?:input|analysis)|"
        r"motion to reconsider",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
