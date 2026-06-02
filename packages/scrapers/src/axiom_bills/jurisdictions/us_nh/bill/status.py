"""New Hampshire action-text -> normalized_status patterns."""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"\bsigned by (?:the )?governor\b|\bchapter\b", NormalizedStatus.ENACTED),
    (r"\bveto overridden\b|\boverride\b", NormalizedStatus.VETO_OVERRIDDEN),
    (r"\bveto(?:ed)?\b", NormalizedStatus.VETOED),
    (r"\benrolled\b", NormalizedStatus.ENROLLED),
    (
        r"\bpassed\b|\bpassed/adopted\b|\bought to pass\b|\badopted\b|"
        r"\bconcur(?:red)?\b|\bcommittee of conference report adopted\b",
        NormalizedStatus.PASSED_CHAMBER,
    ),
    (
        r"\breferred\b|\bcommittee\b|\bhearing\b|\bexecutive session\b|"
        r"\bamend(?:ed|ment)?\b|\bretained\b|\brereferred\b|\bfloor\b|"
        r"\bwork session\b|\bsubcommittee\b|\bspecial order\b|"
        r"\btechnical and administrative corrections\b|\bspeaker appoints\b|"
        r"\bpresident appoints\b|\bremove(?:d)? from (?:the )?(?:table|consent calendar)\b|"
        r"\brecommit\b|\bno pending motion\b|\bflam\b|\bconferee change\b",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (
        r"\binexpedient to legislate\b|\bfailed\b|\bkilled\b|\bwithdrawn\b|"
        r"\bpostponed indefinitely\b|\bindefinitely postpone\b|\brefused\b|"
        r"\bdied on table\b|\brefer(?:red)? (?:for|to) interim study\b|"
        r"\bpending motion interim study\b|\blaid on table\b|\blay .+ on table\b",
        NormalizedStatus.FAILED,
    ),
    (r"\bintroduced\b|\bprefiled\b", NormalizedStatus.INTRODUCED),
])
