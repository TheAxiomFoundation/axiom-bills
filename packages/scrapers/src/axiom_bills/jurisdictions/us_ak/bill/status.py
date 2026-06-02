"""AK action-text -> normalized_status patterns.

Source: Alaska Legislature BASIS bill action rows.
"""
from __future__ import annotations

from axiom_bills._common.models import NormalizedStatus
from axiom_bills._common.status import compile_patterns

PATTERNS = compile_patterns([
    (r"law w/o gov signature|chapter \d+ sla|effective date\(s\) of law", NormalizedStatus.ENACTED),
    (r"signed by governor|governor signed", NormalizedStatus.SIGNED),
    (r"transmitted to governor|transmit to gov|awaiting transmittal to gov|due back from governor", NormalizedStatus.ENROLLED),
    (r"veto", NormalizedStatus.VETOED),
    (r"failed|died|not taken up|indefinitely postponed", NormalizedStatus.FAILED),
    (r"\bpassed\b|passage|transmitted to \([hs]\)|concur am of", NormalizedStatus.PASSED_CHAMBER),
    (
        r"read the first time|referral|referred|committee|heard|held|moved .* out of committee|"
        r"rpt|rules to .*calendar|advanced to third reading|read the second time|cs adopted|version:|"
        r"read the third time|before .* in second reading|deadline for all ams|please note time change|"
        r"hearing rescheduled|engrossment waived|rescind action|"
        r"minutes|meeting canceled|bill hearing canceled|public testimony|testimony|fn\d|"
        r"\bdp:|\bdnp:|\bnr:|\bam:|am \d+ to am \d+ adopted|prime sponsor|c?o?sponsor|"
        r"manifest error|title change|changes .*title|"
        r"am no|effective date\(s\) adopted|return to second|automatically in third|"
        r"moved to bottom|concur message|"
        r"^[\(\)hs ]+(finance|state affairs|judiciary|health|labor|education|community|resources|transportation|"
        r"fisheries|military|rules|fin|sta|jud|hss|l&c|edc|cra|res|tra|fsh|mlv)(,|\b|\s+at)|"
        r"^\([hs]\) [A-Z][A-Z .,'&-]+(?:, [A-Z][A-Z .,'&-]+)*$",
        NormalizedStatus.IN_COMMITTEE,
    ),
    (r"prefile|introduced|sponsor\(s\)", NormalizedStatus.INTRODUCED),
])
