"""Re-encode a rulespec YAML against a bill's amendments.

Pipeline B's mechanical core. Given:

* the baseline rule YAML (as published in rulespec-us),
* the bill's parsed `Op`s against the statute section the YAML encodes,
* the `Atom`s the rule's proof claims (which path each atom points at,
  and what literal text it grounds),

produce a *variant* YAML where each affected rule gains a new version
keyed to the bill's effective date and reflecting the bill's new
values. The baseline `effective_from` version is preserved, so
historical computation against earlier dates is unchanged.

Tiers:

* `SUBSTITUTION` — needle and payload are scalar (dollar, date, percent).
  We can fully patch atoms + formulas + module summary.
* `LIST`         — needle is empty, payload is a new list item being
  appended. Mechanical for the YAML list but requires authoring the
  rule branch — out of scope for the auto-patcher.
* `STRUCTURAL`   — `amend-to-read`, `repeal`, redesignation — entire
  block being rewritten. Needs human (or LLM-with-review) authoring.
* `NO_OP`        — no atom of any rule in this file references the
  targeted section; the bill's ops don't affect this YAML.

The function is pure: it does not touch disk, the network, or Supabase.
Storage and CLI sit in separate modules so we can unit-test the logic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable

import yaml

from .citation_scope import is_ancestor


# ────────────────────────────────────────────────────────────────────
#  Data types
# ────────────────────────────────────────────────────────────────────


class Tier(str, Enum):
    SUBSTITUTION = "substitution"   # auto-patchable
    LIST         = "list"           # needs authoring
    STRUCTURAL   = "structural"     # needs LLM/human
    NO_OP        = "no_op"          # nothing to do


@dataclass
class Atom:
    """One proof atom from a rule's metadata.proof.atoms list.

    `text` is the literal value the atom grounds — for an `amount` atom
    that's the formula's numeric value rendered as text (e.g. "10000");
    for a `date` atom it's an ISO date string. We use `text` to detect
    matches against bill needles/payloads.

    `rule_source` is the owning rule's `source` citation (subsection
    level, e.g. '26 USC 32(b)(2)'). When present, it scopes matching:
    an op striking "$10,000" in 32(b) must not patch a rule grounded in
    32(a) that happens to use the same number.
    """
    rule_name: str
    path: str
    kind: str
    text: str
    rule_source: str = ""


@dataclass
class Op:
    """One amendment operation parsed from the bill."""
    kind: str          # 'strike-insert', 'add-end', 'amend-to-read', 'repeal', etc.
    target: str        # e.g. '26 USC 163(h)(4)(C)'
    needle: str        # text to strike (or empty for add-end)
    payload: str       # text to insert


@dataclass
class ReencodeResult:
    tier: Tier
    patched_yaml: str
    patched_rules: list[str]
    diff_summary: str = ""
    note: str = ""


# ────────────────────────────────────────────────────────────────────
#  Tier classification
# ────────────────────────────────────────────────────────────────────


_TIER_BY_OP_KIND: dict[str, Tier] = {
    "strike-insert":    Tier.SUBSTITUTION,
    "strike":           Tier.SUBSTITUTION,
    "add-end":          Tier.LIST,
    "insert-after":     Tier.LIST,
    "insert-before":    Tier.LIST,
    "amend-to-read":    Tier.STRUCTURAL,
    "repeal":           Tier.STRUCTURAL,
    "redesignate":      Tier.STRUCTURAL,
}


def _classify_op(op: Op) -> Tier:
    return _TIER_BY_OP_KIND.get(op.kind, Tier.STRUCTURAL)


def _section_root(citation: str) -> str:
    """'26 USC 32(b)(2)' → '26 USC 32'."""
    i = citation.find("(")
    return (citation[:i] if i != -1 else citation).strip()


def _op_reaches_rule(op_target: str, rule_source: str) -> bool:
    """Scope check: can an op targeting `op_target` change a rule
    grounded in `rule_source`?

    Only enforced when both citations are within the same section and
    comparable — a rule sourced at 32(a) is out of reach of an op
    striking text in 32(b). Sources in another format (or empty) stay
    permissive: value-matching alone decides, as before.
    """
    if not op_target or not rule_source:
        return True
    if _section_root(op_target) != _section_root(rule_source):
        return True
    return (
        op_target == rule_source
        or is_ancestor(op_target, rule_source)
        or is_ancestor(rule_source, op_target)
    )


# ────────────────────────────────────────────────────────────────────
#  Scalar parsing (needle/payload → comparable value)
# ────────────────────────────────────────────────────────────────────

_DOLLAR_RE  = re.compile(r"^\$\s*([0-9][0-9,]*(?:\.\d+)?)$")
_PERCENT_RE = re.compile(r"^([0-9]+(?:\.\d+)?)\s*percent$", re.IGNORECASE)
_NUMBER_RE  = re.compile(r"^([0-9][0-9,]*(?:\.\d+)?)$")


_MONTHS = {m.lower(): i + 1 for i, m in enumerate([
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
])}
_NATURAL_DATE_RE = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$"
)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _parse_scalar(s: str) -> tuple[str, str] | None:
    """Return ('kind', 'normalized_value') for any scalar we recognize.

    The normalized value is what we compare against the atom's `text`
    field, which always stores the underlying numeric/iso form.
    """
    s = s.strip()
    if not s:
        return None
    m = _DOLLAR_RE.match(s)
    if m:
        return ("amount", m.group(1).replace(",", ""))
    m = _PERCENT_RE.match(s)
    if m:
        return ("percent", m.group(1))
    m = _NUMBER_RE.match(s)
    if m:
        return ("amount", m.group(1).replace(",", ""))
    m = _NATURAL_DATE_RE.match(s)
    if m:
        month_name, day, year = m.groups()
        month_num = _MONTHS.get(month_name.lower())
        if month_num:
            return ("date", f"{year}-{month_num:02d}-{int(day):02d}")
    m = _ISO_DATE_RE.match(s)
    if m:
        return ("date", s)
    return None


# ────────────────────────────────────────────────────────────────────
#  Core: apply substitutions to a YAML tree
# ────────────────────────────────────────────────────────────────────


def reencode_rule_file(
    yaml_text: str,
    operations: Iterable[Op],
    atoms: Iterable[Atom],
    *,
    effective_from: date,
) -> ReencodeResult:
    operations = list(operations)
    atoms = list(atoms)

    if not operations:
        return ReencodeResult(tier=Tier.NO_OP, patched_yaml=yaml_text,
                              patched_rules=[])

    # If ANY op is structural, escalate the whole file's tier to
    # structural — we won't auto-patch even sibling substitution ops in
    # the same block, because mixing risks producing a YAML that looks
    # valid but doesn't reflect the bill's full intent.
    tiers = [_classify_op(op) for op in operations]
    if Tier.STRUCTURAL in tiers:
        return ReencodeResult(
            tier=Tier.STRUCTURAL,
            patched_yaml=yaml_text,
            patched_rules=[],
            note="Structural amendment (amend-to-read/repeal/redesignate) — "
                 "needs human review.",
        )
    if Tier.LIST in tiers:
        return ReencodeResult(
            tier=Tier.LIST,
            patched_yaml=yaml_text,
            patched_rules=[],
            note="List add/insert — needs human review to author the new branch.",
        )

    # Pure-substitution path: walk each op, find atoms whose text
    # matches the needle's normalized value, patch them.
    patched_rule_names: list[str] = []
    diff_lines: list[str] = []

    data = yaml.safe_load(yaml_text)
    rules = data.get("rules", [])
    rules_by_name = {r["name"]: r for r in rules}

    atoms_by_rule: dict[str, list[Atom]] = {}
    for a in atoms:
        atoms_by_rule.setdefault(a.rule_name, []).append(a)

    rules_were_patched: set[str] = set()

    for op in operations:
        needle_scalar = _parse_scalar(op.needle)
        payload_scalar = _parse_scalar(op.payload)
        if needle_scalar is None or payload_scalar is None:
            # Couldn't parse as scalar — out of scope for SUBSTITUTION
            # tier. Escalate to structural so we don't ship a half-baked
            # patch.
            return ReencodeResult(
                tier=Tier.STRUCTURAL,
                patched_yaml=yaml_text,
                patched_rules=[],
                note=f"Op {op.kind} needle/payload not a recognized scalar "
                     f"(needle={op.needle!r}, payload={op.payload!r}).",
            )
        n_kind, n_norm = needle_scalar
        p_kind, p_norm = payload_scalar
        if n_kind != p_kind:
            # Striking "$500" and inserting "January 1, 2027" would put
            # a date into a Money formula. Not auto-patchable.
            return ReencodeResult(
                tier=Tier.STRUCTURAL,
                patched_yaml=yaml_text,
                patched_rules=[],
                note=f"Op {op.kind} replaces a {n_kind} with a {p_kind} "
                     f"(needle={op.needle!r}, payload={op.payload!r}) — "
                     "needs human review.",
            )

        op_patched = False
        for atom in atoms:
            if atom.text.strip() != n_norm:
                continue
            if not _op_reaches_rule(op.target, atom.rule_source):
                continue
            rule = rules_by_name.get(atom.rule_name)
            if rule is None:
                continue
            _append_patched_version(rule, atom.path, p_norm,
                                    effective_from=effective_from)
            rules_were_patched.add(atom.rule_name)
            op_patched = True

        if op_patched:
            # Patch the module summary in-place so the prose reflects
            # new law. Strict needle/payload string substitution. Only
            # for ops that actually patched a rule — recording unmatched
            # ops made diff_summary claim changes that weren't applied.
            summary = data.get("module", {}).get("summary")
            if isinstance(summary, str) and op.needle in summary:
                data["module"]["summary"] = summary.replace(op.needle, op.payload)
            diff_lines.append(f"{op.needle} → {op.payload}")

    if not rules_were_patched:
        # Ops parse cleanly as scalars, but no rule's atom matched the
        # needle value. That's a NO_OP from this YAML's perspective.
        return ReencodeResult(
            tier=Tier.NO_OP,
            patched_yaml=yaml_text,
            patched_rules=[],
            note="No atom in this file matched the bill's needle value.",
        )

    patched_rule_names = sorted(rules_were_patched)
    return ReencodeResult(
        tier=Tier.SUBSTITUTION,
        patched_yaml=yaml.safe_dump(data, sort_keys=False),
        patched_rules=patched_rule_names,
        diff_summary="; ".join(diff_lines),
    )


# ────────────────────────────────────────────────────────────────────
#  Patching primitives
# ────────────────────────────────────────────────────────────────────

_VERSIONS_PATH_RE = re.compile(r"^versions\[(\d+)\]\.formula$")


def _append_patched_version(rule: dict, atom_path: str, new_value: str, *,
                            effective_from: date) -> None:
    """Append a new version dict to `rule['versions']`.

    The baseline version is left intact so historical computation still
    works. We require atom_path to point at a versions[N].formula entry;
    other atom paths are out of scope for the substitution tier and the
    caller should have rejected them upstream.
    """
    m = _VERSIONS_PATH_RE.match(atom_path)
    if m is None:
        # Atom doesn't point at a versions[].formula. Don't crash — just
        # skip; the diff_summary still records what the op intended.
        return
    versions = rule.setdefault("versions", [])
    new_version = {
        "effective_from": effective_from.isoformat(),
        "formula": _render_formula(new_value),
    }
    versions.append(new_version)


def _render_formula(value: str) -> str:
    """Render a scalar value back into a block-literal-friendly form.

    Numbers stay bare; dates and other strings stay as plain strings.
    Rulespec's formulas use `|-` block scalars in source — we keep the
    same value but let yaml.safe_dump choose its own representation.
    """
    return value
