"""Illinois citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\b\d+\s+ILCS\s+\d+(?:/\d+(?:-\d+(?:\.\d+)?)?)?(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b\d+\s+Ill\.?\s+Adm\.?\s+Code\s+\d+(?:\.\d+)?(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bPublic\s+Act\s+\d{2,3}-\d+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bCh\.\s*\d+,\s*par\.\s*[\w.-]+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

