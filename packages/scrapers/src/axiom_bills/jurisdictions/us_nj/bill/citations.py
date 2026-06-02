"""New Jersey citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bN\.?J\.?S\.?A\.?\s*\d+[A-Za-z]?:\d+(?:-\d+)?[A-Za-z]?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bP\.L\.\s*\d{4},\s*c\.\s*\d+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bC\.\s*\d+[A-Za-z]?:\d+(?:-\d+)?[A-Za-z]?\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
