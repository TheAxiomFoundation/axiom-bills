"""Classifier signature shared across jurisdictions.

A classifier is `(title, subjects, bill_type, action_texts) -> BillKind`.
Per-jurisdiction implementations live in
`jurisdictions/<code>/bill/kind.py`. The shared `classify_by_title`
helper handles the regex-pattern case, which is what 80% of rules look
like; richer rules (cross-checking subjects, bill type, action texts)
fall back to plain Python.
"""
from __future__ import annotations

import re

from .models import BillKind


def classify_by_title(
    title: str | None,
    patterns: list[tuple[re.Pattern[str], BillKind]],
    *,
    default: BillKind = BillKind.SUBSTANTIVE,
) -> BillKind:
    """First pattern that matches the title wins. Empty/None title → default."""
    if not title:
        return default
    for pattern, kind in patterns:
        if pattern.search(title):
            return kind
    return default


def compile_kind_patterns(
    raw: list[tuple[str, BillKind]],
) -> list[tuple[re.Pattern[str], BillKind]]:
    return [(re.compile(p, re.IGNORECASE), k) for p, k in raw]
