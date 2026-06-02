"""Mississippi citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bSection\s+\d+(?:-\d+)+(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bMississippi Code of 1972\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

