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

This module is the pure merge. It prefers the stored section only when
it can show the stored diff still answers the same amendment
instruction, marks what it kept as stale, and never touches a section
the fresh run matched.
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Any

# Derived from the rulespec index, not from corpus text, so the fresh
# run's values are the current ones even when its corpus lookup missed.
_ENCODING_FIELDS = ("encoding", "has_rulespec", "encoding_backlog")


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


def _op_raws(section: dict) -> list[str]:
    ops = (section.get("applied_ops") or []) + (section.get("unapplied_ops") or [])
    return sorted((op.get("raw") or "").strip() for op in ops)


def _same_instruction(fresh: dict, stored: dict, *, same_bill_text: bool) -> bool:
    """Is the stored diff still the answer to the fresh section's ops?

    Identical bill text settles it: same text, same citation, same
    position. Otherwise fall back to the parsed instructions themselves,
    which survive a re-fetch that changed unrelated parts of the bill.
    """
    if same_bill_text:
        return True
    fresh_raws = _op_raws(fresh)
    return bool(fresh_raws) and any(fresh_raws) and fresh_raws == _op_raws(stored)


def preserve_stored_sections(
    fresh: dict | None,
    stored: dict | None,
    *,
    stored_as_of: str | None = None,
) -> tuple[dict | None, int]:
    """Merge ``stored`` sections into ``fresh`` where fresh missed corpus.

    Returns ``(payload, n_preserved)``. ``fresh`` is never mutated; with
    nothing to preserve it is returned as is.

    A stored section replaces a fresh one only when all of these hold:

    * the fresh section has ``in_corpus`` false;
    * the stored section at the same citation and the same position
      among sections with that citation has ``in_corpus`` true and
      carries ``current_text``;
    * both payloads hold the same number of sections for that citation,
      so position is unambiguous;
    * the bill text is unchanged, or the parsed instructions are.

    ``stored_as_of`` is the remote row's ``last_scraped_at``. The scrape
    stamps that column and the payload carries no computation time, so it
    is the latest the stored text can date from, not the exact time. A
    section already marked stale keeps its original date through later
    runs.
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
            not section.get("in_corpus")
            and len(candidates) == fresh_counts[citation]
            and candidates[position].get("in_corpus")
            and candidates[position].get("current_text")
            and _same_instruction(section, candidates[position],
                                  same_bill_text=same_bill_text)
        )
        if not keep:
            merged.append(section)
            continue
        kept = copy.deepcopy(candidates[position])
        for field in _ENCODING_FIELDS:
            if field in section:
                kept[field] = section[field]
        kept["corpus_stale"] = True
        kept["corpus_text_as_of"] = kept.get("corpus_text_as_of") or stored_as_of
        # The corpus no longer serves this path, so the Axiom link would
        # land on a not-found page. ``source_url`` (the official source)
        # still stands.
        kept["axiom_url"] = None
        merged.append(kept)
        preserved += 1

    if not preserved:
        return fresh, 0
    return {**fresh, "sections": merged}, preserved
