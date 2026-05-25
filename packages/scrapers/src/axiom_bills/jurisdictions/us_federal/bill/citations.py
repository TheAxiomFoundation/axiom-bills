"""Federal citation extractor.

Captures the citation forms federal bills actually use, in priority
order. We normalize to the same shape rulespec-us uses for file paths
(e.g. '26 USC 32(a)(1)') so axiom_encodings lookups are direct equality.

Edge cases we explicitly handle:
  * '26 U.S.C. § 32(a)(1)' (formal)
  * '26 USC 32(a)(1)'      (informal)
  * 'section 32(a)(1) of the Internal Revenue Code'
  * '7 CFR 273.3' / '7 C.F.R. § 273.3'
  * 'section 6(b) of the Food and Nutrition Act of 2008' (Title 7)
"""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


# IRC = Title 26. The codifier rarely cross-refs IRC to other titles, so
# 'Internal Revenue Code' → Title 26 is a safe simplifying assumption.
ACT_TO_TITLE: dict[str, str] = {
    "internal revenue code":            "26",
    "social security act":              "42",
    "food and nutrition act":           "7",
    "affordable care act":              "42",
    "patient protection and affordable care act": "42",
}


def _subscripts(match: re.Match[str], group_name: str = "sub") -> str:
    """Pull '(a)(1)(B)' or '(a)' from a regex match group, normalized."""
    raw = match.group(group_name)
    if not raw:
        return ""
    # Already has parens — keep as-is, just strip whitespace.
    return re.sub(r"\s+", "", raw)


def _normalize_usc(match: re.Match[str]) -> str:
    title = match.group("title")
    section = match.group("section")
    sub = _subscripts(match)
    return f"{title} USC {section}{sub}"


def _normalize_cfr(match: re.Match[str]) -> str:
    title = match.group("title")
    part = match.group("part")
    section = match.group("section")
    sub = _subscripts(match)
    return f"{title} CFR {part}.{section}{sub}"


def _normalize_act_section(match: re.Match[str]) -> str:
    act = match.group("act").lower().strip()
    title = ACT_TO_TITLE.get(act)
    if not title:
        return ""
    section = match.group("section")
    sub = _subscripts(match)
    return f"{title} USC {section}{sub}"


# Order matters: try the explicit USC/CFR forms before the act-name fallback.
RAW_PATTERNS: list[tuple[str, callable]] = [
    # 26 U.S.C. § 32(a)(1)  /  26 USC 32(a)(1)  /  26 USC §32
    (
        r"\b(?P<title>\d{1,2})\s*"
        r"U\.?\s*S\.?\s*C\.?\s*"
        r"(?:§\s*)?(?P<section>\d+[A-Z]?)"
        r"(?P<sub>(?:\s*\([0-9a-zA-Z]+\))*)",
        _normalize_usc,
    ),
    # 7 CFR 273.3(b)(2)  /  7 C.F.R. § 273.3
    (
        r"\b(?P<title>\d{1,2})\s*"
        r"C\.?\s*F\.?\s*R\.?\s*"
        r"(?:§\s*)?(?P<part>\d+)\.(?P<section>\d+)"
        r"(?P<sub>(?:\s*\([0-9a-zA-Z]+\))*)",
        _normalize_cfr,
    ),
    # 'section 32(a)(1) of the Internal Revenue Code'
    (
        r"section\s+(?P<section>\d+[A-Z]?)"
        r"(?P<sub>(?:\s*\([0-9a-zA-Z]+\))*)"
        r"\s+of\s+(?:the\s+)?(?P<act>"
        r"Internal Revenue Code"
        r"|Social Security Act"
        r"|Food and Nutrition Act(?:\s+of\s+\d{4})?"
        r"|Patient Protection and Affordable Care Act"
        r"|Affordable Care Act"
        r")",
        _normalize_act_section,
    ),
]


PATTERNS = [(re.compile(p, re.IGNORECASE), n) for p, n in RAW_PATTERNS]
extract = regex_extractor(PATTERNS)
