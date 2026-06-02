"""South Dakota citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bSDCL \d+[A-Z]?-\d+[A-Z]?(?:-\d+[A-Z]?)?\b",
    r"\bSouth Dakota Codified Laws? \d+[A-Z]?-\d+[A-Z]?(?:-\d+[A-Z]?)?\b",
])
