"""North Dakota citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return f"N.D.C.C. § {match.group('section')}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:North Dakota Century Code(?: section| sections)?|N\.D\.C\.C\. §?|section)\s*"
            r"(?P<section>\d{1,2}-\d{2}(?:\.\d+)?-\d{2})",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
