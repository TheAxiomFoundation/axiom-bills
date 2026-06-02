"""Alabama citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b(?:Ala\. Code|Code of Alabama)\s*(?:1975,?\s*)?§?\s*"
            r"\d+[A-Z]?-\d+[A-Z]?-\d+(?:\.\d+)?\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bSection\s+\d+[A-Z]?-\d+[A-Z]?-\d+(?:\.\d+)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bAct\s+\d{4}-\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
