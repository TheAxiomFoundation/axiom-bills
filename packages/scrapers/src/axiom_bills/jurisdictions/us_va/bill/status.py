"""Virginia action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (
        r"\bacts of assembly chapter\b|\bchapter \d+\b|\bapproved by governor\b|"
        r"\bgovernor: approved\b|\bsigned by governor\b",
        NormalizedStatus.ENACTED,
    ),
    (r"\bveto overridden\b|\boverrid(?:e|den)\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bvetoed\b|\bgovernor: vetoed\b|\bveto\b", NormalizedStatus.VETOED),
    (
        r"\benrolled\b|\bcommunicated to governor\b|\bsigned by speaker\b|"
        r"\bsigned by president\b|\bexamined by\b|\breenrolled\b",
        NormalizedStatus.ENROLLED,
    ),
    (
        r"\bpassed\b|\bagreed to\b|\bthird reading\b|\bengrossed\b|"
        r"\bconstitutional reading dispensed\b|\bread third time\b|"
        r"\bconcurred in governor's recommendation\b|\bgovernor's recommendation adopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\bfailed\b|\bstricken\b|\bpassed by indefinitely\b|\bleft in\b|"
        r"\bcontinued to\b|\btabled\b|\brejected\b|\bdefeated\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bprefiled\b|\boffered\b|\bintroduced\b", NormalizedStatus.INTRODUCED),
    (
        r"\breferred to\b|\breported from\b|\bassigned\b|\bsubcommittee\b|"
        r"\bfiscal impact statement\b|\bcommittee\b|\bread first time\b|"
        r"\bread second time\b|\bprinted\b|\breported\b|\bsubstitute\b|"
        r"\bamendments?\b|\bplaced on calendar\b|\brereferred\b|"
        r"\brules suspended\b|\bgovernor's action deadline\b|"
        r"\bgovernor's recommendation(?: received)?\b|\bconference report\b|"
        r"\bconferees?\b|\bacceded to request\b|\bmoved from .*calendar\b|"
        r"\bbudget amendments available\b|\bmotion for special\b|\bincorporates\b|"
        r"\bcontinued from last session\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
])
