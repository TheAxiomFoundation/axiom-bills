"""Georgia citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bO\.?C\.?G\.?A\.?\s+(?:§|Section|Sec\.?)\s*"
            r"\d+(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(
            r"\b(?:Code\s+)?Section\s+\d+(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*"
            r"\s+of\s+the\s+Official\s+Code\s+of\s+Georgia\s+Annotated\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(
            r"\b(?:Chapter|Article|Part)\s+\d+[A-Za-z]?"
            r"\s+of\s+(?:Article|Chapter|Title)\s+\d+[A-Za-z]?"
            r"\s+of\s+the\s+Official\s+Code\s+of\s+Georgia\s+Annotated\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
