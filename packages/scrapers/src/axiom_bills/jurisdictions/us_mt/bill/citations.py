"""Montana citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bsection\s+\d{1,2}-\d{1,3}-\d{1,4}\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b\d{1,2}-\d{1,3}-\d{1,4},?\s*MCA\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bMontana Code Annotated\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
