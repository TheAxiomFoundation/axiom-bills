"""Tennessee citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bTennessee Code Annotated,?\s+Title\s+\d+"
            r"(?:,\s*Chapter\s+\d+)?(?:\s+and\s+Title\s+\d+)?\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bTCA\s+Title\s+\d+(?:,\s*Chapter\s+\d+)?(?:\s+and\s+Title\s+\d+)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bT\.?C\.?A\.?\s*(?:§|Section)\s*[\w.-]+", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bSections?\s+\d{1,3}-\d{1,3}-\d{1,4}(?:,\s*\d{1,3}-\d{1,3}-\d{1,4})*", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
