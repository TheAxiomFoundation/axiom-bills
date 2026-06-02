"""Nevada action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bapproved by the governor\b|\bsigned by governor\b|\bchapter\s+\d+\b|"
        r"\bbecame law\b|\bfiled with secretary of state\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto override\b|\bveto overridden\b|\boverr(?:idden|ode)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b|\bnot sustained\b", NormalizedStatus.VETOED),
    (
        r"\bto enrollment\b|\benrolled and delivered\b|\bpassed both\b|"
        r"\breturned to (?:assembly|senate)\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bread third time\b.*\bpassed\b|\bpassed,? as amended\b|\bpassed\b|"
        r"\bto (?:senate|assembly)\b|\bin (?:senate|assembly)\b|\bconcurred\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\breferred to\b|\bto committee\b|\bfrom committee\b|\bdo pass\b|"
        r"\bamend(?:ed|ment)?\b|\brereferred\b|\bexemption\b|\bto printer\b|"
        r"\bfrom printer\b|\bengrossed\b|\breprint\b|\bgeneral file\b|"
        r"\bsecond reading\b|\bread second time\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (
        r"\bno further action taken\b|\bno further action allowed\b|\bno action\b|\bfailed\b|\blost\b|"
        r"\bindefinitely postponed\b|\bwithdrawn\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bprefiled\b|\bintroduced\b|\bread first time\b", NormalizedStatus.INTRODUCED),
])
