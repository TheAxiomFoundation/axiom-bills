"""NY bill kind classifier.

NY legislative resolutions use distinctive title prefixes. Senate and
Assembly bills (S/A prefix) are nearly always substantive; resolutions
(J prefix for joint, K/E for concurrent/simple) are the ceremonial
bucket.
"""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind


TITLE_PATTERNS = compile_kind_patterns([
    # NY's "LEGISLATIVE RESOLUTION" prefix marks the entire ceremonial
    # class: commemorating, memorializing, congratulating, mourning,
    # honoring, proclaiming a day/week.
    (r"^legislative resolution", BillKind.CEREMONIAL),
    (r"^commemorating ", BillKind.CEREMONIAL),
    (r"^memorializing ", BillKind.CEREMONIAL),
    (r"^honoring (the (life|memory)|the role|new york)", BillKind.CEREMONIAL),
    (r"^congratulating ", BillKind.CEREMONIAL),
    (r"^mourning ", BillKind.CEREMONIAL),
    (r"^proclaiming .* (day|week|month) in", BillKind.CEREMONIAL),

    # Appropriations: NY uses budget bill series, but typical
    # title-line prefix is "Making appropriations".
    (r"^making appropriations", BillKind.APPROPRIATIONS),

    # Procedural rules resolutions.
    (r"^providing for the consideration", BillKind.PROCEDURAL),
    (r"^adopting the rules of the (senate|assembly)", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
