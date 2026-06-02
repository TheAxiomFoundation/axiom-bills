"""OH citation extractor."""
from __future__ import annotations

from axiom_bills._common.citations import regex_extractor

extract = regex_extractor([
    r"\bsection \d+(?:\.\d+)? of the Revised Code\b",
    r"\bsections? (?:\d+(?:\.\d+)?(?:, )?)+(?: and \d+(?:\.\d+)?)? of the Revised Code\b",
    r"\bR\.C\. \d+(?:\.\d+)?\b",
])
