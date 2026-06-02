"""WI citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bWis\. Stat\. § ?\d+(?:\.\d+)?\b",
    r"\bsection \d+(?:\.\d+)? of the statutes\b",
])
