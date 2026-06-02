"""Oklahoma citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\b\d+\s+O\.?S\.?(?:\s+\d{4})?,?\s*(?:§|Section)\s*[\w.-]+",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(
            r"\bSection\s+[\w.-]+\s+of\s+Title\s+\d+\s+of\s+the\s+Oklahoma\s+Statutes\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"(?<!of )\bTitle\s+\d+\s+of\s+the\s+Oklahoma\s+Statutes\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
