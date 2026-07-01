"""Tests for the variant batch step (variants.py).

The reencoder core has its own tests; these cover the storage
behavior the iterative loop depends on:

* recomputing with unchanged inputs preserves the row — including an
  LLM-proposed patched_yaml (regression: recomputes used to null it),
* a changed bill text / ops set invalidates the row and clears the
  stale proposal so propose-llm-variants re-proposes,
* variants for files the bill no longer touches are removed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from textwrap import dedent

import pytest

from axiom_bills._common.variants import compute_for_bill


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
# The full chain contains state-coverage seed files with (tolerated)
# duplicate-column errors; apply just the schema the variant path needs.
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "006_encoded_rules.sql",
    "007_rule_variants.sql",
    "008_rule_variant_provenance.sql",
    "056_variant_source_tracking.sql",
]

BASELINE_YAML = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/26/32
      summary: |-
        The credit is $600.
    rules:
      - name: example_credit_amount
        kind: parameter
        source: 26 USC 32(a)
        dtype: Money
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: amount
                source:
                  text: "600"
        versions:
          - effective_from: 2020-01-01
            formula: 600
""")


def _diffs_payload(needle: str = "$600", payload: str = "$750",
                   text_sha: str = "sha-v1") -> str:
    return json.dumps({
        "source_text_sha256": text_sha,
        "sections": [{
            "citation": "26 USC 32(a)",
            "applied_ops": [{
                "kind": "strike-insert",
                "target": "26 USC 32(a)",
                "needle": needle,
                "payload": payload,
            }],
        }],
    })


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    for name in SCHEMA_MIGRATIONS:
        db.executescript((MIGRATIONS / name).read_text())

    repo_root = tmp_path / "rulespec-us"
    (repo_root / "statutes" / "26").mkdir(parents=True)
    (repo_root / "statutes" / "26" / "32.yaml").write_text(BASELINE_YAML)
    monkeypatch.setenv("RULESPEC_US_ROOT", str(repo_root))

    db.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us', 'US', 'federal', 'https://example.gov')"
    )
    db.execute(
        "INSERT INTO sessions (id, jurisdiction, name) VALUES ('s1', 'us', '119')"
    )
    db.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, current_status_at, diffs)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1',
                '2026-06-01 00:00:00', ?)
        """,
        (_diffs_payload(),),
    )
    db.execute(
        """
        INSERT INTO axiom_encodings (id, jurisdiction, repo, kind, citation, file_path)
        VALUES ('e1', 'us', 'rulespec-us', 'statute', '26 USC 32(a)',
                'statutes/26/32.yaml')
        """
    )
    db.execute(
        """
        INSERT INTO encoded_rules (id, encoding_id, rule_name, rule_source)
        VALUES ('r1', 'e1', 'example_credit_amount', '26 USC 32(a)')
        """
    )
    db.execute(
        """
        INSERT INTO encoded_rule_atoms (id, rule_id, atom_path, atom_kind, text)
        VALUES ('a1', 'r1', 'versions[0].formula', 'amount', '600')
        """
    )
    yield db
    db.close()


def _variant(conn) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM rule_variants WHERE bill_id='b1'"
    ).fetchone()


def test_initial_compute_records_fingerprint_and_provenance(conn):
    counts = compute_for_bill(conn, "b1")
    assert counts["variants"] == 1
    v = _variant(conn)
    assert v["tier"] == "substitution"
    assert v["patched_yaml"]  # auto-patched scalar substitution
    assert v["proposed_by"] == "auto"
    assert v["source_ops_fingerprint"]
    assert v["source_text_sha256"] == "sha-v1"


def test_recompute_with_same_inputs_is_a_no_op(conn):
    compute_for_bill(conn, "b1")
    before = dict(_variant(conn))
    counts = compute_for_bill(conn, "b1")
    assert counts["unchanged"] == 1
    assert counts["variants"] == 0
    assert dict(_variant(conn)) == before


def test_recompute_preserves_llm_proposal_when_inputs_unchanged(conn):
    """Regression: recomputes used to null patched_yaml for LLM tiers."""
    compute_for_bill(conn, "b1")
    conn.execute(
        """
        UPDATE rule_variants
           SET tier='structural', patched_yaml='llm: yaml',
               proposed_by='llm', proposed_model='claude-sonnet-4-5'
         WHERE bill_id='b1'
        """
    )
    compute_for_bill(conn, "b1")
    v = _variant(conn)
    assert v["patched_yaml"] == "llm: yaml"
    assert v["proposed_by"] == "llm"


def test_changed_ops_invalidate_stale_llm_proposal(conn):
    compute_for_bill(conn, "b1")
    conn.execute(
        """
        UPDATE rule_variants
           SET tier='structural', patched_yaml='llm: yaml',
               proposed_by='llm', proposed_model='claude-sonnet-4-5'
         WHERE bill_id='b1'
        """
    )
    # Engrossed text changes the amendment: $750 → $800.
    conn.execute(
        "UPDATE bills SET diffs=? WHERE id='b1'",
        (_diffs_payload(payload="$800", text_sha="sha-v2"),),
    )
    compute_for_bill(conn, "b1")
    v = _variant(conn)
    assert v["proposed_by"] != "llm"
    assert v["source_text_sha256"] == "sha-v2"
    assert "Superseded" in (v["note"] or "")
    # Fresh auto-patch against the new ops (still scalar) replaces it.
    assert v["tier"] == "substitution"
    assert "800" in (v["patched_yaml"] or "")


def test_variant_removed_when_bill_stops_touching_file(conn):
    compute_for_bill(conn, "b1")
    assert _variant(conn) is not None
    conn.execute(
        "UPDATE bills SET diffs=? WHERE id='b1'",
        (json.dumps({"sections": [], "source_text_sha256": "sha-v3"}),),
    )
    counts = compute_for_bill(conn, "b1")
    assert counts.get("removed_stale") == 1
    assert _variant(conn) is None


def test_missing_baseline_records_no_op(conn, monkeypatch, tmp_path):
    monkeypatch.setenv("RULESPEC_US_ROOT", str(tmp_path / "nowhere"))
    counts = compute_for_bill(conn, "b1")
    assert counts["no_op"] == 1
    v = _variant(conn)
    assert v["tier"] == "no_op"
    assert "not on disk" in v["note"]
