"""LLM-assisted Tier 3 re-encoder.

For structural bill amendments (`amend-to-read`, `repeal`, `redesignate`)
the mechanical Tier 1 reencoder bails out — needle/payload aren't
scalar so it can't auto-patch. This module asks Claude to read the
baseline rule YAML, the bill's amendment text, and the section
citation, and propose a new YAML with the affected rules' versions
extended (baseline preserved, new version appended).

The output is validated before storage: must parse, must keep the
baseline's rules, must include a version row keyed to the bill's
effective date. Anything else raises `ProposalRejected` so the
variant stays at "needs human review" rather than shipping garbage.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import yaml


# ────────────────────────────────────────────────────────────────────
#  Public types
# ────────────────────────────────────────────────────────────────────


@dataclass
class LLMProposal:
    baseline_yaml: str
    patched_yaml: str
    model: str  # the Anthropic model id, for provenance


class ProposalRejected(Exception):
    """Raised when an LLM proposal fails our safety checks."""


# ────────────────────────────────────────────────────────────────────
#  Prompt builder
# ────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """\
You are helping maintain a Rulespec encoding of US law. The rulespec
format encodes statutory rules as YAML with versioned formulas:

```yaml
rules:
  - name: rule_name
    source: 26 USC X(y)
    metadata:
      proof:
        atoms:
          - path: versions[0].formula
            kind: amount | condition | definition | ...
            source:
              corpus_citation_path: us/statute/26/X
              text: "verbatim quote from law that grounds this rule"
    versions:
      - effective_from: 'YYYY-MM-DD'
        formula: |- ...
```

When a bill changes statutory text, the encoded rules' grounding
changes. Your job: read the baseline YAML and the bill's amendment
language, then propose an updated YAML where each affected rule
gains a NEW version row keyed to the bill's effective date, WITHOUT
removing the historical version.

Hard rules:
1. Preserve every rule that exists in the baseline YAML. Don't drop
   rules. Don't rename them. If a rule isn't affected by the bill,
   leave it untouched.
2. For each AFFECTED rule, APPEND a new entry to its `versions:` list.
   Do NOT replace the existing entry — historical computation still
   needs to work against pre-bill dates. A rule is "affected" only if
   the bill's amendment changes WHAT it computes. If the bill leaves a
   rule's grounding text and value untouched, DO NOT add a new version
   row — a version with the same formula as the baseline is noise.
3. The new version's `effective_from:` must be exactly the date
   provided in the task.
4. The new version's `formula:` should reflect the law as amended by
   the bill — express new conditions/requirements in the same style as
   the baseline formula (boolean predicates, references to other
   parameters, arithmetic, etc.).
5. Update the rule's atoms (`metadata.proof.atoms`) so that an atom
   exists describing what the NEW version grounds in (you can add a
   second atom entry pointing at `versions[1].formula` with the new
   statutory quote).
6. Update `module.summary` ONLY if a phrase in it is directly
   contradicted by the bill — leave other prose alone.
7. Use new predicate names where new concepts are introduced (e.g.
   `qualifying_child_ssn_meets_section_24_e_2_definition`). Don't
   try to redefine pre-existing predicates — humans wire those up.
8. Output ONLY the YAML, optionally wrapped in a ```yaml fence. No
   commentary before or after.
"""


def build_prompt(
    *,
    baseline_yaml: str,
    citation: str,
    bill_number: str,
    bill_op_text: str,
    effective_from: date,
) -> str:
    """Assemble the user-side prompt. System prompt is separate so the
    model has a stable role; this contains the per-task specifics."""
    return (
        f"Bill: {bill_number}\n"
        f"Affected section: {citation}\n"
        f"Effective date for the new version: {effective_from.isoformat()}\n"
        f"\n"
        f"Baseline rulespec YAML (preserve all rules and historical versions):\n"
        f"```yaml\n{baseline_yaml}\n```\n"
        f"\n"
        f"Bill amendment text for this section:\n"
        f"```\n{bill_op_text.strip()}\n```\n"
        f"\n"
        f"Propose a patched YAML following the system rules. Keep every "
        f"baseline rule. Append (don't replace) a new version row keyed "
        f"to {effective_from.isoformat()} on every rule whose grounding "
        f"the bill changes."
    )


# ────────────────────────────────────────────────────────────────────
#  Response parsing
# ────────────────────────────────────────────────────────────────────


_FENCE_RE = re.compile(
    r"```(?:yaml|yml)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def parse_response(text: str) -> str:
    """Pull the YAML out of an LLM response. The model is asked to emit
    a single ```yaml fenced block, but be forgiving: take the largest
    fenced block if multiple exist, fall back to the raw text."""
    matches = _FENCE_RE.findall(text)
    if matches:
        return max(matches, key=len).strip()
    return text.strip()


# ────────────────────────────────────────────────────────────────────
#  Validator
# ────────────────────────────────────────────────────────────────────


def validate_proposal(
    proposal_yaml: str, *, baseline_yaml: str, effective_from: date
) -> LLMProposal:
    """Run safety checks on the proposal. Strips duplicate-formula new
    versions before validation — those are LLM noise where the model
    appended a version row with the baseline formula verbatim. Raises
    `ProposalRejected` if no rule has a *semantically* new version at
    the bill's effective date."""
    try:
        proposal = yaml.safe_load(proposal_yaml)
    except yaml.YAMLError as exc:
        raise ProposalRejected(f"could not parse YAML: {exc}") from exc
    if not isinstance(proposal, dict):
        raise ProposalRejected("proposal is not a YAML mapping")
    if "rules" not in proposal:
        raise ProposalRejected("proposal has no `rules` block")

    baseline = yaml.safe_load(baseline_yaml) or {}
    baseline_rules = {r["name"]: r for r in baseline.get("rules", []) if "name" in r}
    proposal_rules = {r["name"]: r for r in proposal.get("rules", []) if "name" in r}

    # 1. No baseline rule was dropped.
    dropped = baseline_rules.keys() - proposal_rules.keys()
    if dropped:
        raise ProposalRejected(f"proposal dropped baseline rules: {sorted(dropped)}")

    eff = effective_from.isoformat()
    rules_with_real_change: list[str] = []

    # 2. For every rule the model returned that exists in baseline,
    #    preserve historical versions and clean duplicate new versions.
    for name, prule in proposal_rules.items():
        baseline_rule = baseline_rules.get(name)
        if baseline_rule is None:
            continue
        baseline_versions = baseline_rule.get("versions") or []
        prop_versions = prule.get("versions") or []
        if not baseline_versions:
            continue
        baseline_dates = {
            _version_date_iso(v.get("effective_from")) for v in baseline_versions
        }
        prop_dates = {_version_date_iso(v.get("effective_from")) for v in prop_versions}
        missing = baseline_dates - prop_dates
        if missing:
            raise ProposalRejected(
                f"rule {name!r}: baseline version(s) {sorted(missing)} "
                f"are missing from the proposal"
            )
        proposal_versions_by_date = {
            _version_date_iso(v.get("effective_from")): v for v in prop_versions
        }
        for baseline_version in baseline_versions:
            baseline_date = _version_date_iso(baseline_version.get("effective_from"))
            proposal_version = proposal_versions_by_date.get(baseline_date)
            if proposal_version is None:
                continue
            if _normalize_formula(
                proposal_version.get("formula", "")
            ) != _normalize_formula(baseline_version.get("formula", "")):
                raise ProposalRejected(
                    f"rule {name!r}: historical version {baseline_date} formula "
                    "changed in the proposal"
                )

        latest_baseline_formula = _normalize_formula(
            baseline_versions[-1].get("formula", "")
        )
        cleaned_versions: list[Any] = []
        for v in prop_versions:
            version_date = _version_date_iso(v.get("effective_from"))
            if version_date in baseline_dates:
                cleaned_versions.append(v)
                continue
            new_formula = _normalize_formula(v.get("formula", ""))
            if new_formula != latest_baseline_formula:
                cleaned_versions.append(v)
                if version_date == eff:
                    rules_with_real_change.append(name)

        # If we dropped any versions, also strip atom entries that
        # pointed at dropped paths so the YAML stays internally
        # consistent.
        if len(cleaned_versions) != len(prop_versions):
            prule["versions"] = cleaned_versions
            _trim_atoms_to_versions(prule, len(cleaned_versions))

    if not rules_with_real_change:
        raise ProposalRejected(
            f"no rule gained a semantically new version at "
            f"effective_from={eff} — every proposed new version had "
            f"the same formula as its baseline"
        )

    return LLMProposal(
        baseline_yaml=baseline_yaml,
        patched_yaml=yaml.safe_dump(proposal, sort_keys=False),
        model="",
    )


def _normalize_formula(s: Any) -> str:
    """Whitespace-tolerant formula comparison."""
    return re.sub(r"\s+", " ", str(s or "").strip())


def _version_date_iso(value: Any) -> str:
    """Normalize YAML-loaded effective_from values to ISO date strings."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _trim_atoms_to_versions(rule: dict, n_versions: int) -> None:
    """Drop atom entries whose path references a `versions[N].formula`
    index that's beyond the current versions length."""
    proof = (rule.get("metadata") or {}).get("proof")
    if not isinstance(proof, dict):
        return
    atoms = proof.get("atoms") or []
    kept = []
    for a in atoms:
        path = (a.get("path") or "") if isinstance(a, dict) else ""
        m = re.match(r"versions\[(\d+)\]\.formula", path)
        if m and int(m.group(1)) >= n_versions:
            continue
        kept.append(a)
    proof["atoms"] = kept


# ────────────────────────────────────────────────────────────────────
#  Anthropic call (live)
# ────────────────────────────────────────────────────────────────────


DEFAULT_MODEL = os.environ.get("AXIOM_LLM_MODEL", "claude-sonnet-4-5")


def propose_via_anthropic(
    *,
    baseline_yaml: str,
    citation: str,
    bill_number: str,
    bill_op_text: str,
    effective_from: date,
    model: str | None = None,
) -> LLMProposal:
    """Call Claude, parse, validate. Reads ANTHROPIC_API_KEY from env."""
    from anthropic import Anthropic  # local import keeps unit tests light

    client = Anthropic()  # picks up ANTHROPIC_API_KEY
    used_model = model or DEFAULT_MODEL
    prompt = build_prompt(
        baseline_yaml=baseline_yaml,
        citation=citation,
        bill_number=bill_number,
        bill_op_text=bill_op_text,
        effective_from=effective_from,
    )
    resp = client.messages.create(
        model=used_model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":
        # Truncated YAML would just fail validation with a confusing
        # error; surface the real cause. RuntimeError (not
        # ProposalRejected) so the caller records it as retriable.
        raise RuntimeError(
            f"LLM response truncated at max_tokens for {citation} — "
            "baseline may be too large for one-shot re-encoding."
        )
    text_blocks = [b.text for b in resp.content if getattr(b, "text", None)]
    raw = "\n".join(text_blocks)
    yaml_text = parse_response(raw)
    proposal = validate_proposal(
        yaml_text,
        baseline_yaml=baseline_yaml,
        effective_from=effective_from,
    )
    proposal.model = used_model
    return proposal
