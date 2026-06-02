"""Tennessee action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bpub(?:lic)?\.?\s+ch(?:apter)?\.?\b|\bprivate ch(?:apter)?\.?\b|"
        r"\bpr\.?\s+ch(?:apter)?\.?\b|\bsigned by governor\b|\bbecame (?:a )?law\b|"
        r"\beffective date\(s\)",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (
        r"\btransmitted to governor\b|\bsent to governor\b|\benrolled\b|"
        r"\bsigned by (?:h\.?|house|s\.?|senate) speaker\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bpassed\b|\bsubst\.?\b|\bsubstituted\b|\badopted\b|\bconcurred\b|"
        r"\bengrossed\b|\bready for transmission\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bfailed\b|\bwithdrawn\b|\brejected\b|\bnot adopted\b|"
        r"\btaken off notice\b|\breturned to the clerk's desk\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\brefer(?:red)? to\b|\bassigned to\b|\bplaced on\b|\brec\. for pass\b|"
        r"\baction def(?:erred)?\b|\breset\b|\bam\.?\b|\bamended\b|"
        r"\bsecond consideration\b|\bp2c\b|\bcalendar\b|\bcommittee\b|"
        r"\bsponsor\(s\) added\b|\bheld on desk\b|\bplaced behind the budget\b|"
        r"\bmeeting canceled\b|\bno action taken\b|\blift tableing motion\b|"
        r"\brefused to recede\b|\bconf\. comm\. appointed\b|\bsummer study\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bintro(?:duced)?\.?\b|\bfiled for introduction\b|\bfirst consideration\b|\bp1c\b", NormalizedStatus.INTRODUCED),
])
