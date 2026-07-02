"""Tests for the engine-test harness (with a stub axiom-encode)."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from axiom_bills._common.variant_verify import verify_all


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
SCHEMA = ["001_init.sql", "004_encodings_and_citations.sql",
          "006_encoded_rules.sql", "007_rule_variants.sql",
          "008_rule_variant_provenance.sql", "056_variant_source_tracking.sql"]


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    for name in SCHEMA:
        conn.executescript((MIGRATIONS / name).read_text())
    conn.execute("INSERT OR IGNORE INTO jurisdictions (code,name,level,source_url)"
                 " VALUES ('us','US','federal','u')")
    conn.execute("INSERT INTO sessions (id,jurisdiction,name) VALUES ('s1','us','119')")
    conn.execute("INSERT INTO bills (id,jurisdiction,session_id,chamber,number,source_url)"
                 " VALUES ('b1','us','s1','lower','HR1','u')")
    conn.execute("INSERT INTO axiom_encodings (id,jurisdiction,repo,kind,citation,file_path)"
                 " VALUES ('e1','us','rulespec-us','statute','26 USC 32','statutes/26/32.yaml')")
    conn.execute("""INSERT INTO rule_variants
        (id,bill_id,encoding_id,file_path,tier,patched_rule_names,patched_yaml,note)
        VALUES ('v1','b1','e1','statutes/26/32.yaml','structural','[]','patched: yaml','old note')""")
    conn.commit(); conn.close()

    root = tmp_path / "rulespec" / "us"
    (root / "statutes" / "26").mkdir(parents=True)
    (root / "statutes" / "26" / "32.yaml").write_text("baseline: yaml")
    (root / "statutes" / "26" / "32.test.yaml").write_text("- name: t")
    return db, root, tmp_path


def _stub(tmp_path, exit_code: int, message: str) -> str:
    stub = tmp_path / "axiom-encode-stub"
    stub.write_text(f"#!/bin/sh\necho '{message}'\nexit {exit_code}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return str(stub)


def _note(db):
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT note FROM rule_variants WHERE id='v1'").fetchone()[0]
    conn.close()
    return n


def test_pass_stamps_note(env, tmp_path):
    db, root, tp = env
    counts = verify_all(db, rulespec_root=str(root),
                        encode_bin=_stub(tp, 0, "tests passed: 1 file(s)"))
    assert counts == {"patched": 1, "passed": 1, "failed": 0, "no_tests": 0}
    assert _note(db) == "old note | engine-test: pass"


def test_fail_stamps_reason_and_is_idempotent(env, tmp_path):
    db, root, tp = env
    bad = _stub(tp, 1, "versioned derived formulas are not supported yet")
    verify_all(db, rulespec_root=str(root), encode_bin=bad)
    verify_all(db, rulespec_root=str(root), encode_bin=bad)  # re-run replaces, not appends
    note = _note(db)
    assert note.count("engine-test:") == 1
    assert "versioned derived formulas" in note


def test_missing_companion_tests_counted(env, tmp_path):
    db, root, tp = env
    (root / "statutes" / "26" / "32.test.yaml").unlink()
    counts = verify_all(db, rulespec_root=str(root), encode_bin=_stub(tp, 0, "ok"))
    assert counts["no_tests"] == 1
