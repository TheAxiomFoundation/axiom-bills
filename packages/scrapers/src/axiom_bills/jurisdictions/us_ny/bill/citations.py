"""NY citation extractor — initial cut.

NY refers to its own statutes by `<law-name> § <section>` rather than a
title-numbered USC structure. We capture the common law names; matching
against axiom_encodings requires per-jurisdiction state encoding repos
(rulespec-us-ny) which are out of scope for the prototype.
"""
from __future__ import annotations

import re

from axiom_bills._common.citations import regex_extractor


# NY laws-of-record common in tax/benefit bills.
NY_LAWS = (
    "tax law",
    "social services law",
    "education law",
    "labor law",
    "public health law",
    "real property tax law",
)


def _normalize_ny(match: re.Match[str]) -> str:
    law = match.group("law").lower()
    section = match.group("section")
    sub = match.group("sub") or ""
    sub = re.sub(r"\s+", "", sub)
    return f"NY {law.title()} § {section}{sub}"


PATTERNS = [
    (
        re.compile(
            r"\b(?P<law>" + "|".join(NY_LAWS) + r")"
            r"[, ]+(?:section|§)\s*(?P<section>\d+(?:-[a-z])?)"
            r"(?P<sub>(?:\s*\([0-9a-zA-Z]+\))*)",
            re.IGNORECASE,
        ),
        _normalize_ny,
    ),
]
extract = regex_extractor(PATTERNS)
