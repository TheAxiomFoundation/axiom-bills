"""West Virginia action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
(r"\bsigned by governor\b|\beffective from passage\b|\beffective (?:july|june|may|april|march|february|january)\b|\bchapter\b|\bapproved by governor\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (r"\bcommunicated to governor\b|\bto governor\b|\benrolled\b|\bsigned by presiding officers\b", NormalizedStatus.ENROLLED),
    (r"\bpassed legislature\b|\bpassed both\b|\bcompleted legislative action\b", NormalizedStatus.PASSED_BOTH),
    (
        r"\bpassed (?:house|senate)\b|\bpassed bill\b|\bread 3rd time\b|\bon 3rd reading\b|"
        r"\bcommunicated to (?:house|senate)\b|\bconcurred in\b|\breceded and passed\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (r"\bfailed\b|\brejected\b|\bwithdrawn\b|\bdo not pass\b|\bstricken\b", NormalizedStatus.FAILED),
    (
        r"\bto [a-z &]+\b|\bcommittee\b|\breported\b|\bread 2nd time\b|\bon 2nd reading\b|"
        r"\bread 1st time\b|\bon 1st reading\b|\bamendment\b|\bspecial calendar\b|"
        r"\bimmediate consideration\b|\breference dispensed\b|\bhouse received\b|"
        r"\bcommittee substitute\b|\bhouse message received\b|\bmarkup discussion\b|\bdo pass\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bfiled for introduction\b|\bintroduced in (?:house|senate)\b", NormalizedStatus.INTRODUCED),
])
