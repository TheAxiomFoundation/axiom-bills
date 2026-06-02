"""AZ action-text -> normalized_status patterns.

Source: Arizona Legislature official Bill Status Inquiry JSON APIs.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bchapter(?:ed)?\b|secretary of state|signed by governor|governor signed", NormalizedStatus.ENACTED),
    (r"^signed$", NormalizedStatus.SIGNED),
    (r"^governor$", NormalizedStatus.ENROLLED),
    (r"\btransmitted to governor\b|transmitted to the governor", NormalizedStatus.ENROLLED),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bfailed\b|held\b|withdrawn\b", NormalizedStatus.FAILED),
    (r"\bconcur reading\b.*\bpassed\b", NormalizedStatus.PASSED_BOTH),
    (r"\btransmitted to house\b|\btransmitted to senate\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bthird reading\b.*\bpassed\b|\bfinal reading\b.*\bpassed\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bmisc\b.*\bpassed\b|\bmotionreturn\b.*\bpassed\b|\brecon 3rd\b.*\bpassed\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bcommittee of the whole\b|\bcow\b|\bstanding committee\b|\bdo pass\b|\bproper for consideration\b", NormalizedStatus.IN_COMMITTEE),
    (r"\bconf(?:recommend|report|mem|caucus)?\b|\bcowconsent\b", NormalizedStatus.IN_COMMITTEE),
    (r"\bsecond reading\b|\bcaucus\b|\bconsent calendar\b", NormalizedStatus.IN_COMMITTEE),
    (r"\bfirst reading\b|\bintroduced\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
