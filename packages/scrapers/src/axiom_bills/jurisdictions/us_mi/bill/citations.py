"""Michigan citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bMCL\s+\d+(?:\.\d+[A-Za-z]?)?(?:\s*-\s*\d+(?:\.\d+[A-Za-z]?)?)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b\d{4}\s+PA\s+\d+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bPA\s+\d+['’]\d{2}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

