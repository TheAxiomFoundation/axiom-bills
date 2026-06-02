"""Florida citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\b(?:s\.|section)\s*\d+(?:\.\d+)?(?:\([^)]+\))*\s*,?\s*F\.?S\.?\b",
    r"\bFlorida Statutes? \d+(?:\.\d+)?(?:\([^)]+\))*\b",
    r"\bchapter \d{4}-\d+, Laws of Florida\b",
])
