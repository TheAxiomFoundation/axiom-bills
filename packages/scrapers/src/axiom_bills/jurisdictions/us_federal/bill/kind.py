"""Federal bill kind classifier.

Most of the signal is in the title; bill type and subjects refine the
edge cases. Order matters — match the most specific pattern first.

Examples we want to capture cleanly:
  PLACEHOLDER    "Reserved for the Speaker." (H.R.6, etc.)
  CEREMONIAL     "To designate the facility ... as the John X Post Office"
  CEREMONIAL     "Expressing the sense of the House that ..."
  CEREMONIAL     "Honoring the life of ..."
  APPROPRIATIONS "Making appropriations for the Department of Defense ..."
  PROCEDURAL     "Providing for consideration of H.R. 1234" (rules cmte)
  PROCEDURAL     "Electing Members to certain standing committees"
"""
from __future__ import annotations

from axiom_bills._common.kind import classify_by_title, compile_kind_patterns
from axiom_bills._common.models import BillKind


TITLE_PATTERNS = compile_kind_patterns([
    # Placeholder bill numbers reserved by leadership at the start of a
    # Congress. Titled "Reserved for the Speaker." or
    # "Reserved for the Minority Leader."
    (r"^reserved for the ", BillKind.PLACEHOLDER),

    # Appropriations — bill-text pattern is dependable.
    (r"^making appropriations", BillKind.APPROPRIATIONS),
    (r"continuing appropriations", BillKind.APPROPRIATIONS),

    # Ceremonial: post-office namings, sense-of-the-House, honoring,
    # commemorating, congratulating, mourning, recognizing.
    (r"^to designate.*post office", BillKind.CEREMONIAL),
    (r"^to name.*(post office|federal building|courthouse)", BillKind.CEREMONIAL),
    (r"^designating.*national.*(day|week|month)", BillKind.CEREMONIAL),
    (r"^expressing the (sense|gratitude|sympathy|condolences)", BillKind.CEREMONIAL),
    (r"^honoring (the (life|memory|service)|.*for)", BillKind.CEREMONIAL),
    (r"^recognizing (the (role|significance|importance)|.*for)", BillKind.CEREMONIAL),
    (r"^commemorating ", BillKind.CEREMONIAL),
    (r"^congratulating ", BillKind.CEREMONIAL),
    (r"^celebrating ", BillKind.CEREMONIAL),
    (r"^mourning ", BillKind.CEREMONIAL),

    # Procedural / chamber-rules resolutions.
    (r"^providing for consideration of ", BillKind.PROCEDURAL),
    (r"^electing (members|the speaker)", BillKind.PROCEDURAL),
    (r"^amending the rules of the (house|senate)", BillKind.PROCEDURAL),
    (r"^establishing the .* committee", BillKind.PROCEDURAL),
    (r"^authorizing the use of .* for ceremonies", BillKind.PROCEDURAL),
])


def classify(title: str | None) -> BillKind:
    return classify_by_title(title, TITLE_PATTERNS)
