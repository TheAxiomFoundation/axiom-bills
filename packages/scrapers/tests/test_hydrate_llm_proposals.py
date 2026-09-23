"""Tests for hydrate-variants (Supabase → local SQLite) and scheme changes.

A remote LLM proposal is copied down only when its fingerprint matches
the local row. When it does not, the local row is stamped superseded so
the encode queue sees the change, except when the remote fingerprint
was written under an older fingerprint scheme: that cannot show the
bill changed, so the row is left for redrafting with no stale signal.
Supabase is never contacted.
"""

from __future__ import annotations

import sqlite3

from axiom_bills._common import supabase_sync
from axiom_bills._common.variants import FINGERPRINT_SCHEME

from .test_hydrate_reconciliations import (
    SCHEMA_MIGRATIONS,
    _make_db as _make_reconcile_db,
    _patch_remote,
)

# rule_variants gains proposed_by / proposed_model later than the
# reconciliation tests need.
MIGRATIONS = [*SCHEMA_MIGRATIONS, "008_rule_variant_provenance.sql"]


def _make_db(tmp_path) -> str:
    return _make_reconcile_db(tmp_path, migrations=MIGRATIONS)

CURRENT = f"{FINGERPRINT_SCHEME}:" + "a" * 64


def _add_variant(db_path: str, fingerprint: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO axiom_encodings (id, jurisdiction, repo, kind, citation,"
        " file_path) VALUES ('e1', 'us', 'rulespec-us', 'statute',"
        " '26 USC 32(a)', 'statutes/26/32.yaml')"
    )
    conn.execute(
        """
        INSERT INTO rule_variants (id, bill_id, encoding_id, file_path, tier,
                                   patched_rule_names, effective_from,
                                   source_ops_fingerprint)
        VALUES ('v1', 'b1', 'e1', 'statutes/26/32.yaml', 'structural',
                '[]', '2026-01-01', ?)
        """,
        (fingerprint,),
    )
    conn.commit()
    conn.close()


def _variant(db_path: str) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM rule_variants").fetchone()
    finally:
        conn.close()


def _remote(fingerprint: str) -> list[dict]:
    return [{"bill_id": "remote-b1", "file_path": "statutes/26/32.yaml",
             "patched_yaml": "x: 1", "proposed_by": "llm",
             "proposed_model": "claude", "source_ops_fingerprint": fingerprint}]


def test_matching_fingerprint_is_hydrated(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    _add_variant(db_path, CURRENT)
    _patch_remote(monkeypatch, _remote(CURRENT))

    counts = supabase_sync.hydrate_llm_proposals(db_path)

    assert counts["hydrated"] == 1
    assert _variant(db_path)["patched_yaml"] == "x: 1"


def test_changed_inputs_under_the_current_scheme_mark_superseded(
        tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    _add_variant(db_path, CURRENT)
    _patch_remote(monkeypatch, _remote(f"{FINGERPRINT_SCHEME}:" + "b" * 64))

    counts = supabase_sync.hydrate_llm_proposals(db_path)

    assert counts["stale_remote"] == 1
    v = _variant(db_path)
    assert v["patched_yaml"] is None
    assert "Superseded" in v["note"]


def test_older_scheme_fingerprint_raises_no_stale_signal(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    _add_variant(db_path, CURRENT)
    _patch_remote(monkeypatch, _remote("c" * 64))  # pre-scheme, no prefix

    counts = supabase_sync.hydrate_llm_proposals(db_path)

    assert counts["older_scheme"] == 1
    assert counts["stale_remote"] == 0
    v = _variant(db_path)
    assert v["patched_yaml"] is None
    assert not v["note"]
