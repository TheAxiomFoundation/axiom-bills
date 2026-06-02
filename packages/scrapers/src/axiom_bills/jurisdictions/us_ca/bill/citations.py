"""California citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b(?:Section|Sections)\s+\d+(?:\.\d+)?(?:\s*(?:,|and)\s*\d+(?:\.\d+)?)*"
            r"\s+of\s+the\s+[A-Z][A-Za-z ]+\s+Code\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\b[A-Z][A-Za-z ]+\s+Code\s+Section\s+\d+(?:\.\d+)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bChapter\s+\d+,\s+Statutes\s+of\s+\d{4}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
