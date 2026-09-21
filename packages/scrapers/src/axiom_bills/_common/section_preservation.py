"""Keep a stored diff section when the corpus stops answering for it.

``precompute-diffs`` rebuilds every section from the live corpus. CI
starts from an empty SQLite, so a corpus miss has nothing local to fall
back on, and the following ``sync-supabase`` would overwrite a section
that an earlier run had matched to real statutory text with "no corpus
text". A miss is a real empty answer, not an outage: ``corpus_client``
raises ``CorpusUnavailable`` when the service errors, and nothing in
``precompute-diffs`` catches it, so an outage stops the run. What a
miss does mean is that the corpus serves neither the path nor any
ancestor today. That set can shrink: axiom-corpus moved US serving to
RuleSpec-cited scopes in July 2026.

This module is the pure merge. It never touches a section the fresh
run matched, and it marks everything it keeps as stale. What it keeps
depends on whether the stored diff still answers the instruction:

* the fresh parse reads the same operations as the stored one: the whole
  stored section comes back, diff included;
* the parse changed (the parser moves between runs, and an unchanged
  bill text does not mean unchanged operations): only the corpus facts
  come back, which are the current-law text, heading, path and source.
  The operations are the fresh ones, none of them applied, and there is
  no diff, because the stored diff answers a parse that no longer holds.
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Any

# Derived from the rulespec index, not from corpus text, so the fresh
# run's values are the current ones even when its corpus lookup missed.
_ENCODING_FIELDS = ("encoding", "has_rulespec", "encoding_backlog")

# What the corpus said about the section. Independent of how the bill's
# instructions parse, so they survive a changed parse.
_CORPUS_FIELDS = (
    "in_corpus", "exact_corpus_match", "sliced_subsection",
    "matched_corpus_path", "heading", "citation_path", "current_text",
    "source_url", "corpus_fetched_at",
)

# What the parser reads out of an instruction. ``scope_source`` and
# ``note`` are by-products of applying it, so they are not compared.
# ``at_end`` was first parsed on 2026-08-25 and payloads written before
# this module existed do not carry it. A missing value compares as false,
# which is how those ops were applied, so a stored diff whose op now
# parses as "at the end" does not come back.
_OP_PARSE_FIELDS = (
    "kind", "target", "needle", "payload", "anchor", "redesignate_to",
    "at_end", "raw",
)

# The ``note`` on each operation of a text-only section. It is read after
# a lead-in, so it carries none of its own: the reconciliation prompt
# renders an unapplied op as "[could not be auto-applied: <note>] <raw>".
NOT_REAPPLIED_NOTE = "the corpus did not serve this section at this refresh"


def touch_flags(sections: list[dict]) -> tuple[bool, bool, bool]:
    """(touches_corpus, touches_rulespec, needs_new_encoding).

    Same predicate as the bill_list_summary view: a match needs >=1
    parsed amendment op. Unapplied ops count: they're real amendment
    instructions the applier couldn't verify against corpus text (drift,
    every redesignate) — excluding them made such bills silently
    invisible to the re-encode trigger.
    """
    touches_rulespec = any(
        s.get("encoding") and (s.get("applied_ops") or s.get("unapplied_ops"))
        for s in sections
    )
    touches_corpus = any(
        s.get("in_corpus") and s.get("citation_path")
        and (s.get("applied_ops") or s.get("unapplied_ops"))
        for s in sections
    )
    # Amends inside an encoded program area but no existing rule file
    # is affected → new provision → encoder backlog.
    needs_new_encoding = any(s.get("encoding_backlog") for s in sections)
    return bool(touches_corpus), bool(touches_rulespec), bool(needs_new_encoding)


def has_corpus_miss(payload: dict | None) -> bool:
    """Does this diffs payload hold any section the corpus didn't answer?"""
    return any(
        not s.get("in_corpus") for s in (payload or {}).get("sections") or []
    )


def _all_ops(section: dict) -> list[dict]:
    return (section.get("applied_ops") or []) + (section.get("unapplied_ops") or [])


def _op_keys(section: dict) -> list[tuple[str, ...]]:
    return sorted(
        tuple(str(op.get(field) or "").strip() for field in _OP_PARSE_FIELDS)
        for op in _all_ops(section)
    )


def _same_instruction(fresh: dict, stored: dict, *, same_bill_text: bool) -> bool:
    """Is the stored diff still the answer to the fresh section's ops?

    The parsed operations have to match field for field. An unchanged
    bill text is not enough: the parser changes between runs, and a newer
    parse of the same text can read more operations, or different ones.

    Matching operations settle it when there are any to compare. With
    none on either side, only an unchanged bill text shows the two
    sections are the same one.
    """
    if _op_keys(fresh) != _op_keys(stored):
        return False
    has_raw = any((op.get("raw") or "").strip() for op in _all_ops(fresh))
    return same_bill_text or has_raw


def _text_only(fresh: dict, stored: dict) -> dict:
    """The fresh section, carrying the stored section's corpus facts.

    Same shape ``precompute-diffs`` writes when it finds the text and can
    apply nothing: every operation unapplied, ``applied_text`` equal to
    ``current_text``, no diff.
    """
    kept = copy.deepcopy(fresh)
    for field in _CORPUS_FIELDS:
        kept[field] = copy.deepcopy(stored.get(field))
    kept["applied_text"] = kept["current_text"]
    kept["diff"] = []
    kept["applied_ops"] = []
    kept["unapplied_ops"] = [
        {**op, "note": NOT_REAPPLIED_NOTE} for op in _all_ops(fresh)
    ]
    kept["corpus_diff_dropped"] = True
    return kept


def preserve_stored_sections(
    fresh: dict | None,
    stored: dict | None,
    *,
    stored_as_of: str | None = None,
) -> tuple[dict | None, int]:
    """Merge ``stored`` sections into ``fresh`` where fresh missed corpus.

    Returns ``(payload, n_preserved)``. ``fresh`` is never mutated; with
    nothing to preserve it is returned as is.

    A stored section is used only when all of these hold:

    * the fresh section has a citation and ``in_corpus`` false;
    * the stored section at the same citation and the same position
      among sections with that citation has ``in_corpus`` true and
      carries ``current_text``;
    * both payloads hold the same number of sections for that citation,
      so position is unambiguous.

    When the parsed operations also match (see ``_same_instruction``)
    the whole stored section comes back. Otherwise only its corpus facts
    do, under the fresh operations, marked ``corpus_diff_dropped``.

    ``corpus_text_as_of`` is the stored section's ``corpus_fetched_at``
    when it has one, and ``corpus_text_as_of_exact`` is then true. That
    is when the text came from the corpus, which a local cache can make
    earlier than the run that computed the payload. Sections written
    before ``corpus_fetched_at`` existed fall back to ``stored_as_of``,
    the remote row's ``last_scraped_at``. The scrape stamps that column
    before the run computes its diffs, and a run that computes no diffs
    moves it without touching the payload, so it only says the text comes from a
    refresh that started on or before that time. A section already marked
    stale keeps its original date through later runs.
    """
    if not fresh or not stored:
        return fresh, 0
    fresh_sections = fresh.get("sections") or []
    stored_sections = stored.get("sections") or []
    if not fresh_sections or not stored_sections:
        return fresh, 0

    sha = fresh.get("source_text_sha256")
    same_bill_text = bool(sha) and sha == stored.get("source_text_sha256")

    stored_by_citation: dict[Any, list[dict]] = defaultdict(list)
    for section in stored_sections:
        stored_by_citation[section.get("citation")].append(section)
    fresh_counts = Counter(s.get("citation") for s in fresh_sections)

    merged: list[dict] = []
    seen: Counter = Counter()
    preserved = 0
    for section in fresh_sections:
        citation = section.get("citation")
        position = seen[citation]
        seen[citation] += 1
        candidates = stored_by_citation.get(citation) or []
        keep = (
            bool(citation)
            and not section.get("in_corpus")
            and len(candidates) == fresh_counts[citation]
            and candidates[position].get("in_corpus")
            and candidates[position].get("current_text")
        )
        if not keep:
            merged.append(section)
            continue
        source = candidates[position]
        if _same_instruction(section, source, same_bill_text=same_bill_text):
            kept = copy.deepcopy(source)
            for field in _ENCODING_FIELDS:
                if field in section:
                    kept[field] = section[field]
        else:
            kept = _text_only(section, source)
        kept["corpus_stale"] = True
        if source.get("corpus_text_as_of"):
            kept["corpus_text_as_of"] = source["corpus_text_as_of"]
            kept["corpus_text_as_of_exact"] = bool(
                source.get("corpus_text_as_of_exact"))
        elif source.get("corpus_fetched_at"):
            kept["corpus_text_as_of"] = source["corpus_fetched_at"]
            kept["corpus_text_as_of_exact"] = True
        else:
            kept["corpus_text_as_of"] = stored_as_of
            kept["corpus_text_as_of_exact"] = False
        # The corpus no longer serves this path, so the Axiom link would
        # land on a not-found page. ``source_url`` (the official source)
        # still stands.
        kept["axiom_url"] = None
        merged.append(kept)
        preserved += 1

    if not preserved:
        return fresh, 0
    return {**fresh, "sections": merged}, preserved
