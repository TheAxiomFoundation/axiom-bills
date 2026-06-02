"""OR citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bORS\s+\d+(?:\.\d+)?\b",
    r"\bOregon Laws \d{4}, chapter \d+\b",
])
