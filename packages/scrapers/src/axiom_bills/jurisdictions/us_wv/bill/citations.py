"""West Virginia citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return re.sub(r"\s+", " ", match.group(0)).replace("§ ", "§")


PATTERNS = [
    (
        re.compile(r"§\s*\d+[A-Z]?(?:\s*[A-Z])?\s*-\s*\d+[A-Z]?\s*-\s*\d+[A-Z]?", re.IGNORECASE),
        _normalize,
    ),
    (
        re.compile(r"\bCode of West Virginia\b|\bWest Virginia Code\b"),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
