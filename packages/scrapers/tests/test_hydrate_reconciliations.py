"""Tests for hydrate-reconciliations (Supabase → local SQLite).

CI starts from a fresh SQLite each run, so without hydration the
`reconcile` fingerprint skip never sees prior rows and re-analyzes the
same sections hourly. Supabase is never contacted — the client and the
remote lookups are monkeypatched.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from axiom_bills._common import supabase_sync
from axiom_bills._common.reconcile_llm import section_fingerprint


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "007_rule_variants.sql",             # 056 alters it
    "056_variant_source_tracking.sql",   # adds bills.diffs
    "057_bill_touch_flags.sql",          # adds bills.touches_rulespec
    "060_bill_reconciliations.sql",
]


def _encoded_section(citation: str = "26 USC 32(a)") -> dict:
    return {
        "citation": citation,
        "heading": "Earned income credit",
        "current_text": "The credit is $600.",
        "applied_text": "The credit is $750.",
        "encoding": {
            "repo": "rulespec-us", "kind": "statute",
            "citation": citation, "file_path": "statutes/26/32.yaml",
        },
        "applied_ops": [{"kind": "strike-insert", "target": citation,
                         "needle": "$600", "payload": "$750"}],
        "unapplied_ops": [],
    }


PAYLOAD = {
    "topic": "Earned income credit",
    "section": "26 USC 32(a)",
    "billVsLaw": {"status": "conflicts", "divergence": "x",
                  "materiality": "changes-eligibility",
                  "action": "encode-in-model", "confidence": "high",
                  "rationale": "y"},
    "modelVsLaw": {"status": "missing", "divergence": "x",
                   "materiality": "changes-eligibility",
                   "action": "encode-in-model", "confidence": "high",
                   "rationale": "y"},
}


def _make_db(tmp_path, migrations=SCHEMA_MIGRATIONS) -> str:
    path = tmp_path / "bills.sqlite"
    conn = sqlite3.connect(path)
    for name in migrations:
        conn.executescript((MIGRATIONS / name).read_text())
    conn.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us', 'US', 'federal', 'https://example.gov')"
    )
    conn.execute(
        "INSERT INTO sessions (id, jurisdiction, name) VALUES ('s1', 'us', '119')"
    )
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, diffs, touches_rulespec)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1',
                ?, 1)
        """,
        (json.dumps({"sections": [_encoded_section()]}),),
    )
    conn.commit()
    conn.close()
    return str(path)


class _FakeClientCM:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


def _patch_remote(monkeypatch, remote_rows: list[dict]) -> None:
    monkeypatch.setattr(supabase_sync, "_client", lambda: _FakeClientCM())
    # Mirror the REAL signatures: _remote_session_ids returns
    # (mapping, known_remote_sessions) and _remote_bill_ids requires the
    # known-sessions set — a looser mock here previously hid a
    # tuple-treated-as-dict crash in hydrate_reconciliations.
    monkeypatch.setattr(
        supabase_sync, "_remote_session_ids",
        lambda client, rows: (
            {r["id"]: f"remote-{r['id']}" for r in rows},
            {f"remote-{r['id']}" for r in rows},
        ),
    )
    monkeypatch.setattr(
        supabase_sync, "_remote_bill_ids",
        lambda client, rows, known_remote_sessions: {
            r["id"]: f"remote-{r['id']}" for r in rows
        },
    )
    monkeypatch.setattr(
        supabase_sync, "_remote_rows_by_in",
        lambda client, table, *, select, column, values, chunk=100: remote_rows,
    )


def _local_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM bill_reconciliations").fetchall()
    finally:
        conn.close()


def test_hydrates_row_with_matching_fingerprint(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    fingerprint = section_fingerprint(_encoded_section())
    _patch_remote(monkeypatch, [{
        "bill_id": "remote-b1",
        "section_citation": "26 USC 32(a)",
        "payload": PAYLOAD,                    # JSONB arrives as a dict
        "fingerprint": fingerprint,
        "model": "claude-x",
        "computed_at": "2026-07-20T01:02:03+00:00",
    }])

    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 1, "hydrated": 1, "stale_remote": 0}

    rows = _local_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["bill_id"] == "b1"           # local id, not the remote one
    assert rows[0]["section_citation"] == "26 USC 32(a)"
    assert rows[0]["fingerprint"] == fingerprint
    assert rows[0]["model"] == "claude-x"
    assert json.loads(rows[0]["payload"]) == PAYLOAD

    # The hydrated row now satisfies reconcile's fingerprint skip, so a
    # second hydration has no candidates and never opens a client.
    def _boom():
        raise AssertionError("client opened with nothing to hydrate")
    monkeypatch.setattr(supabase_sync, "_client", _boom)
    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 0, "hydrated": 0, "stale_remote": 0}


def test_stale_remote_fingerprint_is_not_hydrated(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    _patch_remote(monkeypatch, [{
        "bill_id": "remote-b1",
        "section_citation": "26 USC 32(a)",
        "payload": PAYLOAD,
        "fingerprint": "an-older-fingerprint",
        "model": "claude-x",
        "computed_at": "2026-07-20T01:02:03+00:00",
    }])

    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 1, "hydrated": 0, "stale_remote": 1}
    assert _local_rows(db_path) == []


def test_hydrates_failure_sentinel_rows(tmp_path, monkeypatch):
    # reconcile stores a layer-less {"failed": true} sentinel when both
    # analyst attempts fail; it must round-trip through hydration like
    # any row so the fingerprint skip fires on fresh CI databases too.
    db_path = _make_db(tmp_path)
    fingerprint = section_fingerprint(_encoded_section())
    sentinel = {
        "topic": "Earned income credit",
        "section": "26 USC 32(a)",
        "failed": True,
        "error": "no valid billVsLaw verdict after retries",
    }
    _patch_remote(monkeypatch, [{
        "bill_id": "remote-b1",
        "section_citation": "26 USC 32(a)",
        "payload": sentinel,
        "fingerprint": fingerprint,
        "model": "claude-x",
        "computed_at": "2026-07-20T01:02:03+00:00",
    }])

    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 1, "hydrated": 1, "stale_remote": 0}
    rows = _local_rows(db_path)
    assert len(rows) == 1
    assert json.loads(rows[0]["payload"]) == sentinel


def test_skips_bills_not_touching_rulespec(tmp_path, monkeypatch):
    # touches_rulespec is precomputed with exactly the
    # candidate_sections predicate — a non-touching bill's diffs blob
    # is never parsed, so it yields no candidates.
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE bills SET touches_rulespec = 0 WHERE id = 'b1'")
    conn.commit()
    conn.close()

    def _boom():
        raise AssertionError("client opened with nothing to hydrate")
    monkeypatch.setattr(supabase_sync, "_client", _boom)

    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 0, "hydrated": 0, "stale_remote": 0}


def test_missing_remote_row_is_left_for_reconcile(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    _patch_remote(monkeypatch, [])
    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 1, "hydrated": 0, "stale_remote": 0}
    assert _local_rows(db_path) == []


def test_tolerates_pre_060_db_without_table(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path, migrations=SCHEMA_MIGRATIONS[:-1])

    def _boom():
        raise AssertionError("client opened despite missing table")
    monkeypatch.setattr(supabase_sync, "_client", _boom)

    counts = supabase_sync.hydrate_reconciliations(db_path)
    assert counts == {"candidates": 0, "hydrated": 0, "stale_remote": 0}
