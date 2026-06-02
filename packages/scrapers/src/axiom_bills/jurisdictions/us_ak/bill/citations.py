"""Alaska citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return f"AS {match.group('section')}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:AS|Alaska Statutes? section|section)\s*"
            r"(?P<section>\d{2}\.\d{2}(?:\.\d{3})?)",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
