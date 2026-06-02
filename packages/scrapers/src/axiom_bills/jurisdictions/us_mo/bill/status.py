"""Missouri action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bsigned by governor\b|\bapproved by governor\b|\btruly agreed\b|"
        r"\bdelivered to secretary of state\b|\bchaptered\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\bdelivered to governor\b|\bsent to governor\b|\bmessage received from the governor\b", NormalizedStatus.ENROLLED),
    (
        r"\bthird read and passed\b|\bpassed\b|\bperfected\b|\bfinally passed\b|"
        r"\badopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bprefiled\b|\bfirst read\b|\bread first time\b|\bintroduced\b",
        NormalizedStatus.INTRODUCED,
    ),
    (
        r"\breferred\b|\bhearing conducted\b|\bhearing completed\b|"
        r"\bpublic hearing (?:scheduled|held)\b|"
        r"\bexecutive session completed\b|\breported do pass\b|"
        r"\bexecutive session (?:held|continued)\b|"
        r"\bvoted do pass\b|\bplaced\b|\bcalendar\b|\bsecond read\b|"
        r"\bread second time\b|\bcommittee\b|\bsubstitute\b|\bamended\b|"
        r"\baction postponed\b|\btaken up for (?:perfection|third reading)\b|"
        r"\btitle of bill\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bwithdrawn\b|\bdefeated\b|\bfailed\b|\bdied\b", NormalizedStatus.FAILED),
])
