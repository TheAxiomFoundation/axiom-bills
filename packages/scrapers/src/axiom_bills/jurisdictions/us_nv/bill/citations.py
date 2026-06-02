"""Nevada citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bNRS\s+\d+[A-Z]?(?:\.\d+[A-Z]?)+\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bchapter\s+\d+[A-Z]?\s+of\s+NRS\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
