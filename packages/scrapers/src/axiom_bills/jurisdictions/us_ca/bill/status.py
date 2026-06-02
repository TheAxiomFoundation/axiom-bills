"""CA action-text -> normalized_status patterns.

Source: California Legislative Information official bill history pages.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bchaptered\b|secretary of state - chapter|statutes of \d{4}", NormalizedStatus.ENACTED),
    (r"\bapproved by the governor\b|signed by the governor", NormalizedStatus.SIGNED),
    (r"\benrolled and presented to the governor\b|engrossing and enrolling", NormalizedStatus.ENROLLED),
    (r"\bvetoed\b", NormalizedStatus.VETOED),
    (r"\bfailed\b|\bdied\b|\bwithdrawn\b", NormalizedStatus.FAILED),
    (r"\bconcurrence in .* amendments pending\b", NormalizedStatus.PASSED_BOTH),
    (r"\bread third time\. passed\. ordered to the (?:assembly|senate)\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bpassed\b.*\bordered to the (?:assembly|senate)\b", NormalizedStatus.PASSED_CHAMBER),
    (r"\bordered to the (?:assembly|senate)\b|\bto assembly\b", NormalizedStatus.PASSED_CHAMBER),
    (
        r"\bfrom committee\b|\breferred to\b|\bin committee\b|\bdo pass\b|"
        r"\bread second time\b|\bordered to third reading\b|\bconsent calendar\b|"
        r"\bordered to second reading\b|\bre-referred\b|\bamended\b|\bcoauthors revised\b|"
        r"\brule .* suspended\b|\bjoint rule\b|\bfrom inactive file\b|\bpending re-refer\b|"
        r"\baction rescinded\b|\bheld at desk\b|\bordered to inactive file\b|"
        r"\bconsideration of governor'?s veto\b|\bayes\s+\d+\. noes\s+\d+",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintroduc(?:ed|tion)\b|\bread first time\b|\bfrom printer\b", NormalizedStatus.INTRODUCED),
])
