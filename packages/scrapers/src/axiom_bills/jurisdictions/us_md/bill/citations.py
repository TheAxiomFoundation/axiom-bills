"""Maryland citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bAnnotated Code of Maryland\b",
    r"\b[A-Z][A-Za-z ]+ Article,?\s*§+\s*[\w.-]+",
    r"\b§+\s*[\w.-]+\s+of\s+the\s+[A-Z][A-Za-z ]+ Article\b",
])
