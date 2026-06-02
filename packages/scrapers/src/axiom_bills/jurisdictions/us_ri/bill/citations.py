"""Rhode Island citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    section = match.group("section")
    return f"RI Gen. Laws § {section}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:R\.?I\.? Gen(?:eral)? Laws(?: §| section)?|section)\s*"
            r"(?P<section>\d{1,2}-\d{1,3}-\d{1,3}(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
