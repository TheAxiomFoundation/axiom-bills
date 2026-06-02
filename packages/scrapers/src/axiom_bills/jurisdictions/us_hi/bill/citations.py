"""Hawaii citation extractor."""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


def _identity(match: re.Match[str]) -> str:
    return match.group(0)


PATTERNS = [
    (
        re.compile(
            r"\bHRS\s+(?:§|Section|Sec\.?)\s*"
            r"\d+[A-Za-z]?(?::\d+[A-Za-z]?)?(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*\b",
            re.IGNORECASE,
        ),
        _identity,
    ),
    (
        re.compile(r"\b(?:section|sections)\s+\d+[A-Za-z]?(?:-\d+(?:\.\d+)?[A-Za-z]?)*(?:\([^)]+\))*\s*,?\s+Hawaii\s+Revised\s+Statutes\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bchapter\s+\d+[A-Za-z]?(?:-\d+)?\s*,?\s+Hawaii\s+Revised\s+Statutes\b", re.IGNORECASE),
        _identity,
    ),
    (
        re.compile(r"\bAct\s+\d+,\s+Session\s+Laws\s+of\s+Hawaii\s+\d{4}\b", re.IGNORECASE),
        _identity,
    ),
]

extract = regex_extractor(PATTERNS)
