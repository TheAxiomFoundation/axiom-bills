"""Washington action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bgovernor signed\b|\bsigned by governor\b|\bchapter\s+\d+\b|"
        r"\beffective date\b|\bfiled with secretary of state\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bgovernor vetoed\b|\bvetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (
        r"\bdelivered to governor\b|\bto governor\b|\benrolled\b|"
        r"\bspeaker signed\b|\bpresident signed\b|"
        r"\bsigned by speaker\b|\bsigned by president\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bpassed final passage\b|\bpassed legislature\b|\bpassed both houses\b|"
        r"\bthird reading, passed(?:;|$).*\b(?:house|senate)\b",
        NormalizedStatus.PASSED_BOTH,
    ),
    (
        r"\bthird reading, passed\b|\bpassed; yeas\b|\bpassed to rules\b|"
        r"\bpassed (?:house|senate)\b|\bplaced on third reading\b|"
        r"\breturned to (?:house|senate)\b|\bconcurred\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bdo not pass\b|\bfailed\b|\bwithdrawn\b|\brejected\b|\bstricken\b|"
        r"\bwithout recommendation\b",
        NormalizedStatus.FAILED,
    ),
    (
        r"\breferred to\b|\bpublic hearing\b|\bexecutive action\b|\bexecutive session\b|"
        r"\bcommittee\b|\bmajority;\b|\bminority;\b|\bdo pass\b|"
        r"\brules committee\b|\brules suspended\b|\bplaced on\b|\bsecond reading\b|"
        r"\bsubstitute bill substituted\b|\bamendment\(s\) adopted\b|"
        r"\bfloor amendment\b|\bby resolution\b|\breturned to\b|"
        r"\bfirst reading\b|\breferred\b|\brules [\"']?x[\"']? file\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"\bprefiled\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
])
