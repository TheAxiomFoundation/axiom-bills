"""Tests for auto-patcher scoping, kind checking, and honest summaries."""

from __future__ import annotations

from datetime import date
from textwrap import dedent

import yaml

from axiom_bills._common.reencoder import (
    Atom,
    Op,
    Tier,
    reencode_rule_file,
)


BASELINE = dedent("""\
    format: rulespec/v1
    module:
      summary: |-
        The cap in (a) is $10,000 and the cap in (b) is $10,000.
    rules:
      - name: cap_a
        kind: parameter
        source: 26 USC 999(a)
        versions:
          - effective_from: 2020-01-01
            formula: 10000
      - name: cap_b
        kind: parameter
        source: 26 USC 999(b)
        versions:
          - effective_from: 2020-01-01
            formula: 10000
""")

ATOMS = [
    Atom(rule_name="cap_a", path="versions[0].formula", kind="amount",
         text="10000", rule_source="26 USC 999(a)"),
    Atom(rule_name="cap_b", path="versions[0].formula", kind="amount",
         text="10000", rule_source="26 USC 999(b)"),
]


def test_op_only_patches_rules_in_its_target_scope():
    """Striking $10,000 in 999(b) must not touch the 999(a) rule that
    happens to ground the same number."""
    result = reencode_rule_file(
        BASELINE,
        [Op(kind="strike-insert", target="26 USC 999(b)",
            needle="$10,000", payload="$12,000")],
        ATOMS,
        effective_from=date(2027, 1, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    assert result.patched_rules == ["cap_b"]
    data = yaml.safe_load(result.patched_yaml)
    versions = {r["name"]: len(r["versions"]) for r in data["rules"]}
    assert versions == {"cap_a": 1, "cap_b": 2}


def test_section_level_op_patches_all_rules_in_section():
    result = reencode_rule_file(
        BASELINE,
        [Op(kind="strike-insert", target="26 USC 999",
            needle="$10,000", payload="$12,000")],
        ATOMS,
        effective_from=date(2027, 1, 1),
    )
    assert result.patched_rules == ["cap_a", "cap_b"]


def test_atoms_without_source_stay_permissive():
    atoms = [Atom(rule_name="cap_a", path="versions[0].formula",
                  kind="amount", text="10000")]
    result = reencode_rule_file(
        BASELINE,
        [Op(kind="strike-insert", target="26 USC 999(b)",
            needle="$10,000", payload="$12,000")],
        atoms,
        effective_from=date(2027, 1, 1),
    )
    assert result.patched_rules == ["cap_a"]


def test_needle_payload_kind_mismatch_escalates():
    """A date payload must never land in a Money formula."""
    result = reencode_rule_file(
        BASELINE,
        [Op(kind="strike-insert", target="26 USC 999(a)",
            needle="$10,000", payload="January 1, 2027")],
        ATOMS,
        effective_from=date(2027, 1, 1),
    )
    assert result.tier == Tier.STRUCTURAL
    assert "amount" in result.note and "date" in result.note


def test_diff_summary_only_lists_ops_that_patched():
    result = reencode_rule_file(
        BASELINE,
        [
            Op(kind="strike-insert", target="26 USC 999(a)",
               needle="$10,000", payload="$12,000"),
            # Parses as scalar but matches no atom — must not appear in
            # the summary as if it were applied.
            Op(kind="strike-insert", target="26 USC 999(a)",
               needle="$77", payload="$88"),
        ],
        ATOMS,
        effective_from=date(2027, 1, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    assert "$10,000 → $12,000" in result.diff_summary
    assert "$77" not in result.diff_summary
