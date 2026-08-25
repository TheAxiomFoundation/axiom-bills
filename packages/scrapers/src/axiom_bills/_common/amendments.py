"""Federal amendment-instruction parser.

Bills typically don't contain rewritten sections — they contain
*amendment instructions* like "Section 213 is amended by striking '7.5
percent' and inserting '10 percent'". This module converts those
instructions into structured operations and applies them to current law.

Coverage in this first cut (the common 60–70% of federal amendments):

  * Single strike/insert:
      ``is amended by striking "X" and inserting "Y"``
  * Pure insert at end:
      ``is amended by adding at the end the following: "(z) ..."``
  * Full rewrite:
      ``is amended to read as follows: "..."``
  * Multi-edit blocks with numbered items:
      ``is amended-- (1) ...; (2) ...``

Out of scope for now (falls back to side-by-side display):
  * Conditional / cross-reference edits
  * Redesignations of subsections
  * Edits keyed to specific sub-elements via the bill text's own outline
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass
class Op:
    kind: str         # 'strike-insert' | 'add-end' | 'replace-all' | 'strike'
    needle: str = ""  # what to find (for strike-insert and strike)
    payload: str = "" # what to insert / append / replace with
    raw: str = ""     # the raw bill substring this came from


# Each pattern returns Op objects. Order matters — try more specific
# (multi-edit blocks) before falling through to single-edit fallbacks.

# GPO's plain-text bill renderer uses double-backticks `` to OPEN quoted
# inserts and double-apostrophes '' to CLOSE them. Each nested paragraph
# inside the insert opens with another ``, but the whole quoted block
# closes only with the final ''. So opening and closing delimiters are
# asymmetric — we can't use a single quote-char class for both, or the
# lazy content stops at the first nested paragraph's open ``.
#
# We also tolerate straight (") and curly (“ ”) quotes for non-GPO text.
_OPEN_Q  = r"(?:``|[\"“])"
_CLOSE_Q = r"(?:''|[\"”])"
_QUOTED = _OPEN_Q + r"(?P<{name}>.*?)" + _CLOSE_Q


def _quoted(name: str) -> str:
    return _QUOTED.format(name=name)


SINGLE_STRIKE_INSERT_RE = re.compile(
    r"by\s+striking\s+" + _quoted("needle") +
    r"\s+(?:and\s+inserting|and\s+inserting\s+in\s+lieu\s+thereof)\s+" + _quoted("payload"),
    re.IGNORECASE | re.DOTALL,
)

PURE_STRIKE_RE = re.compile(
    r"by\s+striking\s+" + _quoted("needle") + r"(?=\s*(?:[;,.]|$))",
    re.IGNORECASE | re.DOTALL,
)

ADD_AT_END_RE = re.compile(
    r"by\s+adding\s+at\s+the\s+end\s+(?:the\s+following[^:]*:\s*)?" + _quoted("payload"),
    re.IGNORECASE | re.DOTALL,
)

REPLACE_ALL_RE = re.compile(
    r"is\s+amended\s+to\s+read\s+as\s+follows[^:]*:\s*" + _quoted("payload"),
    re.IGNORECASE | re.DOTALL,
)

# Top-level multi-edit block: "is amended-- (1) by striking ...; (2) by ...; and (3) ..."
MULTI_EDIT_INTRO_RE = re.compile(
    r"is\s+amended\s*(?:[-—]+|\:)\s*\((?P<first>\d+|[a-z])\)",
    re.IGNORECASE,
)


def parse_amendments_for_citation(bill_text: str, citation: str) -> list[Op]:
    """Find the chunk of bill_text that talks about `citation` and parse it.

    Heuristic: locate the citation's raw appearance in the bill text,
    grab the surrounding 'is amended ...' clause (up to the next period
    that closes a top-level sentence), then parse with the patterns
    above.
    """
    if not bill_text:
        return []

    # Find a window of bill text around any mention of the citation,
    # in any of its raw forms. Use loose regex: 'Section 213', '26 USC 213',
    # 'section 213 of the Internal Revenue Code'.
    haystack_re = _build_citation_haystack_re(citation)
    if haystack_re is None:
        return []

    ops: list[Op] = []
    for window in _windows_around(bill_text, haystack_re):
        ops.extend(_parse_window(window))

    return _dedupe(ops)


def _windows_around(text: str, pattern: re.Pattern[str], radius: int = 6000) -> list[str]:
    """Capture enough text after the citation to include the entire
    quoted insertion. Federal amendments routinely run several thousand
    characters when the bill is adding new subsections wholesale, so we
    pick a deliberately generous radius — the regex itself stops at the
    closing `''`, so over-capturing is harmless.
    """
    out: list[str] = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + radius)
        out.append(text[start:end])
    return out


def _build_citation_haystack_re(citation: str) -> re.Pattern[str] | None:
    """Build a regex that matches the various ways a citation appears."""
    # Citation looks like "26 USC 213" or "26 USC 213(a)(1)".
    m = re.match(r"(\d+)\s+USC\s+(\d+[A-Z]?)((?:\([^)]+\))*)", citation)
    if not m:
        return None
    title, section, sub = m.groups()
    sub_re = re.escape(sub) if sub else ""
    pattern = (
        rf"\b(?:{title}\s+U\.?\s*S\.?\s*C\.?\s*(?:§\s*)?{section}{sub_re}"
        rf"|section\s+{section}{sub_re}\s+of\s+(?:the\s+)?(?:Internal Revenue Code|such Code|title {title}))"
    )
    return re.compile(pattern, re.IGNORECASE)


def _parse_window(window: str) -> list[Op]:
    ops: list[Op] = []

    for m in REPLACE_ALL_RE.finditer(window):
        ops.append(Op(kind="replace-all",
                      payload=_clean(m.group("payload")),
                      raw=m.group(0)))

    for m in SINGLE_STRIKE_INSERT_RE.finditer(window):
        ops.append(Op(kind="strike-insert",
                      needle=_clean(m.group("needle")),
                      payload=_clean(m.group("payload")),
                      raw=m.group(0)))

    for m in ADD_AT_END_RE.finditer(window):
        ops.append(Op(kind="add-end",
                      payload=_clean(m.group("payload")),
                      raw=m.group(0)))

    # Pure-strike runs only after strike-insert so a 'strike X and
    # insert Y' clause doesn't double-count as both ops.
    used_spans = []
    for op in ops:
        if op.kind == "strike-insert":
            idx = window.find(op.raw)
            if idx >= 0:
                used_spans.append((idx, idx + len(op.raw)))
    for m in PURE_STRIKE_RE.finditer(window):
        if any(s <= m.start() < e for s, e in used_spans):
            continue
        ops.append(Op(kind="strike",
                      needle=_clean(m.group("needle")),
                      raw=m.group(0)))

    return ops


def _clean(s: str) -> str:
    """Trim trailing punctuation/whitespace from a parsed needle/payload."""
    s = s.strip()
    # Strip trailing periods or semicolons that belong to bill grammar, not the quoted string.
    s = re.sub(r"[.;,\s]+$", "", s)
    return s


def _dedupe(ops: list[Op]) -> list[Op]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Op] = []
    for op in ops:
        key = (op.kind, op.needle, op.payload)
        if key in seen:
            continue
        seen.add(key)
        out.append(op)
    return out


def apply_ops(corpus_text: str, ops: list[Op]) -> tuple[str, list[Op], list[Op]]:
    """Apply parsed ops to corpus text.

    Returns (modified_text, applied_ops, unapplied_ops). An op is
    unapplied when its needle isn't found in the corpus body — which can
    happen when the bill quotes from an older version of the section, or
    when our quoted-string parser caught some surrounding bill prose by
    mistake.
    """
    if corpus_text is None:
        return corpus_text or "", [], ops
    text = corpus_text
    applied: list[Op] = []
    unapplied: list[Op] = []

    for op in ops:
        if op.kind == "replace-all":
            text = op.payload
            applied.append(op)
        elif op.kind == "strike-insert":
            if op.needle in text:
                text = text.replace(op.needle, op.payload, 1)
                applied.append(op)
            else:
                unapplied.append(op)
        elif op.kind == "strike":
            if op.needle in text:
                text = text.replace(op.needle, "", 1)
                applied.append(op)
            else:
                unapplied.append(op)
        elif op.kind == "add-end":
            text = text.rstrip() + "\n\n" + op.payload
            applied.append(op)
        else:
            unapplied.append(op)
    return text, applied, unapplied


# Federal legal-text hierarchy levels and their indentation. We classify
# by marker shape; cross-references like "subsection (a)" are protected
# upstream so they don't trigger a structural break.
_INDENT_UNIT = "  "

# Cross-reference patterns we DON'T want to treat as structural breaks.
#
# Shape we have to handle (real corpus + bill text examples):
#   subsection (a)                            single
#   subsections (b)(1), (b)(2), and (d)(1)(B) chained, mixed depths
#   section 152                               section number alone
#   section 152(e)                            section number + paren
#   section 7702B(b)                          alphanumeric section ID
#   subparagraph (A)(ii)                      chained inside ref
#
# Comma/and-chaining ("subsections (b)(1), (b)(2), and (d)") is only
# allowed after a ref that is itself parenthesized, or after a section
# NUMBER that already carries an attached paren ("section 151(b) and
# (c)"). A bare number followed by a comma and a paren must NOT chain:
# corpus renders a subsection as one flowing line, so
#
#     "...any deduction provided in section 199A, (4) the deduction..."
#
# is a cross-reference to §199A followed by a STRUCTURAL paragraph
# marker. Chaining there swallowed "(4)" as part of the reference, the
# marker vanished from the structure scan, and slice_subsection could
# not find the paragraph at all. Measured across 197 corpus sections:
# 11 such markers, every one of them eaten.
#
# A reference label is a short token — (b), (1), (12), (A), (ii), (VIII)
# — never prose. Matching `\([^)]+\)` instead let the shield treat an
# explanatory parenthetical as an attached reference: in
#
#   "section 152 (determined without regard to subsections (b)(1),
#    (b)(2), and (d)(1)(B) thereof)"
#
# the unbalanced "(determined … (b)" was consumed as if it were
# §152's subsection, which then hid the real list behind it and left
# "(b)(2)" and "(d)(1)(B)" exposed as false structural markers.
_REF_LABEL = r"\(\s*[0-9A-Za-z]{1,4}\s*\)"

_REF_HEAD = (
    r"\b(?:subsection|subsections|paragraph|paragraphs|subparagraph|subparagraphs"
    r"|clause|clauses|subclause|subclauses|section|sections|subdivision|subdivisions"
    r"|title|subtitle|chapter|part|item|items)\b"
)
# After a section NUMBER, a comma-joined chain must keep the same label
# class as the attached paren it continues. That is what separates
#
#   "section 1005c(a), (b), and (c) of title 7"   one ref, three subsecs
#   "section 170(p), (5) the deduction provided"  a ref, then paragraph (5)
#
# — letters continue letters, digits continue digits. Without the class
# check either the list tail leaks out as false structural markers or the
# real paragraph marker gets swallowed; there is no single comma rule
# that gets both right. The classes are spelled case-sensitively via
# inline (?-i:) because the pattern as a whole is IGNORECASE.
_LOW_LABEL = r"(?-i:\(\s*[a-z]{1,4}\s*\))"
_DIG_LABEL = r"\(\s*[0-9]{1,3}\s*\)"
_UPP_LABEL = r"(?-i:\(\s*[A-Z]{1,4}\s*\))"

# Section identifiers carry more than one optional letter. Title 42 runs
# to "1397jj" and "1396u-1"; corpus also renders some suffixes detached,
# as "section 1715 l (d)(3)(ii)(I)" for §1715l(d)(3)(ii)(I). Every form
# the shield cannot spell leaves the citation's own subdivision parens
# exposed to be read as structural markers — "1397jj(c)(2)" matched only
# as far as "1397j", so "(c)(2) of this title" became a false marker and
# answered requests for subsection (c).
#
# The detached form takes a single letter only: allowing several would
# let "section 152 determined..." swallow the following word.
_SECTION_ID_BODY = (
    r"\d+(?:[a-zA-Z]{1,3}|\s[a-zA-Z])?"
    r"(?:[-\u2010-\u2015]\d+[a-zA-Z]{0,3})?"
)
_SECTION_ID = r"\s+" + _SECTION_ID_BODY

# Citations also appear in bare U.S.C. form, with no "section" in front:
# "( 42 U.S.C. 300gg(b)(1)(A) )". Unshielded, that reference's own
# "(b)" reads as a subsection marker and truncates whichever subsection
# happens to contain the citation — it cost every paragraph after it in
# 42 USC 1397jj(c).
_USC_REF = (
    r"\b\d{1,2}\s*U\.?\s*S\.?\s*C\.?\s*(?:§+\s*)?"
    + _SECTION_ID_BODY + r"(?:\s*" + _REF_LABEL + r")*"
)


# Connector between chained refs: ", (b)", " and (c)", ", or (d)", and
# the Oxford form ", and (e)" — the last of which an earlier pattern
# missed, leaving the tail of every three-or-more-item list
# ("clauses (i), (iii), and (iv)") unshielded and free to be read as a
# structural break.
_CONNECTOR = r"(?:\s*,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+)"


def _same_class_chain(label: str) -> str:
    """One or more further refs of the same label class."""
    return r"(?:" + _CONNECTOR + label + r")+"


# The class is taken from the LAST attached paren, not the first:
# "section 1211(b)(1) or (2)" continues the paragraph (1), so "(2)" is
# part of the citation, whereas "section 170(p), (5)" switches class and
# so "(5)" is a structural marker. Each alternative demands a NON-EMPTY
# chain, with attached-only and bare-number as the final fallbacks —
# otherwise Python's leftmost-alternative matching would settle for
# "section 1211(b)" and leave "(1) or (2)" exposed.
_NUMBER_BRANCH = "|".join(
    [
        _SECTION_ID + r"(?:\s*" + _REF_LABEL + r")*\s*" + lbl
        + _same_class_chain(lbl)
        for lbl in (_LOW_LABEL, _DIG_LABEL, _UPP_LABEL)
    ]
    + [_SECTION_ID + r"(?:\s*" + _REF_LABEL + r")+"]   # attached, no chain
)

_PAREN_HEADED = r"\s*" + _REF_LABEL + r"(?:\s*" + _REF_LABEL + r")*"

# A paren-headed list keeps one class in its LEADING label throughout:
# "subsections (b)(1), (b)(2), and (d)(1)(B)" is letter-led all the way,
# "clauses (i), (iii), and (iv)" likewise. When the class switches the
# list has ended and a structural marker has begun —
#
#     "...the applicable requirements of subsection (a), (5) regulations
#      or other guidance to ensure that the wages taken into account..."
#
# — where "(5)" is paragraph (5) of the subsection being read, not a
# second reference. Note this keys off the FIRST label of each element,
# unlike the section-number branch which keys off the last attached one:
# there the elements are bare labels continuing a path, here they are
# whole paths in their own right.
_PAREN_HEADED_CLASSED = "|".join(
    [
        r"\s*" + lbl + r"(?:\s*" + _REF_LABEL + r")*"
        + r"(?:" + _CONNECTOR + lbl + r"(?:\s*" + _REF_LABEL + r")*)*"
        for lbl in (_LOW_LABEL, _DIG_LABEL, _UPP_LABEL)
    ]
    + [_PAREN_HEADED]
)

_PROTECTED_REF_RE = re.compile(
    r"(?:" + _USC_REF +                         # bare "42 U.S.C. 300gg(b)"
    r"|" + _REF_HEAD +
    r"(?:" + _NUMBER_BRANCH +                   # section number forms
    r"|" + _SECTION_ID +                        # bare number, no chaining
    r"|" + _PAREN_HEADED_CLASSED +              # paren-headed, same-class list
    r")"
    r")",
    re.IGNORECASE,
)

_MARKER_RE = re.compile(
    r"\((?:\d+|[A-Z]|[a-z]|[ivxlc]{2,}|[IVXLC]{2,})\)"
)

# Words that, immediately before a marker, signal a cross-reference rather
# than a structural unit. Kept short — broader heuristics live below.
# "and" and "or" are deliberately absent. They were here to catch the
# second half of "subsections (a) and (b)", but _PROTECTED_REF_RE now
# shields chained references itself, including the Oxford form. What was
# left was the false positive: statutory lists put a conjunction before
# their final item — "...under subsection (b); and (2) may promulgate
# regulations..." — so treating a preceding "and" as proof of a
# cross-reference discarded the last structural marker of most lists, and
# with it every marker the chain search needed afterwards.
_REF_WORDS = {
    "subsection", "subsections", "paragraph", "paragraphs",
    "subparagraph", "subparagraphs", "clause", "clauses",
    "subclause", "subclauses", "section", "sections",
    "subdivision", "subdivisions",
    "title", "subtitle", "chapter", "part", "item", "items",
    "of", "in", "under", "to", "see",
}


def _looks_titled(text_after: str) -> bool:
    """Is the text immediately after a marker formatted like a section title?

    Federal subsections almost always read `(c) Limitation on losses ...`
    — a brief title-cased heading after the marker. Clauses read
    `(i) the amount of personal casualty gains ...` — lowercase
    sentence continuation.

    Heuristic: first word after the marker starts with a capital letter
    AND is a "real" word (≥3 alphabetic chars, not just a one-letter
    article like 'A'). Single-cap first words on clause-style prose
    like 'The taxpayer …' would also pass; we accept those false
    positives as the lesser failure mode — over-tagging a clause as a
    subsection is rare and the slicer's chain-search will still bail
    out if the rest of the path doesn't navigate.
    """
    head = text_after.lstrip()
    if not head:
        return False
    # First whitespace-delimited word.
    first = head.split(maxsplit=1)[0]
    if len(first) < 3 or not first[0].isalpha():
        return False
    return first[0].isupper()


def _marker_depth(marker: str, prev_depth: int,
                  looks_titled: bool = False) -> int:
    """Return the legal-text hierarchy depth for a level marker.

    The federal pattern: subsection (a) → paragraph (1) → subparagraph
    (A) → clause (i)/(ii) → subclause (I)/(II).

    Single-character markers are ambiguous: `(i)` can be subsection-i
    or clause-i; `(I)` can be subparagraph-I or subclause-I. We
    disambiguate by checking whether the text immediately following
    the marker looks like a section heading (title-cased) vs
    mid-sentence prose. Subsection/subparagraph markers carry titles;
    clauses and subclauses don't.
    """
    inner = marker[1:-1]
    if inner.isdigit():
        return 1
    if len(inner) > 1:
        # Multi-char roman: clause (lower) or subclause (upper).
        return 3 if inner.islower() else 4
    if inner.islower():
        # Title heading → subsection. Mid-sentence → clause if we're
        # already deep, else default to subsection.
        if looks_titled:
            return 0
        return 3 if prev_depth >= 2 else 0
    if inner.isupper():
        # Subparagraphs almost always have titles; subclauses rarely.
        # Default to subparagraph unless we're already deep and this
        # marker reads as mid-sentence prose.
        if looks_titled:
            return 2
        return 4 if prev_depth >= 3 else 2
    return 0


# The roman-numeral letters are the one place a marker's label does not
# determine its level: "(i)" opens subsection i in one section and clause
# i in the next, "(v)" likewise, and "(I)" is either a subparagraph or a
# subclause. Guessing costs real slices either way, so the slicer takes
# both readings and lets the surrounding structure decide.
_ROMAN_LETTERS = frozenset("ivxlcdm")


def _candidate_depths(marker: str, prev_depth: int,
                      looks_titled: bool = False) -> tuple[int, ...]:
    """Plausible hierarchy depths for a marker, best guess first.

    Mirrors `_marker_depth` for the unambiguous labels — its first
    element is always what `_marker_depth` would return — but for the
    roman-numeral letters it returns both readings so the chain search
    can try each.
    """
    inner = marker[1:-1]
    if inner.isdigit():
        return (1,)
    if len(inner) > 1:
        return (3,) if inner.islower() else (4,)
    if inner.islower():
        if inner in _ROMAN_LETTERS:
            # Subsection first when the marker carries a heading or we
            # aren't yet deep enough for a clause; clause first otherwise.
            return (0, 3) if (looks_titled or prev_depth < 2) else (3, 0)
        return (0,) if (looks_titled or prev_depth < 2) else (3, 0)
    if inner.isupper():
        if inner.lower() in _ROMAN_LETTERS:
            return (2, 4) if (looks_titled or prev_depth < 3) else (4, 2)
        return (2,) if (looks_titled or prev_depth < 3) else (4, 2)
    return (0,)


_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(label: str) -> int | None:
    total = 0
    highest = 0
    for ch in reversed(label.lower()):
        value = _ROMAN_VALUES.get(ch)
        if value is None:
            return None
        total = total - value if value < highest else total + value
        highest = max(highest, value)
    return total or None


def _label_ordinal(label: str, depth: int) -> int | None:
    """Position of `label` within the sequence used at `depth`."""
    if depth == 1:                                  # paragraphs: 1, 2, 3
        return int(label) if label.isdigit() else None
    if depth in (0, 2):                             # subsections / subparagraphs
        if len(label) == 1 and label.isalpha():
            return ord(label.lower()) - ord("a") + 1
        return None
    return _roman_to_int(label)                     # clauses / subclauses


def _continues_sequence(prev_label: str | None, label: str, depth: int) -> bool:
    """Would `label` be the next item at `depth`?

    Immediate succession, not merely "later": a clause "(i)" appearing
    while subsection "(a)" is open is later than 'a' alphabetically, but
    it is not 'b', so it does not read as the next subsection.
    """
    n = _label_ordinal(label, depth)
    if n is None:
        return False
    if prev_label is None:
        return n == 1                               # opens the sequence
    prev = _label_ordinal(prev_label, depth)
    return prev is not None and n == prev + 1


def _resolve_depths(structural):
    """Pick one depth per marker, using label-sequence continuity.

    The roman letters are ambiguous by label alone, and picking wrong in
    either direction costs a boundary. Reading "(c)" after subsection
    "(b)" as a clause leaves subsection (b)'s slice running to the end of
    the section; reading a clause "(i)" inside a paragraph as a new
    subsection truncates that paragraph at its first clause. Sequence
    continuity separates them: "(c)" follows "(b)" at subsection level,
    while "(i)" opens a clause list and follows nothing at subsection
    level. Where neither reading fits, we keep the label-based guess.
    """
    last: dict[int, str] = {}
    resolved: list[int] = []

    def advance(state: dict[int, str], depth: int, lab: str) -> dict[int, str]:
        nxt = {d: v for d, v in state.items() if d <= depth}
        nxt[depth] = lab
        return nxt

    for idx, (depths, _start, _end, label) in enumerate(structural):
        # Where a reading continues a sequence, take it. Where none does,
        # take the DEEPEST reading: a marker that continues nothing is
        # more likely stray text than a new sibling, and treating it as a
        # sibling would close whatever span encloses it. A spurious "(d)"
        # between paragraphs (7) and (8) ended subsection (a) and lost
        # every paragraph after it.
        chosen = next((d for d in depths
                       if _continues_sequence(last.get(d), label, d)),
                      max(depths))

        # Continuity alone can be fooled: a stray "(c)" deep inside
        # subsection (b) does continue a, b, c at subsection level. Look
        # one marker ahead — reading it as a subsection strands the "(B)"
        # that follows, which was continuing (A) two levels down, whereas
        # the deeper reading leaves that sequence intact.
        if len(depths) > 1 and idx + 1 < len(structural):
            ahead_depths, _, _, ahead_label = structural[idx + 1]

            def keeps_the_thread(d: int) -> bool:
                state = advance(last, d, label)
                return any(_continues_sequence(state.get(a), ahead_label, a)
                           for a in ahead_depths)

            if not keeps_the_thread(chosen):
                better = next((d for d in depths
                               if d != chosen and keeps_the_thread(d)), None)
                if better is not None:
                    chosen = better

        resolved.append(chosen)
        last = advance(last, chosen, label)
    return resolved


def _is_cross_reference(text: str, pos: int) -> bool:
    """Backup heuristic: is the marker at `pos` a cross-reference?

    The placeholder pass handles obvious cases ("subsection (a)"); this
    catches what slips through — section-numbered refs and chain
    continuations like "(b)(1)" where the preceding context is itself a
    parenthetical.
    """
    if pos == 0:
        return False
    i = pos - 1
    # Skip whitespace, remembering whether there was any: it is the only
    # thing separating a chained reference from genuine nesting.
    saw_space = False
    while i >= 0 and text[i].isspace():
        saw_space = True
        i -= 1
    if i < 0:
        return False
    prev = text[i]
    # Sentence/clause terminator → structural.
    if prev in ".—–:;\n":
        return False
    # A closing paren immediately before means a chain continuation of an
    # earlier ref — "(b)(1)". With a space between, it is a subsection
    # opening its first paragraph: statutes that give no heading render
    # exactly "(d) (1) If the veteran is in need of...". Treating those
    # as cross-references discarded the paragraph and everything the
    # chain search needed after it.
    if prev == ")" and not saw_space:
        return True
    # Look at the last word/number in the preceding 40 chars.
    snippet = text[max(0, i - 40):i + 1]
    last_token = re.search(r"(\w+)\s*$", snippet)
    if last_token is None:
        return False
    word = last_token.group(1)
    if word.lower() in _REF_WORDS:
        return True
    # Section identifier like "7702B" or "152" — a number before a
    # parenthetical is a cross-ref, but only when it is ADJACENT to it.
    # Statutory text is full of numbers that merely precede a marker:
    # "93 Stat. 1133 (e) Administrative expenses", "after March 1983
    # (1) For any particular month", a footnote's "1" before "(1)".
    # Without the adjacency test each of those hid a real subsection.
    if re.fullmatch(r"\d+[A-Za-z]?", word) and not saw_space:
        return True
    return False


def _pretty_print_legal(text: str) -> str:
    """Indent legal text by hierarchy level.

    Two-stage protection of cross-references:
      1. The PROTECTED_REF_RE placeholder pass shields obvious refs.
      2. `_is_cross_reference` catches what slips through.
    Structural markers get a newline + two-space indent per level.
    """
    if not text:
        return ""

    refs: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        refs.append(m.group(0))
        return f"\x00{len(refs) - 1}\x00"

    shielded = _PROTECTED_REF_RE.sub(_stash, text)

    parts: list[str] = []
    cursor = 0
    prev_depth = -1
    emitted_any = False
    for m in _MARKER_RE.finditer(shielded):
        if _is_cross_reference(shielded, m.start()):
            continue
        between = shielded[cursor:m.start()]
        if between:
            parts.append(between.rstrip(" "))
        text_after = shielded[m.end():m.end() + 120]
        depth = _marker_depth(m.group(0), prev_depth, _looks_titled(text_after))
        if emitted_any:
            parts.append("\n" + _INDENT_UNIT * depth)
        parts.append(m.group(0))
        cursor = m.end()
        prev_depth = depth
        emitted_any = True
    if cursor < len(shielded):
        parts.append(shielded[cursor:])

    result = "".join(parts).lstrip()
    result = re.sub(r"\x00(\d+)\x00",
                    lambda mm: refs[int(mm.group(1))], result)
    return result


# Section identifiers are not just "213". Title 42 in particular is full
# of "1397aa", "1396u-1" and "300j-12", and corpus renders the separator
# as an EN DASH ("1396u\u20131"). The old pattern here allowed a single
# optional letter and no suffix at all, so every one of those citations
# failed to parse and slice_subsection returned None before it looked at
# any text — 223 of the fixture's 237 misses came from this alone.
_USC_SECTION_ID = r"\d+[a-zA-Z]{0,3}(?:[-\u2010-\u2015]\d+[a-zA-Z]{0,3})?"


def slice_subsection(section_body: str, citation: str) -> tuple[str | None, tuple[int, int] | None]:
    """Slice a subsection out of a parent section's body.

    Given a citation like '26 USC 213(d)(2)' and the body of §213, return
    just the text covered by `(d)(2)`. We use the same level-marker
    classifier as the pretty-printer to identify structural breakpoints,
    then walk the body to find the chunk that starts at the requested
    marker and ends at the next marker of equal or shallower depth.

    Returns (slice_text, (start_offset, end_offset)) on success, or
    (None, None) when the subsection can't be located. The offsets are
    against the original `section_body`, enabling stitch-back after
    applying ops.
    """
    if not section_body or not citation:
        return None, None

    # Extract the subsection path from the citation: '26 USC 213(d)(2)' → ['d','2']
    m = re.search(rf"USC\s+{_USC_SECTION_ID}((?:\([^)]+\))+)",
                  citation, re.IGNORECASE)
    if not m:
        return None, None
    levels = re.findall(r"\(([^)]+)\)", m.group(1))
    if not levels:
        return None, None

    # Walk the body, tracking position and depth, looking for the chain
    # `(d) ... (2)` opening structurally. Pretty-printer logic but
    # operating in offset space.
    refs: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        refs.append(m.group(0))
        return "\x00" * len(m.group(0))

    shielded = _PROTECTED_REF_RE.sub(_stash, section_body)

    # (candidate_depths, start, end, marker_text)
    structural: list[tuple[tuple[int, ...], int, int, str]] = []
    prev_depth = -1
    for mm in _MARKER_RE.finditer(shielded):
        if _is_cross_reference(shielded, mm.start()):
            continue
        text_after = shielded[mm.end():mm.end() + 120]
        depths = _candidate_depths(mm.group(0), prev_depth,
                                   _looks_titled(text_after))
        structural.append((depths, mm.start(), mm.end(), mm.group(0)[1:-1]))
        prev_depth = depths[0]

    if not structural:
        return None, None

    # Walk the marker chain with backtracking rather than a single pass.
    #
    # The old search committed to the first marker matching each level and
    # reset the whole chain whenever it met anything at or above the top
    # level's depth. One spurious structural marker — a "; and (2)" read as
    # a list continuation, a citation's parens exposed by a shield miss —
    # therefore discarded every later paragraph in the section. Trying each
    # candidate and backing out costs nothing on the common path and
    # survives a stray marker.
    #
    # Depth is used relatively (each level must sit deeper than its parent)
    # instead of being matched against a precomputed absolute depth per
    # citation level. Absolute matching demanded the classifier and the
    # citation agree exactly, and an off-by-one anywhere meant no slice.
    found = _descend_marker_chain(structural, levels, len(section_body),
                                  _resolve_depths(structural))
    if found is None:
        return None, None

    slice_start, slice_end = found
    return section_body[slice_start:slice_end], (slice_start, slice_end)


def _descend_marker_chain(structural, levels, body_len, resolved):
    """Find the span of `levels` (e.g. ['b', '6']) in a marker list.

    Returns (start, end) of the deepest level's text, or None.

    Run in two passes. The first reads every marker at its best-guess
    depth only. Just the sections where that fails get the second pass,
    which also allows the alternate reading of an ambiguous roman-letter
    marker.

    The ordering matters more than it looks. Allowing both readings at
    once makes "(i)" as a subsection match the first clause "(i)" that
    appears anywhere earlier in the section — a wrong slice, which is
    worse than no slice, since an amendment applied inside it edits a
    provision the bill never named. Trying the confident reading first
    keeps the ambiguity as a fallback for sections that genuinely need
    it rather than a licence to match anything.
    """
    n = len(structural)

    def search(strict: bool):
        def readings(depths, k):
            if strict:
                # A USC citation's levels ARE the hierarchy ladder:
                # first paren is a subsection, second a paragraph, third a
                # subparagraph, and so on. Requiring the marker to sit at
                # the level its position implies is what stops a clause
                # "(i)" buried in some paragraph from answering a request
                # for subsection (i).
                return depths[:1] if depths[0] == k else ()
            # Fallback: any reading, but the positional one first.
            return sorted(depths, key=lambda d: abs(d - k))

        def span_end(i: int, depth: int, limit: int) -> int:
            """Where the marker at `i`, read at `depth`, stops."""
            for j in range(i + 1, n):
                _depths, start, _, _ = structural[j]
                if start >= limit:
                    break
                # Close on the marker's RESOLVED depth. Taking the
                # shallowest reading truncated a paragraph at its first
                # clause; taking the deepest never closed a subsection
                # whose sibling happened to be a roman letter, so "(b)"
                # ran on through (c) and (d) to the end of the section.
                # Sequence continuity tells the two apart.
                if resolved[j] <= depth:
                    return start
            return limit

        def descend(k: int, lo: int, limit: int, min_depth: int):
            for j in range(lo, n):
                depths, start, _, label = structural[j]
                if start >= limit:
                    return None
                if label != levels[k]:
                    continue
                for depth in readings(depths, k):
                    if depth <= min_depth:
                        continue
                    end = span_end(j, depth, limit)
                    if k == len(levels) - 1:
                        return (start, end)
                    deeper = descend(k + 1, j + 1, end, depth)
                    if deeper is not None:
                        return deeper
            return None

        return descend(0, 0, body_len, -1)

    return search(strict=True) or search(strict=False)



def stitch_subsection(section_body: str, offsets: tuple[int, int], new_slice: str) -> str:
    """Replace `section_body[offsets[0]:offsets[1]]` with `new_slice`."""
    start, end = offsets
    return section_body[:start] + new_slice + section_body[end:]


def normalize_legal_text(text: str) -> str:
    """Strip GPO formatting artifacts and re-indent by legal hierarchy.

    axiom-corpus stores each subsection as a single flowing line. GPO
    plain text uses ``opens'' and `--` for em-dashes plus hard wraps at
    ~70 columns. Both forms get the same treatment here:

      1. Strip `` and '' delimiter artifacts.
      2. Convert `--` to `—`.
      3. Collapse all whitespace (including line wraps) within each
         source paragraph into single spaces.
      4. Re-introduce hierarchical line breaks + indent at each level
         marker, skipping cross-references.

    Both the corpus body and the applied bill text go through this
    function before diffing, so the diff reflects only legal changes.
    """
    if not text:
        return ""
    cleaned = text.replace("``", "").replace("''", "")
    cleaned = re.sub(r"\s*--\s*", "—", cleaned)
    paragraphs = re.split(r"\n\s*\n+", cleaned)
    out: list[str] = []
    for p in paragraphs:
        flat = re.sub(r"\s+", " ", p).strip()
        if flat:
            out.append(_pretty_print_legal(flat))
    return "\n\n".join(out)


def unified_diff(before: str, after: str, *, n_context: int = 3) -> list[dict]:
    """Return a structured diff for the frontend to render.

    Each entry is {kind: 'equal'|'add'|'remove'|'change', text: str}.
    We use difflib's SequenceMatcher and collapse to whole lines so the
    rendered diff reads naturally, not character-by-character.
    """
    before_lines = before.splitlines() if before else []
    after_lines = after.splitlines() if after else []
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.append({"kind": "equal", "text": "\n".join(before_lines[i1:i2])})
        elif tag == "delete":
            out.append({"kind": "remove", "text": "\n".join(before_lines[i1:i2])})
        elif tag == "insert":
            out.append({"kind": "add", "text": "\n".join(after_lines[j1:j2])})
        elif tag == "replace":
            out.append({"kind": "remove", "text": "\n".join(before_lines[i1:i2])})
            out.append({"kind": "add", "text": "\n".join(after_lines[j1:j2])})
    return out
