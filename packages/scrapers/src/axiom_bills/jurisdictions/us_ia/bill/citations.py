"""Iowa citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bIowa\s+Code\s+(?:section|sections|chapter|chapters)?\s*"
            r"\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)*(?:\([^)]+\))*\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(
            r"\b(?:section|sections)\s+\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)*(?:\([^)]+\))*"
            r"\s*,?\s+(?:Code|Iowa\s+Code)\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bchapter\s+\d+[A-Za-z]?\s*,?\s+(?:Code|Iowa\s+Code)\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b\d{4}\s+Iowa\s+Acts\s+chapter\s+\d+[A-Za-z]?\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

