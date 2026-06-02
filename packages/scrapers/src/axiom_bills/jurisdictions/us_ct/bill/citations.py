"""Connecticut citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b(?:section|sections)\s+\d+[a-z]?(?:-\d+[a-z]?)*(?:\s*(?:,|and)\s*\d+[a-z]?(?:-\d+[a-z]?)*)*"
            r"\s+of\s+the\s+general\s+statutes\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bConn(?:ecticut)?\.?\s+Gen(?:eral)?\.?\s+Stat(?:utes?)?\.?\s+(?:§|Sec\.?)\s*\d+[a-z]?(?:-\d+[a-z]?)*\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bPublic Act\s+\d{2}-\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
