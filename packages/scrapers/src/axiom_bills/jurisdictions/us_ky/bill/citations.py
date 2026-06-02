"""Kentucky citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bKRS\s+(?:Chapter\s+)?\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)?(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bKentucky\s+Acts\s+Chapter\s+\d+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bActs?\s+Ch\.?\s+\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

