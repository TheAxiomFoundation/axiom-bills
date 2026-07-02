"""Extract a bill's statutory effective date from its text.

Variants used to stamp `effective_from` with the bill's latest status
action date — but the date a rule change takes effect is written in the
bill ("shall apply to taxable years beginning after December 31,
2026"), and that's the date the patched rulespec version must carry.

Deliberately conservative: return a date only when the bill states one
explicit, unambiguous calendar-anchored effective date. Enactment-
relative dates ("on the date of the enactment") can't be resolved until
signing, and bills with several different effective dates would need
per-section attribution — both return None and the caller falls back
to the status-action date, as before.
"""
from __future__ import annotations

import re
from datetime import date, timedelta


_MONTHS = {m: i + 1 for i, m in enumerate([
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
])}

_DATE = r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})"

# "shall apply to taxable years beginning after December 31, 2026"
# (also: plan years, calendar years, fiscal years, quarters) — the rule
# takes effect the day AFTER the anchor date.
_APPLIES_AFTER_RE = re.compile(
    r"shall\s+apply\s+to\s+(?:taxable|plan|calendar|fiscal)\s+"
    r"(?:years?|quarters?)\s+beginning\s+after\s+" + _DATE,
    re.IGNORECASE,
)

# "shall take effect on January 1, 2027" / "effective on January 1, 2027"
_TAKES_EFFECT_ON_RE = re.compile(
    r"(?:shall\s+take\s+effect\s+on|effective\s+(?:on|as\s+of))\s+" + _DATE,
    re.IGNORECASE,
)


def _to_date(m: re.Match[str]) -> date | None:
    month = _MONTHS.get(m.group("month").lower())
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def extract_effective_date(bill_text: str) -> date | None:
    """One unambiguous statutory effective date, or None."""
    if not bill_text:
        return None
    found: set[date] = set()
    for m in _APPLIES_AFTER_RE.finditer(bill_text):
        d = _to_date(m)
        if d:
            found.add(d + timedelta(days=1))
    for m in _TAKES_EFFECT_ON_RE.finditer(bill_text):
        d = _to_date(m)
        if d:
            found.add(d)
    if len(found) == 1:
        return found.pop()
    return None
