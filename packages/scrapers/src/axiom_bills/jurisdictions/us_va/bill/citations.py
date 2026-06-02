"""Virginia citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"§+\s*\d{1,3}(?:\.\d+)?-\d+(?:\.\d+)?(?:[:.-]\d+)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bCode of Virginia(?:,?\s+§+\s*\d{1,3}(?:\.\d+)?-\d+(?:\.\d+)?)?\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bTitle\s+\d{1,3}(?:\.\d+)?\s+of\s+the\s+Code of Virginia\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
