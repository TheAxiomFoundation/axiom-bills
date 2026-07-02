"""Which encoded files can a bill op actually affect?

Citations nest: '7 USC 2015' contains '7 USC 2015(d)(2)(A)'. Matching a
section citation against axiom_encodings by prefix (both directions)
finds every related file — but *related* is not *affected*, and treating
them the same fanned one add-end op against §2015 into nine no-content
variants (every statutes/7/2015/... child file).

The rule, per op:

* the file whose citation equals the op's target is affected;
* ancestor files (their citation contains the target) are affected —
  they encode the scope the op edits;
* descendant files (nested under the target) are affected only by
  MODIFYING ops (strike, strike-insert, amend-to-read, repeal,
  redesignate) — rewriting or striking the parent's text can reach the
  text a child file encodes. ADDITIVE ops (add-end, insert-after,
  insert-before) append new provisions and cannot change any existing
  child — new text lands in the encoder backlog instead.
"""
from __future__ import annotations

import re


ADDITIVE_OP_KINDS = {"add-end", "insert-after", "insert-before"}

_USC_DOTTED = re.compile(r"\bU\.\s*S\.\s*C\.")
_CFR_DOTTED = re.compile(r"\bC\.\s*F\.\s*R\.")


def normalize_citation(citation: str) -> str:
    """Collapse citation format drift to the tracker's canonical form.

    rulespec-us files aren't uniform: some rule sources say
    '20 U.S.C. 1070a(b)(5)' where the tracker says '20 USC 1070a(b)(5)'.
    Prefix comparisons silently fail across that drift.
    """
    if not citation:
        return citation
    out = _USC_DOTTED.sub("USC", citation)
    out = _CFR_DOTTED.sub("CFR", out)
    out = out.replace("§", " ").replace("§", " ")
    return re.sub(r"\s+", " ", out).strip()


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """True if `descendant` is strictly nested inside `ancestor`.

    Mirrors the SQL predicate used to find candidates:
    '26 USC 32' is an ancestor of '26 USC 32(a)(1)';
    '7 CFR 273' of '7 CFR 273.3'.
    """
    if not ancestor or not descendant or ancestor == descendant:
        return False
    return descendant.startswith(ancestor + "(") or \
        descendant.startswith(ancestor + ".")


def op_affects_encoding(encoding_citation: str, op_target: str,
                        op_kind: str) -> bool:
    """Can this op change what `encoding_citation`'s file encodes?"""
    if not encoding_citation or not op_target:
        return False
    if encoding_citation == op_target:
        return True
    # File encodes a scope containing the target: any edit inside it
    # (including appended text) is this file's business.
    if is_ancestor(encoding_citation, op_target):
        return True
    # File is nested under the target: only ops that rewrite or strike
    # existing text can reach it. Appending new text cannot.
    if is_ancestor(op_target, encoding_citation):
        return op_kind not in ADDITIVE_OP_KINDS
    return False
