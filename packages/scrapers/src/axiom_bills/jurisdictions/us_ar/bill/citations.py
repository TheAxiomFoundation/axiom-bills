"""Arkansas citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bArk(?:ansas)?\.?\s+Code(?:\s+Ann(?:otated)?\.?)?\s*"
            r"(?:§|section)?\s*\d{1,2}-\d{1,3}-\d{1,4}(?:\.\d+)?\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bA\.C\.A\.?\s*§?\s*\d{1,2}-\d{1,3}-\d{1,4}(?:\.\d+)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bAct\s+\d+\s+of\s+\d{4}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
