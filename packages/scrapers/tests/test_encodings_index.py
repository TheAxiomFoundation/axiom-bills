"""Tests for index_repo's id stability.

Re-running index-encodings must not churn encoding ids: rule_variants
reference them with ON DELETE CASCADE (an id churn silently deleted
every computed variant, including paid LLM proposals), and the Supabase
sync upserts by id against a unique file_path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from textwrap import dedent

import pytest

from axiom_bills._common.encodings import index_repo


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
# The full chain contains state-coverage seed files with (tolerated)
# duplicate-column errors; apply just the schema these tests need.
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "006_encoded_rules.sql",
    "007_rule_variants.sql",
    "008_rule_variant_provenance.sql",
    "056_variant_source_tracking.sql",
]

RULE_YAML = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/26/32
    rules:
      - name: example_rule
        kind: parameter
        source: 26 USC 32(a)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: amount
                source:
                  text: "600"
""")


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(path)
    for name in SCHEMA_MIGRATIONS:
        conn.executescript((MIGRATIONS / name).read_text())
    conn.close()
    return str(path)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "rulespec-us"
    (root / "statutes" / "26").mkdir(parents=True)
    (root / "statutes" / "26" / "32.yaml").write_text(RULE_YAML)
    return root


def _encodings(db_path) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, file_path FROM axiom_encodings").fetchall()
    conn.close()
    return {r["file_path"]: r["id"] for r in rows}


def test_reindex_keeps_encoding_ids_stable(db_path, repo):
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    first = _encodings(db_path)
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    assert _encodings(db_path) == first


def test_reindex_preserves_rule_variants(db_path, repo):
    """Regression: DELETE-and-reinsert cascaded away all rule_variants."""
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    enc_id = _encodings(db_path)["statutes/26/32.yaml"]

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us', 'US', 'federal', 'u')"
    )
    conn.execute("INSERT INTO sessions (id, jurisdiction, name) VALUES ('s1','us','119')")
    conn.execute(
        "INSERT INTO bills (id, jurisdiction, session_id, chamber, number, source_url)"
        " VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'u')"
    )
    conn.execute(
        """
        INSERT INTO rule_variants (id, bill_id, encoding_id, file_path, tier,
                                   patched_rule_names, patched_yaml, proposed_by)
        VALUES ('v1', 'b1', ?, 'statutes/26/32.yaml', 'structural', '[]',
                'llm: yaml', 'llm')
        """,
        (enc_id,),
    )
    conn.commit()
    conn.close()

    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    row = conn.execute("SELECT patched_yaml FROM rule_variants WHERE id='v1'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "llm: yaml"


def test_vanished_file_is_removed(db_path, repo):
    (repo / "statutes" / "26" / "45.yaml").write_text(RULE_YAML)
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    assert set(_encodings(db_path)) == {"statutes/26/32.yaml", "statutes/26/45.yaml"}

    (repo / "statutes" / "26" / "45.yaml").unlink()
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    assert set(_encodings(db_path)) == {"statutes/26/32.yaml"}


def test_rules_and_atoms_refresh_without_duplicates(db_path, repo):
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    index_repo(repo, jurisdiction="us", repo_name="rulespec-us", db_path=db_path)
    conn = sqlite3.connect(db_path)
    n_rules = conn.execute("SELECT count(*) FROM encoded_rules").fetchone()[0]
    n_atoms = conn.execute("SELECT count(*) FROM encoded_rule_atoms").fetchone()[0]
    conn.close()
    assert n_rules == 1
    assert n_atoms == 1
