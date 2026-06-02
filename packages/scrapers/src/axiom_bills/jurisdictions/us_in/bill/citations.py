"""Indiana citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return re.sub(r"\s+", " ", match.group(0)).replace("IC ", "IC ")


PATTERNS = [
    (
        re.compile(r"\bIC\s+\d+(?:-\d+[A-Z]?){1,5}\b", re.IGNORECASE),
        _normalize,
    ),
    (
        re.compile(r"\bIndiana Code\b", re.IGNORECASE),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
