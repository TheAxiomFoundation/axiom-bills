"""Arizona citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b(?:A\.R\.S\.|Arizona Revised Statutes)\s*"
            r"(?:§|section)?\s*\d{1,2}-\d{1,4}(?:\.\d+)?\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"(?<!Statutes )\bsection\s+\d{1,2}-\d{1,4}(?:\.\d+)?\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
