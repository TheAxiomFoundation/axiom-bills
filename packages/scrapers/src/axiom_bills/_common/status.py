"""Status-text normalization helpers.

Each jurisdiction has its own action vocabulary; this module hosts
reusable patterns. State-specific maps live next to the scraper in
`jurisdictions/<code>/bill/status.py`.
"""
from __future__ import annotations

import re

from .models import NormalizedStatus


def match_first(text: str, patterns: list[tuple[re.Pattern[str], NormalizedStatus]]) -> NormalizedStatus | None:
    """Return the first matching normalized status, or None.

    Patterns are tried in order; put the most specific patterns first
    (e.g. 'signed by governor' before 'signed').
    """
    for pattern, status in patterns:
        if pattern.search(text):
            return status
    return None


def compile_patterns(raw: list[tuple[str, NormalizedStatus]]) -> list[tuple[re.Pattern[str], NormalizedStatus]]:
    return [(re.compile(p, re.IGNORECASE), s) for p, s in raw]
