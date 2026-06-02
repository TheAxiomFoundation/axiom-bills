"""KS citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bK\.S\.A\. \d{1,3}-\d+[a-z]?\b",
    r"\bKansas Statutes Annotated \d{1,3}-\d+[a-z]?\b",
])
