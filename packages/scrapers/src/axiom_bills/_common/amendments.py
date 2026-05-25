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
_PROTECTED_REF_RE = re.compile(
    r"\b(?:subsection|subsections|paragraph|paragraphs|subparagraph|subparagraphs"
    r"|clause|clauses|subclause|subclauses|section|sections|subdivision|subdivisions"
    r"|title|subtitle|chapter|part|item|items)\b"
    r"(?:\s+(?:\d+[A-Za-z]?|\([^)]+\)))"          # first ref: number or first paren
    r"(?:\s*\([^)]+\))*"                          # chained parens
    r"(?:\s*(?:,|and|or)\s*\([^)]+\)"             # comma/and-separated refs
    r"(?:\s*\([^)]+\))*)*",
    re.IGNORECASE,
)

_MARKER_RE = re.compile(
    r"\((?:\d+|[A-Z]|[a-z]|[ivxlc]{2,}|[IVXLC]{2,})\)"
)

# Words that, immediately before a marker, signal a cross-reference rather
# than a structural unit. Kept short — broader heuristics live below.
_REF_WORDS = {
    "subsection", "subsections", "paragraph", "paragraphs",
    "subparagraph", "subparagraphs", "clause", "clauses",
    "subclause", "subclauses", "section", "sections",
    "subdivision", "subdivisions",
    "title", "subtitle", "chapter", "part", "item", "items",
    "of", "and", "or", "in", "under", "to", "see",
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
    # Skip whitespace.
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0:
        return False
    prev = text[i]
    # Sentence/clause terminator → structural.
    if prev in ".—–:;\n":
        return False
    # Closing paren → chain continuation of an earlier ref → cross-ref.
    if prev == ")":
        return True
    # Look at the last word/number in the preceding 40 chars.
    snippet = text[max(0, i - 40):i + 1]
    last_token = re.search(r"(\w+)\s*$", snippet)
    if last_token is None:
        return False
    word = last_token.group(1)
    if word.lower() in _REF_WORDS:
        return True
    # Section identifier like "7702B" or "152" — numbers (optionally
    # followed by a letter) before a parenthetical are cross-refs.
    if re.fullmatch(r"\d+[A-Za-z]?", word):
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
    m = re.search(r"USC\s+\d+[A-Z]?((?:\([^)]+\))+)", citation, re.IGNORECASE)
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

    structural: list[tuple[int, int, int, str]] = []  # (depth, start, end, marker_text)
    prev_depth = -1
    for mm in _MARKER_RE.finditer(shielded):
        if _is_cross_reference(shielded, mm.start()):
            continue
        text_after = shielded[mm.end():mm.end() + 120]
        depth = _marker_depth(mm.group(0), prev_depth, _looks_titled(text_after))
        structural.append((depth, mm.start(), mm.end(), mm.group(0)[1:-1]))
        prev_depth = depth

    if not structural:
        return None, None

    # Find the chain. We need to descend depth-by-depth, matching
    # marker_text against each level.
    target_levels = levels
    target_depths = [_marker_depth(f"({t})", target_levels and 2 or 0)
                     for t in target_levels]
    # Adjust depths via the same prev-state biasing that classifier uses:
    # walk the target_levels and compute their depths progressively.
    target_depths = []
    prev = -1
    for t in target_levels:
        d = _marker_depth(f"({t})", prev)
        target_depths.append(d)
        prev = d

    # Search for the structural marker matching the *last* level at the
    # correct depth and whose ancestors (in order) match too.
    idx = 0
    chain_starts: list[int] = []  # offsets of each successful chain step
    while idx < len(structural):
        d, start, end, marker = structural[idx]
        if d == target_depths[len(chain_starts)] and marker == target_levels[len(chain_starts)]:
            chain_starts.append(start)
            if len(chain_starts) == len(target_levels):
                break
            idx += 1
        else:
            # Sibling or unrelated; if we've already started a chain and
            # see a depth ≤ first level, reset the chain.
            if chain_starts and d <= target_depths[0]:
                chain_starts = []
            idx += 1

    if len(chain_starts) != len(target_levels):
        return None, None

    # Start at the *deepest* matched marker — for `(c)(2)` we want
    # just the `(2)` content, not everything from `(c)` onward.
    slice_start = chain_starts[-1]
    # End = the next structural marker that's a sibling-or-shallower of
    # the deepest level we matched. Depth of the deepest target level
    # gives the right stop condition: (d)(2) ends at the next ≤-depth-1
    # marker, which catches (d)(3) (a sibling paragraph).
    target_depth = target_depths[-1]
    slice_end = len(section_body)
    for d, start, _, _ in structural:
        if start > chain_starts[-1] and d <= target_depth:
            slice_end = start
            break

    return section_body[slice_start:slice_end], (slice_start, slice_end)


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
