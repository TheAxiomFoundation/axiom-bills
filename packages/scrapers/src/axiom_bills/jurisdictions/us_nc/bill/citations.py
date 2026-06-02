"""North Carolina citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return f"N.C. Gen. Stat. § {match.group('section')}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:N\.?C\.?\s*Gen\.?\s*Stat\.?|G\.S\.|section)\s*(?:§)?\s*"
            r"(?P<section>\d+[A-Z]?(?:-\d+(?:\.\d+)?)?)",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
