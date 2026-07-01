"""Rank bill version labels by legislative stage.

`bill_versions` has no reliable date column, and label strings sort
badly alphabetically ("Engrossed in House" < "Introduced in House"), so
"pick the newest text" was label-alphabet luck. The iterative encoding
story depends on always encoding against the latest stage: enrolled
beats engrossed beats introduced.

Keyword-based so it covers federal Congress.gov labels ("Engrossed in
Senate", "Enrolled Bill", "Public Law") and the common state phrasings.
Unknown labels rank 0 — better an explicit floor than a guess.
"""
from __future__ import annotations


_STAGE_KEYWORDS: list[tuple[str, int]] = [
    ("public law", 90),
    ("enacted", 85),
    ("chaptered", 85),
    ("enrolled", 80),
    ("engrossed", 60),
    ("passed", 55),
    ("reported", 40),
    ("placed on calendar", 30),
    ("amended", 25),
    ("referred", 20),
    ("introduced", 10),
    ("as introduced", 10),
]


def stage_rank(label: str | None) -> int:
    """Higher = later in the legislative process. Unknown → 0."""
    if not label:
        return 0
    lowered = label.lower()
    best = 0
    for keyword, rank in _STAGE_KEYWORDS:
        if keyword in lowered and rank > best:
            best = rank
    return best
