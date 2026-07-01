"""Structured amendment-block parser AND applier.

Replaces the citation-window scanner in ``amendments.py``. Federal bills
follow a consistent grammar:

    Section <X> of the <Act> (<title> U.S.C. <section>) is amended—
        (1) [in <scope-qualifier>,] by <verb> <operand1> [and <verb2> <operand2>];
        (2) by <verb> <operand>;
        ...
        (N) in <inner scope>—
                (A) by <verb> ...;
                (B) by <verb> ...;

The pipeline this module produces:

    bill_text → list[AmendmentBlock] → for each: corpus fetch → apply →
    diff. Each block is one amendment with one target; each Op inside
    knows its precise scope (block target + any narrowing prefix).

Design choices:

* Target-first: the parser does not extract citations from arbitrary
  bill prose. Citations come only from amendment block headers. This
  fixes the duplicate-tab bug (`16 USC 1533` + `16 USC 1533(a)` both
  showing up as separate sections for the same amendment) by
  construction.

* Scope-aware: "in paragraph (1), by striking X and inserting Y" emits
  an Op with target = block_target + (1), not just block_target. The
  applier then narrows its substring replacement to that paragraph's
  slice rather than the whole subsection.

* Verb kinds: strike-insert, strike, add-end, insert-after, amend-to-read,
  repeal, redesignate. Each is a concrete corpus-text manipulation.

* Failures are first-class. When we can't parse an amendment block (or
  a leaf operation inside one) we record it on the block's
  ``parse_warnings`` list with the raw text. The frontend surfaces
  these so a human reviewer can see what we missed instead of having
  the bill silently appear "no diff detected."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ────────────────────────────────────────────────────────────────────
#  Data model
# ────────────────────────────────────────────────────────────────────

OpKind = str  # 'strike-insert' | 'strike' | 'add-end' | 'insert-after'
              # | 'amend-to-read' | 'repeal' | 'redesignate' | 'unknown'


@dataclass
class Op:
    kind: OpKind
    target: str                     # normalized citation, e.g. '16 USC 1533(a)(1)'
    needle: str = ""
    payload: str = ""
    anchor: str = ""                # for insert-after: the text we insert after
    redesignate_to: str = ""        # for redesignate
    raw: str = ""                   # the verbatim bill substring this came from


@dataclass
class AmendmentBlock:
    target: str                     # base target citation
    operations: list[Op] = field(default_factory=list)
    raw: str = ""
    parse_warnings: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────
#  Lexer helpers — quotes
# ────────────────────────────────────────────────────────────────────

_OPEN_Q  = r"(?:``|[\"“])"
_CLOSE_Q = r"(?:''|[\"”])"
QUOTED = _OPEN_Q + r"(?P<q>.*?)" + _CLOSE_Q


def _take_quoted(s: str) -> tuple[str, int] | None:
    m = re.match(QUOTED, s, re.DOTALL)
    if m is None:
        return None
    return m.group("q"), m.end()


def _norm_ws(s: str) -> str:
    """Collapse all whitespace runs (including newlines + indents) to a
    single space, and strip. Used everywhere we need to match a quoted
    bill needle against corpus text — GPO bill quotes wrap at ~70 cols
    with 8-space indent, while corpus stores body text as one flowing
    line per subsection. Without normalization the substring search
    fails on real bills like the LIZARD Act.
    """
    return re.sub(r"\s+", " ", s).strip()


def _norm_find(haystack: str, needle: str) -> int:
    """Find `needle` in `haystack` ignoring whitespace differences.

    Returns the start offset in the *original* haystack, or -1 if not
    found. Works by building a parallel mapping: for each character in
    a whitespace-normalized form of haystack, record what original
    offset it corresponds to.
    """
    if not needle:
        return -1
    needle_norm = _norm_ws(needle)
    if not needle_norm:
        return -1

    # Build the normalized form of haystack and a parallel index map.
    norm_chars: list[str] = []
    index_map: list[int] = []
    prev_ws = True   # treat the start as if preceded by whitespace so we
                     # don't emit a leading space
    for i, ch in enumerate(haystack):
        if ch.isspace():
            if prev_ws:
                continue
            norm_chars.append(" ")
            index_map.append(i)
            prev_ws = True
        else:
            norm_chars.append(ch)
            index_map.append(i)
            prev_ws = False
    norm_text = "".join(norm_chars).rstrip()

    pos = norm_text.find(needle_norm)
    if pos < 0:
        return -1
    return index_map[pos]


def _norm_replace(haystack: str, needle: str, payload: str) -> tuple[str, bool]:
    """Whitespace-tolerant single-occurrence replace.

    Find `needle` in `haystack` via `_norm_find`, then locate the
    corresponding end offset by counting normalized characters off the
    same index map. Returns (new_haystack, True) on success or
    (haystack, False) on miss.
    """
    if not needle:
        return haystack, False
    start = _norm_find(haystack, needle)
    if start < 0:
        return haystack, False
    # Determine end offset by walking forward through whitespace-
    # collapsed chars until we've matched len(needle_norm) of them.
    needle_norm = _norm_ws(needle)
    matched = 0
    end = start
    prev_ws = False if not haystack[start].isspace() else True
    for j in range(start, len(haystack)):
        ch = haystack[j]
        if ch.isspace():
            if prev_ws:
                continue
            norm_ch = " "
            prev_ws = True
        else:
            norm_ch = ch
            prev_ws = False
        if matched < len(needle_norm) and norm_ch == needle_norm[matched]:
            matched += 1
            end = j + 1
            if matched == len(needle_norm):
                break
        else:
            # mismatch mid-run — shouldn't happen if _norm_find said yes
            return haystack, False
    return haystack[:start] + payload + haystack[end:], True


# ────────────────────────────────────────────────────────────────────
#  Citation utilities
# ────────────────────────────────────────────────────────────────────

# Common federal act-name → USC title map. Inferred from the bill's
# "of the <Act>" phrasing when there's no explicit U.S.C. parenthetical.
# Expanded based on a drift survey across 800 federal bills; covers the
# top unresolved act names. House Rules and similar non-USC sources are
# intentionally absent — they can't be mapped to corpus.
ACT_TO_TITLE: dict[str, str] = {
    "internal revenue code":            "26",
    "social security act":              "42",
    "food and nutrition act":           "7",
    "affordable care act":              "42",
    "patient protection and affordable care act": "42",
    "endangered species act":           "16",
    "fair labor standards act":         "29",
    "americans with disabilities act":  "42",
    "public health service act":        "42",
    "higher education act":             "20",
    "immigration and nationality act":  "8",
    "tariff act":                       "19",
    "communications act":               "47",
    "housing and community development act": "42",
    "fair credit reporting act":        "15",
    "electronic fund transfer act":     "15",
    "energy independence and security act": "42",
    "infrastructure investment and jobs act": "23",
    "intermodal surface transportation efficiency act": "23",
    "rural electrification act":        "7",
    "civil rights act":                 "42",
    "protecting access to medicare act": "42",
    "water infrastructure improvements for the nation act": "33",
    "food security act":                "16",
    "farm security and rural investment act": "7",
}

# "Section 1533(a) of the Endangered Species Act of 1973 (16 U.S.C. 1533(a)) is amended"
#
# Section identifiers can carry hyphenated suffixes (300j-12, 285l-3,
# 300hh-14) common in Title 42 health-related statutes. The trailing
# optional " note" handles bills like "(42 U.S.C. 300j-12 note)" which
# point at a session-law note rather than the codified section.
_USC_PAREN_RE = re.compile(
    r"\(\s*(?P<title>\d{1,2})\s*U\.?\s*S\.?\s*C\.?\s*"
    r"(?:Sec\.?\s*|§\s*)?"   # optional "Sec." prefix as in "(6 U.S.C. Sec. 279)"
    r"(?P<sect>\d+[a-zA-Z]{0,3}(?:-\d+[a-zA-Z]{0,3})?)"
    r"(?P<sub>(?:\s*\([^)]+\))*)"
    r"(?:\s+note)?(?:\s+et\s+seq\.?)?\s*\)",
    re.IGNORECASE,
)

# "Section X of title N, United States Code, is amended" — direct USC
# reference without a parenthetical. Common when the bill amends a
# codified statute that has no popularly-named act (e.g. Title 5 civil
# service, Title 10 armed forces, Title 49 transportation).
_TITLE_USC_DIRECT_RE = re.compile(
    r"of\s+title\s+(?P<title>\d{1,2})\s*,\s*United\s+States\s+Code",
    re.IGNORECASE,
)

# Fallback when there's no USC parenthetical or direct title reference:
# pull the act name. Tokens can be:
#   * Capitalized words ("Water", "Infrastructure")
#   * Initials with a trailing period ("M.", "S.") — for personal-name
#     acts like "James M. Inhofe National Defense Authorization Act"
#   * Lowercase connectors (for, of, the, and, in, on, to, a)
_ACT_RE = re.compile(
    r"\bof\s+the\s+(?P<act>"
    r"(?:[A-Z][a-zA-Z]*\.?"
        r"|(?:for|of|the|and|in|on|to|a)"
    r")(?:\s+(?:[A-Z][a-zA-Z]*\.?"
        r"|(?:for|of|the|and|in|on|to|a)"
    r"))*\s+(?:Act|Code))"
    r"(?:\s+of\s+\d{4})?"
    r"(?:\s+for\s+Fiscal\s+Year\s+\d{4})?",
)


def _normalize_subscripts(raw: str) -> str:
    """`(a) (1) (B)` → `(a)(1)(B)`."""
    if not raw:
        return ""
    return re.sub(r"\s*\(\s*", "(", re.sub(r"\s*\)\s*", ")", raw))


# "of such title" / "of such Code" — chain-reference to the previously-
# resolved title in the same bill. Common after the first block has
# established the title via a (T U.S.C. M) parenthetical.
_CHAIN_REF_RE = re.compile(
    r"of\s+such\s+(?:title|Code)",
    re.IGNORECASE,
)

# Patterns that identify references to non-USC document sets, so we can
# tag them honestly rather than reporting "unresolved citation".
_DC_CODE_RE = re.compile(r"D\.?C\.?\s+Official\s+Code", re.IGNORECASE)
_HOUSE_RULE_RE = re.compile(r"Rule\s+\w+\s+of\s+the\s+Rules\s+of\s+the\s+House", re.IGNORECASE)
_HOUSE_RESOLUTION_RE = re.compile(r"House\s+Resolution\s+\d+", re.IGNORECASE)
_PUBLIC_LAW_RE = re.compile(r"Public\s+Law\s+\d+[-–]\d+", re.IGNORECASE)


def _classify_non_usc(header_text: str, sect: str) -> str | None:
    """Pin a useful category onto an otherwise unresolved block.

    Returns a marker like `dccode:1-206.02` so downstream consumers
    show the right framing ("D.C. Code amendment — not diffable
    against axiom-corpus") rather than a generic parse failure.
    """
    if _DC_CODE_RE.search(header_text):
        m = re.search(r"sec\.\s*([\w\-.]+)", header_text, re.IGNORECASE)
        return f"dccode:{m.group(1)}" if m else "dccode:?"
    if _HOUSE_RULE_RE.search(header_text):
        return "houserule"
    if _HOUSE_RESOLUTION_RE.search(header_text):
        return "houseres"
    if _PUBLIC_LAW_RE.search(header_text):
        m = _PUBLIC_LAW_RE.search(header_text)
        return f"publiclaw:{m.group(0).replace('Public Law ', 'PL')}"
    # Bare "Section X is amended" with no context — we know there's a
    # section number but not its title. Mark as unscoped so the UI
    # can show it as "amends an unidentified federal section."
    if sect:
        return f"unscoped:{sect}"
    return None


# Whole-act amendments: "The <Act> is amended by adding at the end the
# following new section:". The bill is adding a brand-new section,
# nothing to diff against. Detect and mark.
_WHOLE_ACT_AMEND_RE = re.compile(
    r"(?P<header>"
    r"The\s+(?P<act>[A-Z][^.\n]{5,150}?(?:Act|Code))"
    r"(?:[^.\n]*?\((?P<title>\d{1,2})\s*U\.?\s*S\.?\s*C\.?[^)]*\))?"
    r"[^.\n]*?)"
    r"\s+is\s+amended\s+by\s+adding\s+at\s+the\s+end\s+the\s+following"
    r"\s+new\s+section\s*:",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_target(header_text: str, section_with_subs: str,
                    context_title: str | None = None,
                    chain_title: str | None = None) -> str | None:
    """Resolve a block header to a normalized USC citation.

    Priority order:
      1. The USC parenthetical *closest to* "is amended" (rightmost).
      2. A "title N, United States Code" direct reference — bills
         amending uncodified titles (10, 40, 49, 54) often use this
         form instead of a parenthetical.
      3. An "of the <Act>" fallback mapping the act name to a title.
      4. "of such title" / "of such Code" → use `chain_title`, the
         title resolved by the most recent previous block in the bill.
      5. A bill-level `context_title` (e.g. "Amendment of 1986 Code"
         establishes IRC for the whole bill).
    """
    matches = list(_USC_PAREN_RE.finditer(header_text))
    if matches:
        m = matches[-1]   # the parenthetical closest to "is amended"
        title = m.group("title")
        sect = m.group("sect")
        sub = _normalize_subscripts(m.group("sub") or "")
        return f"{title} USC {sect}{sub}"

    m = _TITLE_USC_DIRECT_RE.search(header_text)
    if m:
        return f"{m.group('title')} USC {section_with_subs}"

    m = _ACT_RE.search(header_text)
    if m:
        # Normalize whitespace — GPO line wraps inject newlines into
        # the captured act name, so direct `key in act` lookups miss.
        act = re.sub(r"\s+", " ", m.group("act")).lower().strip()
        for key, title in ACT_TO_TITLE.items():
            if key in act:
                return f"{title} USC {section_with_subs}"

    if chain_title and _CHAIN_REF_RE.search(header_text):
        return f"{chain_title} USC {section_with_subs}"

    # The header names an Act we couldn't map (e.g. "Section 1 of the
    # Act of July 31, 1947" with an et-seq parenthetical we also missed).
    # Falling through to the bill-level context title fabricated a
    # confident wrong citation ("26 USC 1") — worse than admitting the
    # target is unresolved. "such Act" chain references are exempt: they
    # refer to whatever the context established.
    if re.search(r"\bAct\b", header_text) and \
            not re.search(r"\bsuch\s+Act\b", header_text):
        return None

    if context_title:
        return f"{context_title} USC {section_with_subs}"
    return None


# Bills often establish a single act context at the top — H.R.7024
# has a "(b) Amendment of 1986 Code" subsection saying "the reference
# shall be considered to be made to ... the Internal Revenue Code of
# 1986." Subsequent "Section X is amended" headers inherit that
# title. Detect such context and carry it forward.

_IRC_CONTEXT_RE = re.compile(
    r"(?:Amendment\s+of\s+(?:1986\s+Code|the\s+Internal\s+Revenue\s+Code)"
    r"|Internal\s+Revenue\s+Code\s+of\s+1986)",
    re.IGNORECASE,
)

_ACT_CONTEXT_RE = re.compile(
    r"(?:amendment(?:s)?\s+to\s+|amending\s+|amend(?:ment)?\s+of\s+)"
    r"(?:the\s+)?(?P<act>internal\s+revenue\s+code|social\s+security\s+act"
    r"|food\s+and\s+nutrition\s+act|endangered\s+species\s+act)",
    re.IGNORECASE,
)


def _scan_context_title(text_before_block: str,
                        full_text: str | None = None) -> str | None:
    """Find a context-establishing phrase. Prefer pre-block matches but
    fall back to anything in the whole bill — many short bills say
    "of such Code" in their first amendment block without having
    introduced the code first, but mention it later (or in the bill's
    long title at the very top).
    """
    # First try the pre-block prose (most specific).
    if _IRC_CONTEXT_RE.search(text_before_block):
        return "26"
    matches = list(_ACT_CONTEXT_RE.finditer(text_before_block))
    if matches:
        act = re.sub(r"\s+", " ", matches[-1].group("act")).lower().strip()
        for key, title in ACT_TO_TITLE.items():
            if key in act:
                return title

    # Fall back to scanning the full bill for any code/act mention.
    if full_text is not None:
        if _IRC_CONTEXT_RE.search(full_text):
            return "26"
        matches = list(_ACT_CONTEXT_RE.finditer(full_text))
        if matches:
            act = re.sub(r"\s+", " ", matches[0].group("act")).lower().strip()
            for key, title in ACT_TO_TITLE.items():
                if key in act:
                    return title
    return None


def _narrow_target(base: str, scope_kind: str | None, scope_label: str | None) -> str:
    """Append a scope qualifier to a base citation.

    base="26 USC 213(a)", scope_kind="paragraph", scope_label="1"
        → "26 USC 213(a)(1)"
    """
    if scope_label is None:
        return base
    return f"{base}({scope_label})"


# ────────────────────────────────────────────────────────────────────
#  Block-header detection
# ────────────────────────────────────────────────────────────────────

# Matches the start of an amendment block. Captures:
#   sect    — the section identifier as written ("1533", "1533(a)", "213")
#   header  — the entire pre-"is amended" prefix, for target resolution
#
# `Section`/`SECTION` is case-sensitive: real amendment headers begin
# with capital S. Lowercase "section X" inside purpose-sentence prose
# should be ignored — otherwise the regex's `.{0,200}?` lazy match
# happily swallows up to the next real amendment header and lands the
# wrong USC parenthetical as the target.

_SEP_RE = (
    r"(?P<sep>"
    r"\s*(?:—|--)"
    r"|\s+to\s+read\s+as\s+follows\s*:"
    r"|\s+(?=by\b)"
    r")"
)

# Bare "Section X" header. Section identifier matches plain digits
# with optional trailing letter and optional hyphenated suffix
# (`300j-12`-style). Up to 3 trailing letters cover Title 42 health
# statutes like `300hh-14`.
_BLOCK_HEADER_RE = re.compile(
    r"(?P<header>"
    r"(?-i:Section|SECTION)\s+"
    r"(?P<sect>\d+[a-zA-Z]{0,3}(?:-\d+[a-zA-Z]{0,3})?(?:\([^)]+\))*)"
    # Tempered gap: must not bridge across another "Section N" start.
    # Without this, the bill's own enumerator ("SECTION 1. EXTENSION OF
    # ...") swallowed the real header ("Section 48(c)(1)(E) of the
    # Internal Revenue Code ... is amended") and the block was
    # attributed to section 1 of whatever title context resolved.
    r"(?:(?!(?-i:Section|SECTION)\s+\d).){0,200}?"
    r")"
    r"\s+is\s+amended"
    + _SEP_RE,
    re.IGNORECASE | re.DOTALL,
)

# Prefixed header: "Subsection (X) of section Y", or
# "Paragraph (P) of subsection (S) of section Y", etc. Captures up to
# two levels of "of <level> (X)" prefix before the section keyword.
_LEVEL = r"(?-i:Subsection|Paragraph|Subparagraph|Clause|Subclause)"
_LEVEL_LC = r"(?-i:subsection|paragraph|subparagraph|clause|subclause)"

_PREFIXED_BLOCK_HEADER_RE = re.compile(
    r"(?P<header>"
    + _LEVEL + r"\s+\((?P<l1>[^)]+)\)\s+of\s+"
    + r"(?:" + _LEVEL_LC + r"\s+\((?P<l2>[^)]+)\)\s+of\s+)?"
    + r"(?:" + _LEVEL_LC + r"\s+\((?P<l3>[^)]+)\)\s+of\s+)?"
    + r"(?-i:section|Section|SECTION)\s+"
    + r"(?P<sect>\d+[a-zA-Z]{0,3}(?:-\d+[a-zA-Z]{0,3})?(?:\([^)]+\))*)"
    # Same tempered gap as _BLOCK_HEADER_RE — never bridge a "Section N".
    + r"(?:(?!(?-i:Section|SECTION)\s+\d).){0,200}?"
    + r")"
    + r"\s+is\s+amended"
    + _SEP_RE,
    re.IGNORECASE | re.DOTALL,
)

# When the entire bill section is "by adding at the end of <Act> the
# following new section:" — rarer; we handle it but with lower priority.
# (Out of scope for Phase 1; surfaced as unparsed.)


# ────────────────────────────────────────────────────────────────────
#  Verb-phrase patterns inside a numbered item
# ────────────────────────────────────────────────────────────────────

_STRIKE_INSERT_RE = re.compile(
    r"by\s+striking\s+" + QUOTED.replace("?P<q>", "?P<needle>")
    + r"\s+and\s+inserting(?:\s+in\s+lieu\s+thereof)?\s+"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

_STRIKE_RE = re.compile(
    r"by\s+striking\s+" + QUOTED.replace("?P<q>", "?P<needle>")
    + r"(?!\s+and\s+inserting)",
    re.IGNORECASE | re.DOTALL,
)

_ADD_END_RE = re.compile(
    # "at the end" with optional "the" — bills sometimes write "at end".
    r"by\s+adding\s+at\s+(?:the\s+)?end(?:\s+of\s+(?P<addend_scope>[^,]+?))?"
    r"\s+(?:the\s+following[^:]*:\s*)?"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

_INSERT_AFTER_RE = re.compile(
    r"by\s+inserting\s+after\s+" + QUOTED.replace("?P<q>", "?P<anchor>")
    + r"\s+the\s+following(?:\s+new[^:]*)?:\s*"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

# Payload-first variant: "by inserting ``X'' after ``Y''" — common when
# the insertion is a brief inline string rather than a multi-paragraph
# block.
_INSERT_AFTER_FLIPPED_RE = re.compile(
    r"by\s+inserting\s+"
    + QUOTED.replace("?P<q>", "?P<payload>")
    + r"\s+after\s+"
    + QUOTED.replace("?P<q>", "?P<anchor>"),
    re.IGNORECASE | re.DOTALL,
)

# Structural insert-after: anchor is a marker like "subsection (b)"
# instead of a quoted phrase. Common pattern for adding new
# subsections/paragraphs/subparagraphs in sequence.
_INSERT_AFTER_STRUCT_RE = re.compile(
    r"by\s+inserting\s+after\s+"
    r"(?P<anchor_level>subsection|paragraph|subparagraph|clause|subclause)\s+"
    r"\((?P<anchor_label>[^)]+)\)"
    r"\s+the\s+following(?:\s+new[^:]*)?:\s*"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

# "by inserting ``X'' before ``Y''" — the before-anchor sibling of
# insert-after. Common when adding a qualifier to a list.
_INSERT_BEFORE_RE = re.compile(
    r"by\s+inserting\s+"
    + QUOTED.replace("?P<q>", "?P<payload>")
    + r"\s+before\s+"
    + QUOTED.replace("?P<q>", "?P<anchor>"),
    re.IGNORECASE | re.DOTALL,
)

# "by striking the period at the end [of paragraph (N)] and inserting"
# — replaces trailing punctuation. The optional "of paragraph (N)"
# narrows the op target.
_STRIKE_PERIOD_INSERT_RE = re.compile(
    r"by\s+striking\s+the\s+period"
    r"(?:\s+at\s+the\s+end)?"
    r"(?:\s+of\s+(?P<scope_level>subsection|paragraph|subparagraph|clause|subclause)"
    r"\s+\((?P<scope_label>[^)]+)\))?"
    r"\s+and\s+inserting\s+"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

# "by inserting before the period at the end [of paragraph (N)] ``X''"
# — adds text just before trailing punctuation, with optional scope.
_INSERT_BEFORE_PUNCT_RE = re.compile(
    r"by\s+inserting\s+before\s+the\s+(?P<punct>period|semicolon|comma)"
    r"(?:\s+at\s+the\s+end)?"
    r"(?:\s+of\s+(?P<scope_level>subsection|paragraph|subparagraph|clause|subclause)"
    r"\s+\((?P<scope_label>[^)]+)\))?"
    r"\s+"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

# "by adding ``and'' at the end" / "by adding ``or'' at the end" — adds
# a literal conjunction. Treated as add-end with the quoted payload.
_ADD_LITERAL_END_RE = re.compile(
    r"by\s+adding\s+"
    + QUOTED.replace("?P<q>", "?P<payload>")
    + r"\s+at\s+the\s+end",
    re.IGNORECASE | re.DOTALL,
)

# Multi-element structural strike: "by striking clauses (ii), (iii),
# and (iv)" or "by striking paragraphs (3) and (4)". Each element is a
# separate repeal of (label) at the same level.
_STRIKE_MULTI_STRUCT_RE = re.compile(
    r"by\s+striking\s+"
    r"(?P<level>subsections?|paragraphs?|subparagraphs?|clauses?|subclauses?)\s+"
    r"(?P<labels>\([^)]+\)(?:\s*(?:,|and|or|,\s*and)\s*\([^)]+\))+)",
    re.IGNORECASE,
)

_AMEND_TO_READ_RE = re.compile(
    r"by\s+amending\s+(?P<scope>[a-z][a-z ]+\([^)]+\)(?:\([^)]+\))*)"
    r"\s+to\s+read\s+as\s+follows\s*:\s*"
    + QUOTED.replace("?P<q>", "?P<payload>"),
    re.IGNORECASE | re.DOTALL,
)

_REPEAL_RE = re.compile(
    r"by\s+repealing\s+(?P<scope>[a-z][a-z ]+\([^)]+\)(?:\([^)]+\))*)",
    re.IGNORECASE,
)

_REDESIGNATE_RE = re.compile(
    r"by\s+redesignating\s+(?P<from>[a-z][a-z ]+\([^)]+\)(?:\([^)]+\))*)"
    r"\s+as\s+(?P<to>[a-z][a-z ]+\([^)]+\)(?:\([^)]+\))*)",
    re.IGNORECASE,
)

# "by striking paragraph (7)" / "by striking subsection (b)" — strikes a
# whole structural element rather than a literal text. Treated as a
# repeal of that scope.
_STRIKE_STRUCTURAL_RE = re.compile(
    r"by\s+striking\s+"
    r"(?P<level>subsection|paragraph|subparagraph|clause|subclause)\s+"
    r"\((?P<label>[^)]+)\)",
    re.IGNORECASE,
)

# Scope qualifier prefix: "in paragraph (1)," / "in subsection (b)," etc.
_SCOPE_PREFIX_RE = re.compile(
    r"^\s*in\s+(?P<level>subsection|paragraph|subparagraph|clause|subclause)\s+"
    r"\((?P<label>[^)]+)\)\s*,?\s*",
    re.IGNORECASE,
)

# Non-scoping prefixes we just skip past without changing target:
#   "in the heading, by striking X" — the strike applies to the heading
#     text of the block's target; functionally just strikes the phrase
#   "in the matter preceding paragraph (N), by ..." — same: the strike
#     applies to the intro prose before paragraph (N)
# We treat both as "no narrowing" — the verbatim phrase match still
# locates the text correctly via _norm_find substring search.
_NON_NARROWING_PREFIX_RE = re.compile(
    r"^\s*in\s+the\s+(?:heading|matter\s+preceding[^,]*)\s*,?\s*",
    re.IGNORECASE,
)

_LEVEL_TO_DEPTH = {
    "subsection":   0,
    "paragraph":    1,
    "subparagraph": 2,
    "clause":       3,
    "subclause":    4,
}


# ────────────────────────────────────────────────────────────────────
#  Numbered-item splitting
# ────────────────────────────────────────────────────────────────────

# Numbered items inside a block use `(N)` markers at the start of a
# line (after indentation). We split on the FIRST matched indentation
# only — deeper indents belong to nested items inside the current one.
_NUMBERED_ITEM_START_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\((?P<num>\d+|[A-Z])\)\s+",
)


def _split_numbered_items(body: str) -> list[str]:
    """Return the textual content of each `(N)` item at the FIRST
    matched indentation level.

    Federal bills nest items by indentation:
        (1) in subsection (b)--
            (A) by striking X and inserting Y;
            (B) by adding Z at the end.

    At the (1) block level, (A) and (B) are nested children, not
    siblings of (1). Splitting on every `(N)` marker without regard
    to indentation produces three top-level items when there should
    be one. We pick the first match's indent as the canonical
    block-level indent and only emit items that share it.
    """
    matches = list(_NUMBERED_ITEM_START_RE.finditer(body))
    if not matches:
        return []
    first_indent = len(matches[0].group("indent"))
    top_level = [m for m in matches if len(m.group("indent")) == first_indent]
    items = []
    for i, m in enumerate(top_level):
        start = m.end()
        end = top_level[i + 1].start() if i + 1 < len(top_level) else len(body)
        items.append(body[start:end].strip())
    return items


# ────────────────────────────────────────────────────────────────────
#  Item parsing
# ────────────────────────────────────────────────────────────────────

def _peel_scope(item_text: str, base_target: str) -> tuple[str, str]:
    """Pull off any leading "in <level> (X)," scope qualifier.

    Also peels non-narrowing prefixes like "in the heading," or "in the
    matter preceding paragraph (N)," which don't change the target —
    the verb's phrase match locates the right text on its own.
    """
    m = _SCOPE_PREFIX_RE.match(item_text)
    if m:
        label = m.group("label").strip()
        narrowed = _narrow_target(base_target, m.group("level"), label)
        return narrowed, item_text[m.end():]
    m = _NON_NARROWING_PREFIX_RE.match(item_text)
    if m:
        return base_target, item_text[m.end():]
    return base_target, item_text


def _parse_verbs(text: str, target: str, *, warnings: list[str]) -> list[Op]:
    """Parse one or more verb phrases out of a leaf item.

    Multiple verbs can be chained with "and": "by striking X and
    inserting Y and by adding at the end Z".
    """
    ops: list[Op] = []
    cursor = 0
    raw_full = text
    progressed = True
    safety = 0
    while progressed and cursor < len(text) and safety < 12:
        safety += 1
        progressed = False
        sub = text[cursor:]

        m = _STRIKE_INSERT_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="strike-insert",
                target=target,
                needle=m.group("needle"),
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _ADD_END_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="add-end",
                target=target,
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _INSERT_AFTER_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="insert-after",
                target=target,
                anchor=m.group("anchor"),
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _INSERT_AFTER_FLIPPED_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="insert-after",
                target=target,
                anchor=m.group("anchor"),
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _INSERT_BEFORE_RE.search(sub)
        if m and m.start() < 8:
            # Insert payload before anchor = strike `anchor` and insert
            # `payload + anchor` so the diff shows the addition.
            ops.append(Op(
                kind="strike-insert",
                target=target,
                needle=m.group("anchor"),
                payload=m.group("payload") + " " + m.group("anchor"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _INSERT_AFTER_STRUCT_RE.search(sub)
        if m and m.start() < 8:
            # The anchor is a structural marker — use the literal "(X)"
            # text as the anchor for substring search. Body text
            # typically contains "(X) ...heading..." matching that.
            ops.append(Op(
                kind="insert-after",
                target=target,
                anchor=f"({m.group('anchor_label')})",
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _STRIKE_PERIOD_INSERT_RE.search(sub)
        if m and m.start() < 8:
            # Narrow target via optional "of paragraph (N)" qualifier.
            op_target = target
            if m.group("scope_label"):
                op_target = _narrow_target(target, None, m.group("scope_label"))
            ops.append(Op(
                kind="strike-insert",
                target=op_target,
                needle=".",
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _INSERT_BEFORE_PUNCT_RE.search(sub)
        if m and m.start() < 8:
            punct = m.group("punct").lower()
            anchor_char = {"period": ".", "semicolon": ";", "comma": ","}[punct]
            op_target = target
            if m.group("scope_label"):
                op_target = _narrow_target(target, None, m.group("scope_label"))
            ops.append(Op(
                kind="strike-insert",
                target=op_target,
                needle=anchor_char,
                payload=m.group("payload") + anchor_char,
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _ADD_LITERAL_END_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="add-end",
                target=target,
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _STRIKE_MULTI_STRUCT_RE.search(sub)
        if m and m.start() < 8:
            labels = re.findall(r"\(([^)]+)\)", m.group("labels"))
            for label in labels:
                ops.append(Op(
                    kind="repeal",
                    target=_narrow_target(target, None, label),
                    raw=m.group(0),
                ))
            cursor += m.end()
            progressed = True
            continue

        m = _AMEND_TO_READ_RE.search(sub)
        if m and m.start() < 8:
            scope_label = m.group("scope")
            # Resolve the scope phrase to a citation suffix.
            sub_m = re.search(r"\(([^)]+)\)", scope_label)
            sub_t = target
            if sub_m:
                sub_t = _narrow_target(target, None, sub_m.group(1))
            ops.append(Op(
                kind="amend-to-read",
                target=sub_t,
                payload=m.group("payload"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _STRIKE_STRUCTURAL_RE.search(sub)
        if m and m.start() < 8:
            label = m.group("label")
            ops.append(Op(
                kind="repeal",
                target=_narrow_target(target, None, label),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _STRIKE_RE.search(sub)
        if m and m.start() < 8:
            ops.append(Op(
                kind="strike",
                target=target,
                needle=m.group("needle"),
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        m = _REPEAL_RE.search(sub)
        if m and m.start() < 8:
            scope_label = m.group("scope")
            sub_m = re.search(r"\(([^)]+)\)", scope_label)
            sub_t = _narrow_target(target, None, sub_m.group(1)) if sub_m else target
            ops.append(Op(kind="repeal", target=sub_t, raw=m.group(0)))
            cursor += m.end()
            progressed = True
            continue

        m = _REDESIGNATE_RE.search(sub)
        if m and m.start() < 8:
            from_m = re.search(r"\(([^)]+)\)", m.group("from"))
            to_m = re.search(r"\(([^)]+)\)", m.group("to"))
            from_label = from_m.group(1) if from_m else m.group("from")
            to_label = to_m.group(1) if to_m else m.group("to")
            ops.append(Op(
                kind="redesignate",
                target=_narrow_target(target, None, from_label),
                redesignate_to=to_label,
                raw=m.group(0),
            ))
            cursor += m.end()
            progressed = True
            continue

        # Skip past " and " between verbs.
        skip = re.match(r"\s*(?:;|,)?\s*and\s+", sub, re.IGNORECASE)
        if skip:
            cursor += skip.end()
            progressed = True
            continue
        skip = re.match(r"\s*(?:;|,|\.)\s*", sub)
        if skip and skip.end() > 0:
            cursor += skip.end()
            progressed = True
            continue

    if not ops:
        warnings.append(raw_full[:200])
    return ops


def _parse_item(item_text: str, base_target: str,
                warnings: list[str]) -> list[Op]:
    """Parse a single `(N)` item, recursing into nested sub-items if present."""
    narrowed_target, rest = _peel_scope(item_text, base_target)

    # If the item ends with a colon/dash followed by sub-items (A)/(B)/...,
    # recurse. Otherwise treat as a leaf and parse verbs directly.
    nested_starts = list(_NUMBERED_ITEM_START_RE.finditer(rest))
    if nested_starts and nested_starts[0].group("num").isalpha():
        # Recursive: the prefix before sub-items might itself be a scope
        # qualifier we just peeled, or it might be empty (when the
        # outer item is just a wrapper). Parse each sub-item with the
        # narrowed target.
        ops: list[Op] = []
        for sub_item in _split_numbered_items(rest):
            ops.extend(_parse_item(sub_item, narrowed_target, warnings))
        return ops
    return _parse_verbs(rest, narrowed_target, warnings=warnings)


# ────────────────────────────────────────────────────────────────────
#  Block parsing
# ────────────────────────────────────────────────────────────────────

def _find_block_end(text: str, start: int) -> int:
    """Return the offset where this amendment block ends.

    Block ends at the next "Section X ... is amended" header, the next
    "SEC. N." top-level bill-section marker, or end of text.
    """
    # Section header for a new amendment block
    next_hdr = _BLOCK_HEADER_RE.search(text, start)
    # Top-level bill section header
    next_sec = re.search(r"\n\s*SEC(?:TION)?\.\s+\d+\.", text[start:])
    candidates = []
    if next_hdr:
        candidates.append(next_hdr.start())
    if next_sec:
        candidates.append(start + next_sec.start())
    if not candidates:
        return len(text)
    return min(candidates)


def _gather_headers(bill_text: str):
    """Yield (match, target_section_with_subs) for every block header in
    bill_text, from both bare ("Section X is amended") and prefixed
    ("Subsection (Y) of section X is amended") patterns.

    Also emits "whole-act amendment" pseudo-blocks for cases like
    "The Public Health Service Act is amended by adding at the end the
    following new section:" — these are flagged for the UI but won't
    have a corpus row to diff against (the act, as a whole, isn't a
    corpus citation; only its sections are).
    """
    seen_starts: set[int] = set()

    for m in _WHOLE_ACT_AMEND_RE.finditer(bill_text):
        # Synthesize a section identifier from the act and (optional) title.
        title = m.group("title")
        if title:
            sect = f"wholeact-title{title}"
        else:
            sect = "wholeact"
        yield m, sect
        seen_starts.add(m.start())

    # Prefixed first — its match starts BEFORE the bare "Section" keyword,
    # so by registering its position we suppress the bare regex's overlap.
    for m in _PREFIXED_BLOCK_HEADER_RE.finditer(bill_text):
        sect = _normalize_subscripts(m.group("sect"))
        # Append subscripts in the order: section + l3 + l2 + l1.
        # English nesting reads deepest-first; in the citation, the
        # deepest level lands LAST.
        for level in (m.group("l3"), m.group("l2"), m.group("l1")):
            if level:
                sect = sect + f"({level})"
        yield m, sect
        seen_starts.add(m.start())
        # Also record the inner "Section X" position so the bare regex
        # doesn't double-emit. Find the actual "section" keyword inside.
        inner = re.search(r"(?-i:section|Section|SECTION)\s+\d", m.group(0))
        if inner:
            seen_starts.add(m.start() + inner.start())

    for m in _BLOCK_HEADER_RE.finditer(bill_text):
        if m.start() in seen_starts:
            continue
        # Check if this bare match is inside a prefixed match we've
        # already emitted — if the start is within 80 chars after a
        # seen start, skip it.
        if any(0 < (m.start() - s) < 80 for s in seen_starts):
            continue
        # Skip if inside a whole-act amendment region.
        if any(0 < (m.start() - s) < 300 for s in seen_starts):
            continue
        yield m, _normalize_subscripts(m.group("sect"))


def parse_bill_amendments(bill_text: str) -> list[AmendmentBlock]:
    """Top-level parser: return one AmendmentBlock per "Section X is amended" header."""
    if not bill_text:
        return []
    blocks: list[AmendmentBlock] = []
    chain_title: str | None = None
    for m, sect in _gather_headers(bill_text):
        header = m.group("header")
        # Whole-act blocks short-circuit target resolution: they don't
        # touch a specific section, so there's no corpus row to look up.
        if sect.startswith("wholeact"):
            blocks.append(AmendmentBlock(
                target=f"wholeact:{sect.replace('wholeact-', '').replace('wholeact','?')}",
                raw=bill_text[m.start():_find_block_end(bill_text, m.end())],
                parse_warnings=[],
            ))
            continue
        context_title = _scan_context_title(bill_text[:m.start()], bill_text)
        target = _resolve_target(header, sect,
                                 context_title=context_title,
                                 chain_title=chain_title)
        if target and not target.startswith("unresolved"):
            mt = re.match(r"(\d+)\s+USC\b", target)
            if mt:
                chain_title = mt.group(1)
        else:
            target = _classify_non_usc(header, sect) or target
        if target is None:
            # Couldn't resolve the citation. Record as a fully-unparsed block.
            blocks.append(AmendmentBlock(
                target=f"unresolved:{sect}",
                raw=bill_text[m.start():_find_block_end(bill_text, m.end())],
                parse_warnings=["could not resolve citation from header"],
            ))
            continue

        end = _find_block_end(bill_text, m.end())
        body = bill_text[m.end():end]
        warnings: list[str] = []

        # If the header itself says "is amended to read as follows: ___",
        # the whole block is a single amend-to-read op.
        atr = _AMEND_TO_READ_RE.search(bill_text[m.start():end])
        if "to read as follows" in m.group(0).lower():
            quoted = _take_quoted(body.lstrip(": \n"))
            if quoted:
                payload, _ = quoted
                blocks.append(AmendmentBlock(
                    target=target,
                    operations=[Op(kind="amend-to-read", target=target,
                                   payload=payload, raw=body[:200])],
                    raw=bill_text[m.start():end],
                ))
                continue
            warnings.append("amend-to-read without parseable payload")

        ops: list[Op] = []
        body_stripped = body.lstrip()
        # If the body starts with "by <verb>", the entire block is a
        # single-verb amendment. Don't split on numbered items —
        # quoted payloads contain `(1)`, `(2)` markers that would
        # otherwise be mistaken for block-level items.
        if re.match(r"by\s+(striking|adding|inserting|amending|repealing|redesignating)",
                    body_stripped, re.IGNORECASE):
            ops.extend(_parse_verbs(body, target, warnings=warnings))
        else:
            items = _split_numbered_items(body)
            if items:
                for it in items:
                    ops.extend(_parse_item(it, target, warnings))
            else:
                ops.extend(_parse_verbs(body, target, warnings=warnings))

        blocks.append(AmendmentBlock(
            target=target,
            operations=ops,
            raw=bill_text[m.start():end],
            parse_warnings=warnings,
        ))
    return blocks


# ────────────────────────────────────────────────────────────────────
#  Applier — scope-aware substring manipulation on corpus text
# ────────────────────────────────────────────────────────────────────

# Imported lazily from .amendments so we don't get a cycle if someone
# imports just this module.
def _slice_for(target: str, body: str) -> tuple[str, tuple[int, int]] | None:
    from .amendments import slice_subsection
    sl, off = slice_subsection(body, target)
    if sl and off:
        return sl, off
    return None


def apply_op(op: Op, body: str, block_target: str) -> tuple[str, bool, str]:
    """Apply a single Op to ``body`` (the slice corresponding to ``block_target``).

    Returns (new_body, applied, note). `note` carries a short reason
    when applied=False so the UI can show "couldn't apply this op
    because needle not found" rather than dropping silently.
    """
    # If op.target is deeper than block_target, slice the sub-scope out
    # of body, apply, stitch back.
    sub_offsets: tuple[int, int] | None = None
    work_text = body
    if op.target != block_target:
        sliced = _slice_for(op.target, body)
        if sliced is None:
            return body, False, f"couldn't locate {op.target} within {block_target}"
        work_text, sub_offsets = sliced

    if op.kind == "strike-insert":
        new_work, ok = _norm_replace(work_text, op.needle, op.payload)
        if not ok:
            return body, False, f"needle not found: {_norm_ws(op.needle)[:60]!r}"
    elif op.kind == "strike":
        new_work, ok = _norm_replace(work_text, op.needle, "")
        if not ok:
            return body, False, f"needle not found: {_norm_ws(op.needle)[:60]!r}"
    elif op.kind == "add-end":
        new_work = work_text.rstrip() + "\n\n" + op.payload
    elif op.kind == "insert-after":
        # whitespace-tolerant anchor find, then insert payload right after.
        start = _norm_find(work_text, op.anchor)
        if start < 0:
            return body, False, (
                f"insert-after anchor not found: {_norm_ws(op.anchor)[:60]!r}"
            )
        # Find end of the anchor by re-running the replace machinery
        # against a sentinel.
        sentinel = "\x00ANCHOR\x00"
        replaced, _ = _norm_replace(work_text, op.anchor, sentinel)
        new_work = replaced.replace(sentinel, op.anchor + " " + op.payload)
    elif op.kind == "amend-to-read":
        new_work = op.payload
    elif op.kind == "repeal":
        new_work = "[REPEALED]"
    elif op.kind == "redesignate":
        # Redesignation rewrites the marker label in place. We don't
        # currently rewrite the body — record as applied=False with a
        # note so the user knows the bill renumbered something but the
        # diff text doesn't reflect that yet.
        return body, False, (
            f"redesignate {op.target} → ({op.redesignate_to}) — "
            f"recognized but not yet applied"
        )
    else:
        return body, False, f"unknown op kind: {op.kind}"

    if sub_offsets is None:
        return new_work, True, ""
    start, end = sub_offsets
    return body[:start] + new_work + body[end:], True, ""


@dataclass
class AppliedBlock:
    target: str
    block: AmendmentBlock
    before_text: str | None
    after_text: str | None
    applied: list[Op] = field(default_factory=list)
    unapplied: list[tuple[Op, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def apply_block(block: AmendmentBlock, corpus_body: str,
                slice_for_target) -> AppliedBlock:
    """Apply an AmendmentBlock to a corpus body.

    `slice_for_target` is injected so this module doesn't import
    `amendments.py` directly (avoids cycles in some call paths). Caller
    passes a function `(body, citation) -> (slice_text, (start, end))`.
    """
    out = AppliedBlock(
        target=block.target,
        block=block,
        before_text=None,
        after_text=None,
    )

    # Slice the block's target out of the corpus body.
    sliced = slice_for_target(corpus_body, block.target)
    if sliced and sliced[0]:
        block_slice, block_offsets = sliced
        out.before_text = block_slice
    else:
        # Block target is exactly the corpus row, OR slicer couldn't
        # locate. Use the full body as our working scope.
        block_slice = corpus_body
        block_offsets = (0, len(corpus_body))
        out.before_text = corpus_body

    current = block_slice
    for op in block.operations:
        new_current, ok, note = apply_op(op, current, block.target)
        if ok:
            out.applied.append(op)
            current = new_current
        else:
            out.unapplied.append((op, note))
            out.notes.append(note)

    out.after_text = current
    return out
