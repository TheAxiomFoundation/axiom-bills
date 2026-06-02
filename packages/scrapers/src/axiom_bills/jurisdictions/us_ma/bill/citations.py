"""Massachusetts citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return f"M.G.L. c. {match.group('chapter')}, § {match.group('section')}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:section|§)\s*(?P<section>\d+[A-Za-z]?)\s+of\s+chapter\s+(?P<chapter>\d+[A-Za-z]?)\b",
            re.IGNORECASE,
        ),
        _normalize,
    ),
    (
        re.compile(
            r"\b(?:M\.?G\.?L\.?|General Laws?)\s+c(?:hapter|\.)?\s*(?P<chapter>\d+[A-Za-z]?),?\s*"
            r"(?:§|section)\s*(?P<section>\d+[A-Za-z]?)\b",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
