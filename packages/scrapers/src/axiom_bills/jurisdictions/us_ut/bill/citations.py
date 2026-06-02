"""UT citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\b\d+[A-Z]?-\d+[A-Z]?-\d+\b",
    r"\bUtah Code (?:Section )?\d+[A-Z]?-\d+[A-Z]?-\d+\b",
])
