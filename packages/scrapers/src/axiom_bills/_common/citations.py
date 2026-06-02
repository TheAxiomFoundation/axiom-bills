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
PatternSpec = str | tuple[re.Pattern[str], Callable[[re.Match[str]], str]]


def regex_extractor(patterns: list[PatternSpec]) -> Extractor:
    """Build an extractor from regex strings or (pattern, normalizer) pairs."""

    compiled = [_compile_pattern(pattern) for pattern in patterns]

    def extract(text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if not text:
            return out
        for pattern, normalize in compiled:
            for match in pattern.finditer(text):
                citation = normalize(match)
                if citation:
                    out.append((match.group(0), citation))
        return out

    return extract


def _compile_pattern(pattern: PatternSpec) -> tuple[re.Pattern[str], Callable[[re.Match[str]], str]]:
    if isinstance(pattern, str):
        return re.compile(pattern, re.IGNORECASE), _normalize_raw
    return pattern


def _normalize_raw(match: re.Match[str]) -> str:
    return re.sub(r"\s+", " ", match.group(0)).strip()
