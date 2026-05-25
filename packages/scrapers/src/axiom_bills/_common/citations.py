"""Shared citation-extraction primitives.

Each jurisdiction supplies its own list of regex patterns plus a
normalizer that maps the matched text to a canonical citation string
matching the format axiom_encodings uses ('26 USC 32(a)(1)', '7 CFR
273.3', etc.).

The extractor returns a list of (raw_match, normalized_citation) tuples.
We deduplicate at write time on (bill_id, citation, source).
"""
from __future__ import annotations

import re
from typing import Callable


Extractor = Callable[[str], list[tuple[str, str]]]


def regex_extractor(patterns: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]]) -> Extractor:
    """Build an extractor that runs each (pattern, normalizer) against text."""

    def extract(text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if not text:
            return out
        for pattern, normalize in patterns:
            for match in pattern.finditer(text):
                citation = normalize(match)
                if citation:
                    out.append((match.group(0), citation))
        return out

    return extract
