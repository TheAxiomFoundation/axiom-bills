"""South Carolina citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bSections?\s+\d{1,3}-\d{1,3}-\d{1,4}(?:,\s*\d{1,3}-\d{1,3}-\d{1,4})*", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bSouth Carolina Code(?: of Laws)?\s+Section\s+\d{1,3}-\d{1,3}-\d{1,4}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
