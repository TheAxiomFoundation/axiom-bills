"""Tests for the encoder trigger queue (`trigger-encodes`).

The encoder itself is never invoked — --run tests monkeypatch
subprocess.Popen. Coverage:

* enqueue scan against a fixture DB covering all three reasons
  (needs_new_encoding backlog citations, superseded rule_variants,
  enacted bills touching encoded files),
* corpus_citation_path fill from encoded_rules.module_corpus_citation_path,
* dedup/idempotency, including that a dismissed row is never re-enqueued,
* --dry-run writing nothing,
* --run: env-var validation before anything runs, success and failure
  paths (status/detail/resolved_at), the no---apply invariant, --limit.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from axiom_bills._common import encode_queue
from axiom_bills._common.encode_queue import enqueue_scan, run_pending


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
# The full chain contains state-coverage seed files with (tolerated)
# duplicate-column errors; apply just the schema this path needs.
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "006_encoded_rules.sql",
    "007_rule_variants.sql",
    "008_rule_variant_provenance.sql",
    "056_variant_source_tracking.sql",
    "057_bill_touch_flags.sql",
    "058_needs_new_encoding.sql",
    "061_encode_queue.sql",
]


def _backlog_section(citation: str = "7 USC 2020(x)") -> dict:
    """A section amending inside an encoded program area with no
    existing rule file — the needs_new_encoding backlog signal."""
    return {
        "citation": citation,
        "encoding": None,
        "encoding_backlog": True,
        "applied_ops": [],
        "unapplied_ops": [{"kind": "add-end", "target": citation,
                           "needle": "", "payload": "New program."}],
    }


def _encoded_section(citation: str = "26 USC 32(a)",
                     file_path: str = "statutes/26/32.yaml") -> dict:
    return {
        "citation": citation,
        "encoding": {
            "repo": "rulespec-us", "kind": "statute",
            "citation": citation, "file_path": file_path,
        },
        "encoding_backlog": False,
        "applied_ops": [{"kind": "strike-insert", "target": citation,
                         "needle": "$600", "payload": "$750"}],
        "unapplied_ops": [],
    }


def _diffs(sections: list[dict]) -> str:
    return json.dumps({"source_text_sha256": "sha-v1", "sections": sections})


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "bills.sqlite"
    conn = sqlite3.connect(path)
    for name in SCHEMA_MIGRATIONS:
        conn.executescript((MIGRATIONS / name).read_text())
    conn.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us', 'US', 'federal', 'https://example.gov')"
    )
    conn.execute(
        "INSERT INTO sessions (id, jurisdiction, name) VALUES ('s1', 'us', '119')"
    )
    # b1: flagged needs_new_encoding, two sections but only one backlog.
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, diffs, needs_new_encoding)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1',
                ?, 1)
        """,
        (_diffs([_backlog_section(), _encoded_section()]),),
    )
    # b2: carries a superseded LLM variant against encoding e1.
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, current_status)
        VALUES ('b2', 'us', 's1', 'lower', 'HR2', 'https://example.gov/hr2',
                'in_committee')
        """
    )
    # b3: enacted and touches an encoded file.
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, current_status, diffs,
                           touches_rulespec)
        VALUES ('b3', 'us', 's1', 'lower', 'HR3', 'https://example.gov/hr3',
                'enacted', ?, 1)
        """,
        (_diffs([_encoded_section()]),),
    )
    conn.execute(
        """
        INSERT INTO axiom_encodings (id, jurisdiction, repo, kind, citation,
                                     file_path)
        VALUES ('e1', 'us', 'rulespec-us', 'statute', '26 USC 32(a)',
                'statutes/26/32.yaml')
        """
    )
    conn.execute(
        """
        INSERT INTO encoded_rules (id, encoding_id, rule_name, rule_source,
                                   module_corpus_citation_path)
        VALUES ('r1', 'e1', 'example_credit_amount', '26 USC 32(a)',
                'us/statute/26/32')
        """
    )
    conn.execute(
        """
        INSERT INTO rule_variants
            (id, bill_id, encoding_id, file_path, tier, patched_rule_names,
             note)
        VALUES ('v1', 'b2', 'e1', 'statutes/26/32.yaml', 'structural', '[]', ?)
        """,
        ("Superseded claude-x proposal: bill amendments or baseline "
         "changed since it was drafted.",),
    )
    conn.commit()
    conn.close()
    return str(path)


def _queue_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM encode_queue ORDER BY reason, citation"
        ).fetchall()
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────────
#  Enqueue scan
# ────────────────────────────────────────────────────────────────────

def test_scan_enqueues_all_three_reasons(db_path):
    counts = enqueue_scan(db_path, jurisdiction="us")
    assert counts["enqueued"] == 3
    assert counts["needs_new_encoding"] == 1
    assert counts["stale_variant"] == 1
    assert counts["enacted_touch"] == 1

    rows = {(r["bill_id"], r["reason"]): r for r in _queue_rows(db_path)}
    assert set(rows) == {
        ("b1", "needs_new_encoding"),
        ("b2", "stale_variant"),
        ("b3", "enacted_touch"),
    }
    assert rows[("b1", "needs_new_encoding")]["citation"] == "7 USC 2020(x)"
    assert rows[("b2", "stale_variant")]["citation"] == "26 USC 32(a)"
    assert rows[("b3", "enacted_touch")]["citation"] == "26 USC 32(a)"
    for row in rows.values():
        assert row["status"] == "pending"
        assert row["resolved_at"] is None


def test_scan_fills_corpus_citation_path_where_indexed(db_path):
    enqueue_scan(db_path)
    rows = {(r["bill_id"], r["reason"]): r for r in _queue_rows(db_path)}
    # Backlog citations have no encoded file yet — no corpus path.
    assert rows[("b1", "needs_new_encoding")]["corpus_citation_path"] is None
    # Encoded citations resolve through encoded_rules.
    assert rows[("b2", "stale_variant")]["corpus_citation_path"] == "us/statute/26/32"
    assert rows[("b3", "enacted_touch")]["corpus_citation_path"] == "us/statute/26/32"


def test_rescan_is_idempotent(db_path):
    enqueue_scan(db_path)
    counts = enqueue_scan(db_path)
    assert counts["enqueued"] == 0
    assert counts["existing"] == 3
    assert len(_queue_rows(db_path)) == 3


def test_dismissed_row_is_not_reenqueued(db_path):
    enqueue_scan(db_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE encode_queue SET status='dismissed',"
            " resolved_at=datetime('now') WHERE bill_id='b1'"
        )
    counts = enqueue_scan(db_path)
    assert counts["enqueued"] == 0
    rows = {(r["bill_id"], r["reason"]): r for r in _queue_rows(db_path)}
    assert rows[("b1", "needs_new_encoding")]["status"] == "dismissed"
    assert len(rows) == 3


def test_dry_run_writes_nothing(db_path, capsys):
    counts = enqueue_scan(db_path, dry_run=True)
    assert counts["enqueued"] == 3
    assert _queue_rows(db_path) == []
    err = capsys.readouterr().err
    assert "would enqueue" in err
    assert "7 USC 2020(x)" in err


def test_scan_respects_jurisdiction_filter(db_path):
    counts = enqueue_scan(db_path, jurisdiction="us-ny")
    assert counts["candidates"] == 0
    assert _queue_rows(db_path) == []


def test_unenacted_touching_bill_is_not_enqueued(db_path):
    # b1's second section touches an encoded file, but b1 isn't
    # enacted/signed — no enacted_touch row for it.
    enqueue_scan(db_path)
    rows = [r for r in _queue_rows(db_path)
            if r["bill_id"] == "b1" and r["reason"] == "enacted_touch"]
    assert rows == []


# ────────────────────────────────────────────────────────────────────
#  --run (monkeypatched subprocess)
# ────────────────────────────────────────────────────────────────────

RUN_ENV = {
    "AXIOM_CORPUS_PATH": "/checkouts/axiom-corpus",
    "AXIOM_POLICY_REPO_PATH": "/checkouts/rulespec-us",
    "AXIOM_RULES_ENGINE_PATH": "/checkouts/axiom-rules-engine",
}


class FakePopen:
    """Stands in for subprocess.Popen: canned stdout/stderr streams and
    exit code, records every invocation on the class."""

    calls: list[list[str]] = []
    returncode_next = 0
    stderr_next = ""

    def __init__(self, cmd, stdout=None, stderr=None, text=None, bufsize=None):
        type(self).calls.append(list(cmd))
        self.stdout = io.StringIO("encoder progress line\n")
        self.stderr = io.StringIO(type(self).stderr_next)
        self.returncode = type(self).returncode_next

    def wait(self):
        return self.returncode


@pytest.fixture
def fake_popen(monkeypatch):
    FakePopen.calls = []
    FakePopen.returncode_next = 0
    FakePopen.stderr_next = ""
    monkeypatch.setattr(encode_queue.subprocess, "Popen", FakePopen)
    # The runner preflights the binary; pretend it is installed.
    monkeypatch.setattr(
        encode_queue.shutil, "which",
        lambda name: "/usr/local/bin/axiom-encode",
    )
    return FakePopen


def _run_env(tmp_path) -> dict[str, str]:
    return dict(RUN_ENV, AXIOM_ENCODE_OUTPUT=str(tmp_path / "encode-out"))


def test_run_requires_env_vars_before_running_anything(db_path, fake_popen,
                                                       tmp_path):
    enqueue_scan(db_path)
    incomplete = dict(RUN_ENV)
    del incomplete["AXIOM_RULES_ENGINE_PATH"]
    with pytest.raises(RuntimeError, match="AXIOM_RULES_ENGINE_PATH"):
        run_pending(db_path, env=incomplete)
    assert fake_popen.calls == []  # nothing ran
    assert all(r["status"] == "pending" for r in _queue_rows(db_path))


def test_run_requires_encoder_binary_before_running_anything(
        db_path, fake_popen, tmp_path, monkeypatch):
    """A machine without axiom-encode on PATH fails up front, before the
    first invocation — not with a traceback mid-queue."""
    enqueue_scan(db_path)
    monkeypatch.setattr(encode_queue.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="axiom-encode"):
        run_pending(db_path, env=_run_env(tmp_path))
    assert fake_popen.calls == []
    assert all(r["status"] == "pending" for r in _queue_rows(db_path))


def test_run_success_marks_ran_and_never_applies(db_path, fake_popen, tmp_path):
    enqueue_scan(db_path)
    counts = run_pending(db_path, env=_run_env(tmp_path))
    assert counts == {"pending": 3, "ran": 3, "failed": 0}
    assert len(fake_popen.calls) == 3

    for cmd in fake_popen.calls:
        assert cmd[:2] == ["axiom-encode", "encode"]
        assert "--apply" not in cmd
        assert cmd[cmd.index("--corpus-path") + 1] == RUN_ENV["AXIOM_CORPUS_PATH"]
        assert cmd[cmd.index("--policy-repo-path") + 1] == \
            RUN_ENV["AXIOM_POLICY_REPO_PATH"]
        assert cmd[cmd.index("--axiom-rules-engine-path") + 1] == \
            RUN_ENV["AXIOM_RULES_ENGINE_PATH"]
        out_dir = Path(cmd[cmd.index("--output") + 1])
        assert out_dir.parent == tmp_path / "encode-out"
        assert out_dir.is_dir()

    for row in _queue_rows(db_path):
        assert row["status"] == "ran"
        assert row["detail"].startswith("exit 0; output ")
        assert row["id"] in row["detail"]  # per-row output dir
        assert row["resolved_at"] is not None


def test_run_failure_records_exit_and_stderr_tail(db_path, fake_popen,
                                                  tmp_path):
    enqueue_scan(db_path)
    fake_popen.returncode_next = 2
    fake_popen.stderr_next = "warming up\nboom: citation not in corpus\n"
    counts = run_pending(db_path, env=_run_env(tmp_path), limit=1)
    assert counts["ran"] == 0
    assert counts["failed"] == 1

    failed = [r for r in _queue_rows(db_path) if r["status"] == "failed"]
    assert len(failed) == 1
    assert "exit 2" in failed[0]["detail"]
    assert "boom: citation not in corpus" in failed[0]["detail"]
    assert failed[0]["resolved_at"] is not None
    # The other rows stay pending for a later run.
    assert sum(r["status"] == "pending" for r in _queue_rows(db_path)) == 2


def test_run_limit_caps_invocations(db_path, fake_popen, tmp_path):
    enqueue_scan(db_path)
    counts = run_pending(db_path, env=_run_env(tmp_path), limit=2)
    assert counts["pending"] == 3
    assert counts["ran"] == 2
    assert len(fake_popen.calls) == 2
    assert sum(r["status"] == "pending" for r in _queue_rows(db_path)) == 1


def test_run_skips_non_pending_rows(db_path, fake_popen, tmp_path):
    enqueue_scan(db_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute("UPDATE encode_queue SET status='dismissed'"
                    " WHERE bill_id='b1'")
    counts = run_pending(db_path, env=_run_env(tmp_path))
    assert counts["pending"] == 2
    assert len(fake_popen.calls) == 2
