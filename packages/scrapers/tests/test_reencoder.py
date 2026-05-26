"""Tests for the rulespec re-encoder.

The re-encoder is the heart of Pipeline B: given a bill's parsed
operations against a statute section and the rulespec-us rules
encoded against that section, produce a patched YAML where each
affected rule gains a new version row keyed to the bill's effective
date. The baseline version is preserved so historical computation
still works.

Test fixtures mirror the real rulespec-us layout we saw in
statutes/26/163.yaml (passenger vehicle loan interest).
"""
from __future__ import annotations

from datetime import date
from textwrap import dedent

import yaml

from axiom_bills._common.reencoder import (
    Atom,
    Op,
    ReencodeResult,
    Tier,
    reencode_rule_file,
)


# ────────────────────────────────────────────────────────────────────
#  Fixtures: minimal real-shape rulespec YAML
# ────────────────────────────────────────────────────────────────────

SINGLE_RULE = dedent("""\
    format: rulespec/v1
    module:
      proof_validation:
        required: true
      source_verification:
        corpus_citation_path: us/statute/26/163
      summary: |-
        26 USC 163(h)(4)(C): The amount of interest taken into account shall
        not exceed $10,000.
    rules:
      - name: passenger_vehicle_loan_interest_cap
        kind: parameter
        dtype: Money
        unit: USD
        source: 26 USC 163(h)(4)(C)(i)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: amount
                source:
                  corpus_citation_path: us/statute/26/163
        versions:
          - effective_from: '2025-01-01'
            formula: |-
              10000
    """)

MULTI_RULE = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/26/163
      summary: |-
        Cap $10,000; phaseout starts $100,000.
    rules:
      - name: interest_cap
        kind: parameter
        dtype: Money
        unit: USD
        source: 26 USC 163(h)(4)(C)(i)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: amount
                source:
                  corpus_citation_path: us/statute/26/163
        versions:
          - effective_from: '2025-01-01'
            formula: |-
              10000
      - name: phaseout_threshold
        kind: parameter
        dtype: Money
        unit: USD
        source: 26 USC 163(h)(4)(C)(ii)(I)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: amount
                source:
                  corpus_citation_path: us/statute/26/163
        versions:
          - effective_from: '2025-01-01'
            formula: |-
              100000
    """)

DATE_RULE = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/38/5503
      summary: |-
        38 USC 5503(d)(7): This subsection expires on November 30, 2031.
    rules:
      - name: medicaid_pension_cap_sunset
        kind: parameter
        dtype: Date
        source: 38 USC 5503(d)(7)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: date
                source:
                  corpus_citation_path: us/statute/38/5503
        versions:
          - effective_from: '2025-01-01'
            formula: |-
              2031-11-30
    """)


# ────────────────────────────────────────────────────────────────────
#  Tier 1: dollar substitutions
# ────────────────────────────────────────────────────────────────────

def test_dollar_substitution_updates_summary_and_formula():
    atom = Atom(
        rule_name="passenger_vehicle_loan_interest_cap",
        path="versions[0].formula",
        kind="amount",
        text="10000",
    )
    op = Op(
        kind="strike-insert",
        target="26 USC 163(h)(4)(C)",
        needle="$10,000",
        payload="$15,000",
    )
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    assert len(result.patched_rules) == 1
    patched = yaml.safe_load(result.patched_yaml)
    versions = patched["rules"][0]["versions"]
    # Baseline kept, new version appended.
    assert len(versions) == 2
    assert versions[0]["effective_from"] == "2025-01-01"
    assert int(versions[0]["formula"].strip()) == 10000
    assert versions[1]["effective_from"] == "2026-07-01"
    assert int(versions[1]["formula"].strip()) == 15000
    # Module summary reflects the new amount (so proof text matches law).
    assert "$15,000" in patched["module"]["summary"]
    assert "$10,000" not in patched["module"]["summary"]


def test_unrelated_atoms_left_alone():
    # Only the cap rule's atom is in the op's section; phaseout_threshold
    # has its own atom unrelated to this op.
    atoms = [
        Atom(rule_name="interest_cap", path="versions[0].formula",
             kind="amount", text="10000"),
        Atom(rule_name="phaseout_threshold", path="versions[0].formula",
             kind="amount", text="100000"),
    ]
    op = Op(kind="strike-insert", target="26 USC 163(h)(4)(C)(i)",
            needle="$10,000", payload="$15,000")
    result = reencode_rule_file(
        MULTI_RULE, [op], atoms,
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    assert result.patched_rules == ["interest_cap"]
    patched = yaml.safe_load(result.patched_yaml)
    # interest_cap has two versions; phaseout_threshold still has one.
    rules = {r["name"]: r for r in patched["rules"]}
    assert len(rules["interest_cap"]["versions"]) == 2
    assert len(rules["phaseout_threshold"]["versions"]) == 1


def test_appends_new_version_does_not_overwrite():
    atom = Atom(rule_name="passenger_vehicle_loan_interest_cap",
                path="versions[0].formula", kind="amount", text="10000")
    op = Op(kind="strike-insert", target="26 USC 163(h)(4)(C)",
            needle="$10,000", payload="$15,000")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    patched = yaml.safe_load(result.patched_yaml)
    # The OLD formula must still be present so historical computation
    # against effective_from < 2026-07-01 keeps working.
    formulas = [v["formula"].strip() for v in patched["rules"][0]["versions"]]
    assert "10000" in formulas
    assert "15000" in formulas


# ────────────────────────────────────────────────────────────────────
#  Tier 1: date substitutions
# ────────────────────────────────────────────────────────────────────

def test_date_substitution_natural_language():
    atom = Atom(rule_name="medicaid_pension_cap_sunset",
                path="versions[0].formula", kind="date", text="2031-11-30")
    op = Op(kind="strike-insert", target="38 USC 5503(d)(7)",
            needle="November 30, 2031", payload="December 31, 2031")
    result = reencode_rule_file(
        DATE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    patched = yaml.safe_load(result.patched_yaml)
    versions = patched["rules"][0]["versions"]
    assert len(versions) == 2
    assert versions[1]["formula"].strip() == "2031-12-31"
    assert "December 31, 2031" in patched["module"]["summary"]


# ────────────────────────────────────────────────────────────────────
#  Tier classification for unsupported ops
# ────────────────────────────────────────────────────────────────────

def test_add_end_classified_as_tier_list_no_patch():
    atom = Atom(rule_name="interest_cap", path="versions[0].formula",
                kind="amount", text="10000")
    op = Op(kind="add-end", target="26 USC 163(h)(4)(C)",
            needle="", payload="(iii) an exception for emergency loans.")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.LIST
    assert result.patched_yaml == SINGLE_RULE
    assert result.patched_rules == []
    assert "needs human review" in result.note.lower()


def test_amend_to_read_classified_as_tier_structural_no_patch():
    atom = Atom(rule_name="interest_cap", path="versions[0].formula",
                kind="amount", text="10000")
    op = Op(kind="amend-to-read", target="26 USC 163(h)(4)(C)",
            needle="", payload="(C) Entirely rewritten text.")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.STRUCTURAL
    assert result.patched_rules == []


def test_repeal_classified_as_tier_structural():
    atom = Atom(rule_name="interest_cap", path="versions[0].formula",
                kind="amount", text="10000")
    op = Op(kind="repeal", target="26 USC 163(h)(4)(C)",
            needle="", payload="")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.STRUCTURAL


# ────────────────────────────────────────────────────────────────────
#  Edge cases
# ────────────────────────────────────────────────────────────────────

def test_no_matching_atoms_returns_empty_result():
    # Atom belongs to a different rule that's not in this YAML file.
    atom = Atom(rule_name="some_other_rule", path="versions[0].formula",
                kind="amount", text="500")
    op = Op(kind="strike-insert", target="26 USC 999",
            needle="$500", payload="$750")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.NO_OP
    assert result.patched_rules == []
    assert result.patched_yaml == SINGLE_RULE


def test_needle_in_multiple_atoms_all_updated():
    # Two atoms grounding the same dollar amount across two rules.
    multi = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/200
          summary: |-
            Cap $1,000 in two places.
        rules:
          - name: rule_a
            kind: parameter
            dtype: Money
            source: 26 USC 200
            metadata:
              proof:
                atoms:
                  - path: versions[0].formula
                    kind: amount
                    source:
                      corpus_citation_path: us/statute/26/200
            versions:
              - effective_from: '2025-01-01'
                formula: |-
                  1000
          - name: rule_b
            kind: parameter
            dtype: Money
            source: 26 USC 200
            metadata:
              proof:
                atoms:
                  - path: versions[0].formula
                    kind: amount
                    source:
                      corpus_citation_path: us/statute/26/200
            versions:
              - effective_from: '2025-01-01'
                formula: |-
                  1000
        """)
    atoms = [
        Atom(rule_name="rule_a", path="versions[0].formula",
             kind="amount", text="1000"),
        Atom(rule_name="rule_b", path="versions[0].formula",
             kind="amount", text="1000"),
    ]
    op = Op(kind="strike-insert", target="26 USC 200",
            needle="$1,000", payload="$2,000")
    result = reencode_rule_file(
        multi, [op], atoms, effective_from=date(2026, 7, 1),
    )
    assert result.tier == Tier.SUBSTITUTION
    assert set(result.patched_rules) == {"rule_a", "rule_b"}


def test_patched_yaml_still_parses():
    atom = Atom(rule_name="passenger_vehicle_loan_interest_cap",
                path="versions[0].formula", kind="amount", text="10000")
    op = Op(kind="strike-insert", target="26 USC 163(h)(4)(C)",
            needle="$10,000", payload="$15,000")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    # Must round-trip through yaml.safe_load without raising.
    parsed = yaml.safe_load(result.patched_yaml)
    assert parsed["format"] == "rulespec/v1"
    assert "rules" in parsed


def test_diff_summary_lists_change():
    atom = Atom(rule_name="passenger_vehicle_loan_interest_cap",
                path="versions[0].formula", kind="amount", text="10000")
    op = Op(kind="strike-insert", target="26 USC 163(h)(4)(C)",
            needle="$10,000", payload="$15,000")
    result = reencode_rule_file(
        SINGLE_RULE, [op], [atom],
        effective_from=date(2026, 7, 1),
    )
    # A short, human-readable summary of what changed.
    assert "$10,000" in result.diff_summary
    assert "$15,000" in result.diff_summary
