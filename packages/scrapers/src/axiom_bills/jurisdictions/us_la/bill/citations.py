"""Louisiana citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\b(?:La\.\s*)?R\.S\.\s*\d+[A-Za-z]?:\d+(?:\.\d+)*(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\b(?:C\.C\.|Civil Code|Code of Civil Procedure|Code of Criminal Procedure)\s+Art(?:icle|\.)?\s*\d+(?:\.\d+)*(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bChildren'?s Code\s+Art(?:icle|\.)?\s*\d+(?:\.\d+)*(?:\([^)]+\))*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bAct\s+No\.?\s+\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)

