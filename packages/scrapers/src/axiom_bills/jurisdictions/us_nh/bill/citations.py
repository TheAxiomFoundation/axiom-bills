"""New Hampshire citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bRSA\s+\d+[A-Z]?(?:-[A-Z])?(?::\d+[A-Z]?)*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bNew Hampshire Revised Statutes Annotated\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
