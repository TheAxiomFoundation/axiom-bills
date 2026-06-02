"""Vermont citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b\d+[A-Z]?\s+V\.S\.A\.\s+(?:chapter\s+\d+[A-Za-z]?|"
            r"§+\s*\d+[A-Za-z]?(?:[-.]\d+[A-Za-z]?)*(?:\([a-zA-Z0-9]+\))*)\b"
        ),
        _identity,
    ),
    (
        re.compile(r"\bVermont Statutes Annotated\b|\bV\.S\.A\.\b"),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
