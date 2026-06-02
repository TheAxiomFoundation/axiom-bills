"""District of Columbia citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bD\.?C\.?\s+Official\s+Code\s+(?:§|Section|Sec\.?)\s*\d+[A-Za-z]?(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\b(?:section|sections)\s+\d+[A-Za-z]?(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*\s+of\s+the\s+District\s+of\s+Columbia\s+Official\s+Code\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bD\.?C\.?\s+Law\s+\d+-\d+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bAct\s+A\d{2}-\d{4}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
