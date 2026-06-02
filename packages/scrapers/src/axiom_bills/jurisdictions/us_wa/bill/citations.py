"""Washington citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bRCW\s+\d+[A-Z]?(?:\.\d+[A-Z]?)+(?:\([a-zA-Z0-9]+\))*\b|"
            r"\b\d+[A-Z]?\.\d+[A-Z]?\.\d+[A-Z]?\s+RCW\b"
        ),
        _identity,
    ),
    (
        re.compile(r"\bchapter\s+\d+[A-Z]?(?:\.\d+[A-Z]?)*\s+RCW\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
