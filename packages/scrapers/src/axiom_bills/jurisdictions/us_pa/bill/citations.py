"""Pennsylvania citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bTitle\s+\d+\s+\([^)]+\)\s+of\s+the\s+Pennsylvania\s+Consolidated\s+Statutes\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\b\d+\s+Pa\.?C\.?S\.?\s*(?:§|Section)\s*[\w.-]+", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(
            r"\bact\s+of\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+\(P\.L\.\d+,\s+No\.\d+\)",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\bP\.L\.\d+,\s+No\.\d+\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
