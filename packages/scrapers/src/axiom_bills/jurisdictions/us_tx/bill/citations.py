"""Texas citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


CODE_NAME = r"(?:[A-Z][A-Za-z'&.-]+(?:\s+[A-Z][A-Za-z'&.-]+)*\s+)?Code"

PATTERNS = [
    (
        re.compile(
            rf"\bSections?\s+\d+[A-Za-z]?(?:\.\d+)*"
            rf"(?:(?:,|\s+and)\s*\d+[A-Za-z]?(?:\.\d+)*)*,\s+{CODE_NAME}\b"
        ),
        _identity,
    ),
    (
        re.compile(rf"\bChapters?\s+\d+[A-Za-z]?(?:,\s*\d+[A-Za-z]?)*,\s+{CODE_NAME}\b"),
        _identity,
    ),
    (
        re.compile(rf"\b{CODE_NAME}\s+Section\s+\d+[A-Za-z]?(?:\.\d+)*\b"),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
