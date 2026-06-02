"""Maine citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\b\d+\s+M\.?R\.?S\.?A\.?\s*(?:§|section)\s*\d+[A-Za-z-]*(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bTitle\s+\d+,?\s+section\s+\d+[A-Za-z-]*(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b(?:Public Law|Resolve|Private and Special Law)\s+\d{4},?\s+chapter\s+\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

