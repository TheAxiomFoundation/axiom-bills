"""Wyoming citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    section = match.group("section")
    sub = re.sub(r"\s+", "", match.group("sub") or "")
    return f"WY Stat. § {section}{sub}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:W\.?S\.?|Wyoming Statutes? (?:Section )?|section )\s*"
            r"(?P<section>\d{1,2}-\d{1,3}-\d{1,4})"
            r"(?P<sub>(?:\s*\([^)]+\))*)",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
