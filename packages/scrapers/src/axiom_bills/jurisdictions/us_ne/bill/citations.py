"""Nebraska citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _normalize(match: re.Match[str]) -> str:
    return f"Neb. Rev. Stat. § {match.group('section')}"


PATTERNS = [
    (
        re.compile(
            r"\b(?:Neb\.?\s*Rev\.?\s*Stat\.?\s*(?:§|section)?|section)\s*"
            r"(?P<section>\d{1,2}-\d{1,4}(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        _normalize,
    ),
]

extract = regex_extractor(PATTERNS)
