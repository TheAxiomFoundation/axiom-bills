"""Idaho citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bIdaho Code (?:Section )?\d{1,2}-\d+[A-Za-z]?\b",
    r"\bSection \d{1,2}-\d+[A-Za-z]?, Idaho Code\b",
])
