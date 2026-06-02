"""New Mexico citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(r"\bSection\s+\d{1,3}-\d{1,3}-\d{1,3}\s+NMSA\s+1978\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"(?<!Section )\b\d{1,3}-\d{1,3}-\d{1,3}\s+NMSA\s+1978\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
