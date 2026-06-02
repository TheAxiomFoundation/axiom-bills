"""Delaware citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\btitle\s+\d+\s+of\s+the\s+delaware\s+code\b",
    r"\b\d+\s+del\.\s*c\.\s*§+\s*[\w.-]+",
    r"\b§+\s*[\w.-]+\s+of\s+title\s+\d+\b",
])
