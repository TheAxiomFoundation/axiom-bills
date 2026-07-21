"""Tests for the agentic bill↔encoding reconciliation stage.

The LLM is never called — a fake client is injected. Coverage:

* fingerprint stability and skip logic (unchanged inputs → no calls),
* section selection (encoding match + ≥1 op) against a fixture DB,
* payload validation: enum rejection + retry path, and persistent
  failure recording nothing,
* upsert uniqueness on (bill_id, section_citation).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from axiom_bills._common.reconcile_llm import (
    candidate_sections,
    reconcile_all,
    reconcile_for_bill,
    section_fingerprint,
    valid_verdict,
)


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
# The full chain contains state-coverage seed files with (tolerated)
# duplicate-column errors; apply just the schema this path needs.
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "005_corpus_provisions.sql",
    "006_encoded_rules.sql",
    "007_rule_variants.sql",
    "008_rule_variant_provenance.sql",
    "056_variant_source_tracking.sql",
    "060_bill_reconciliations.sql",
]


def _section(citation: str = "26 USC 32(a)", *,
             encoding: dict | None = None,
             applied_ops: list | None = None,
             unapplied_ops: list | None = None,
             before: str = "The credit is $600.",
             after: str = "The credit is $750.") -> dict:
    return {
        "citation": citation,
        "heading": "Earned income credit",
        "current_text": before,
        "applied_text": after,
        "encoding": encoding,
        "applied_ops": applied_ops or [],
        "unapplied_ops": unapplied_ops or [],
    }


def _encoded_section(**kwargs) -> dict:
    kwargs.setdefault("encoding", {
        "repo": "rulespec-us", "kind": "statute",
        "citation": "26 USC 32(a)", "file_path": "statutes/26/32.yaml",
    })
    kwargs.setdefault("applied_ops", [{
        "kind": "strike-insert", "target": "26 USC 32(a)",
        "needle": "$600", "payload": "$750",
        "raw": "by striking \"$600\" and inserting \"$750\"",
    }])
    return _section(**kwargs)


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
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, diffs)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1', ?)
        """,
        (_diffs([_encoded_section()]),),
    )
    conn.execute(
        """
        INSERT INTO axiom_encodings (id, jurisdiction, repo, kind, citation, file_path)
        VALUES ('e1', 'us', 'rulespec-us', 'statute', '26 USC 32(a)',
                'statutes/26/32.yaml')
        """
    )
    conn.execute(
        """
        INSERT INTO encoded_rules (id, encoding_id, rule_name, rule_source)
        VALUES ('r1', 'e1', 'example_credit_amount', '26 USC 32(a)')
        """
    )
    conn.execute(
        """
        INSERT INTO encoded_rule_atoms (id, rule_id, atom_path, atom_kind, text)
        VALUES ('a1', 'r1', 'versions[0].formula', 'amount', '600')
        """
    )
    conn.execute(
        """
        INSERT INTO corpus_provisions (citation_path, citation, jurisdiction,
                                       doc_type, heading, body)
        VALUES ('us/statute/26/32', '26 USC 32', 'us', 'statute',
                'Earned income credit', 'The credit is $600.')
        """
    )
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def conn(db_path):
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ────────────────────────────────────────────────────────────────────
#  Fake Anthropic client
# ────────────────────────────────────────────────────────────────────

class _ToolUse:
    type = "tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "tu1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class _Resp:
    def __init__(self, blocks: list):
        self.content = blocks


def _verdict_resp(tool_input: dict) -> _Resp:
    return _Resp([_ToolUse("record_verdict", tool_input)])


VALID_VERDICT = {
    "status": "conflicts",
    "divergence": "Credit amount rises from $600 to $750.",
    "materiality": "changes-eligibility",
    "action": "encode-in-model",
    "confidence": "high",
    "rationale": "The bill strikes $600 and inserts $750.",
    "upstreamQuote": "$600",
    "downstreamQuote": "$750",
}


class FakeMessages:
    """Yields queued responses; optionally repeats the last one forever
    (for persistent-failure loops). Raises if called with none left."""

    def __init__(self, responses: list, repeat_last: bool = False):
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("unexpected LLM call — no responses queued")
        if self._repeat_last and len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list, repeat_last: bool = False):
        self.messages = FakeMessages(responses, repeat_last)

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls


# ────────────────────────────────────────────────────────────────────
#  Fingerprint
# ────────────────────────────────────────────────────────────────────

def test_fingerprint_is_stable():
    assert section_fingerprint(_encoded_section()) == \
        section_fingerprint(_encoded_section())


def test_fingerprint_changes_with_ops():
    changed = _encoded_section(applied_ops=[{
        "kind": "strike-insert", "target": "26 USC 32(a)",
        "needle": "$600", "payload": "$900",
    }])
    assert section_fingerprint(_encoded_section()) != \
        section_fingerprint(changed)


def test_fingerprint_changes_when_op_moves_to_unapplied():
    op = {"kind": "strike-insert", "target": "26 USC 32(a)",
          "needle": "$600", "payload": "$750"}
    applied = _encoded_section(applied_ops=[op], unapplied_ops=[])
    unapplied = _encoded_section(applied_ops=[], unapplied_ops=[op])
    assert section_fingerprint(applied) != section_fingerprint(unapplied)


def test_fingerprint_changes_with_text_and_file_path():
    base = section_fingerprint(_encoded_section())
    assert section_fingerprint(_encoded_section(after="Different text.")) != base
    other_file = _encoded_section(encoding={
        "repo": "rulespec-us", "kind": "statute",
        "citation": "26 USC 32(a)", "file_path": "statutes/26/other.yaml",
    })
    assert section_fingerprint(other_file) != base


# ────────────────────────────────────────────────────────────────────
#  Section selection
# ────────────────────────────────────────────────────────────────────

def test_candidate_sections_require_encoding_and_ops():
    encoded_with_ops = _encoded_section()
    encoded_no_ops = _encoded_section(applied_ops=[], unapplied_ops=[])
    ops_no_encoding = _section(
        citation="7 USC 2015",
        encoding=None,
        applied_ops=[{"kind": "strike-insert", "target": "7 USC 2015",
                      "needle": "x", "payload": "y"}],
    )
    picked = candidate_sections({"sections": [
        encoded_with_ops, encoded_no_ops, ops_no_encoding,
    ]})
    assert picked == [encoded_with_ops]


def test_candidate_sections_accept_unapplied_only():
    section = _encoded_section(applied_ops=[], unapplied_ops=[{
        "kind": "amend-to-read", "target": "26 USC 32(a)",
        "needle": "", "payload": "new text", "note": "could not apply",
    }])
    assert candidate_sections({"sections": [section]}) == [section]


def test_dry_run_selects_only_qualifying_bills(db_path):
    with sqlite3.connect(db_path) as raw:
        # A bill whose only section has no encoding: never selected.
        raw.execute(
            """
            INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                               source_url, diffs)
            VALUES ('b2', 'us', 's1', 'lower', 'HR2',
                    'https://example.gov/hr2', ?)
            """,
            (_diffs([_section(citation="7 USC 2015", encoding=None,
                              applied_ops=[{"kind": "strike-insert",
                                            "target": "7 USC 2015",
                                            "needle": "x", "payload": "y"}])]),),
        )
    counts = reconcile_all(db_path, jurisdiction="us", dry_run=True)
    assert counts["would_analyze"] == 1
    assert counts["sections"] == 1
    # Dry run never opens a client and writes nothing.
    with sqlite3.connect(db_path) as raw:
        n = raw.execute("SELECT count(*) FROM bill_reconciliations").fetchone()[0]
    assert n == 0


# ────────────────────────────────────────────────────────────────────
#  Verdict validation
# ────────────────────────────────────────────────────────────────────

def test_valid_verdict_rejects_bad_enums():
    assert valid_verdict(VALID_VERDICT)
    for key in ("status", "materiality", "action", "confidence"):
        bad = dict(VALID_VERDICT, **{key: "bogus"})
        assert not valid_verdict(bad), key
    assert not valid_verdict(None)
    assert not valid_verdict(dict(VALID_VERDICT, rationale="", divergence=""))


def test_invalid_enum_then_retry_records_row(conn):
    # billVsLaw analyst: first response has a bad status, the corrective
    # tool_result makes the loop call again and the second is valid.
    # modelVsLaw analyst: valid immediately.
    fake = FakeClient([
        _verdict_resp(dict(VALID_VERDICT, status="bogus")),
        _verdict_resp(VALID_VERDICT),
        _verdict_resp(dict(VALID_VERDICT, status="missing",
                           action="encode-in-model")),
    ])
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts == {"sections": 1, "analyzed": 1, "skipped": 0, "failed": 0}
    assert len(fake.calls) == 3

    row = conn.execute(
        "SELECT payload, fingerprint, model FROM bill_reconciliations"
        " WHERE bill_id='b1'"
    ).fetchone()
    payload = json.loads(row["payload"])
    assert payload["section"] == "26 USC 32(a)"
    assert payload["topic"] == "Earned income credit"
    assert payload["billVsLaw"]["status"] == "conflicts"
    assert payload["modelVsLaw"]["status"] == "missing"
    assert row["fingerprint"] == section_fingerprint(_encoded_section())


def test_persistent_invalid_records_nothing(conn):
    fake = FakeClient(
        [_verdict_resp(dict(VALID_VERDICT, materiality="huge"))],
        repeat_last=True,
    )
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts["failed"] == 1
    assert counts["analyzed"] == 0
    n = conn.execute("SELECT count(*) FROM bill_reconciliations").fetchone()[0]
    assert n == 0
    # 2 attempts × 5 turns for the billVsLaw analyst; modelVsLaw skipped.
    assert len(fake.calls) == 10


# ────────────────────────────────────────────────────────────────────
#  Skip logic + upsert uniqueness
# ────────────────────────────────────────────────────────────────────

def test_unchanged_fingerprint_skips_llm(conn):
    fake = FakeClient([_verdict_resp(VALID_VERDICT)] * 2)
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts["analyzed"] == 1

    # Re-run: same inputs, so no client call may happen at all.
    def _no_client():
        raise AssertionError("client requested on an unchanged section")
    counts = reconcile_for_bill(conn, "b1", get_client=_no_client)
    assert counts == {"sections": 1, "analyzed": 0, "skipped": 1, "failed": 0}


def test_changed_inputs_update_row_in_place(conn):
    fake = FakeClient([_verdict_resp(VALID_VERDICT)] * 2)
    reconcile_for_bill(conn, "b1", get_client=lambda: fake)

    # The bill text changes: new ops → new fingerprint → recompute.
    new_section = _encoded_section(applied_ops=[{
        "kind": "strike-insert", "target": "26 USC 32(a)",
        "needle": "$600", "payload": "$900",
    }], after="The credit is $900.")
    conn.execute("UPDATE bills SET diffs=? WHERE id='b1'",
                 (_diffs([new_section]),))

    fake2 = FakeClient([
        _verdict_resp(dict(VALID_VERDICT,
                           divergence="Credit rises to $900.")),
        _verdict_resp(VALID_VERDICT),
    ])
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake2)
    assert counts["analyzed"] == 1

    rows = conn.execute(
        "SELECT payload, fingerprint FROM bill_reconciliations"
        " WHERE bill_id='b1'"
    ).fetchall()
    assert len(rows) == 1  # UNIQUE(bill_id, section_citation) upsert
    payload = json.loads(rows[0]["payload"])
    assert payload["billVsLaw"]["divergence"] == "Credit rises to $900."
    assert rows[0]["fingerprint"] == section_fingerprint(new_section)


def test_limit_caps_analyzed_sections(conn):
    two_sections = [
        _encoded_section(),
        _encoded_section(citation="26 USC 32(b)"),
    ]
    conn.execute("UPDATE bills SET diffs=? WHERE id='b1'",
                 (_diffs(two_sections),))
    fake = FakeClient([_verdict_resp(VALID_VERDICT)] * 2)
    counts = reconcile_for_bill(conn, "b1", limit=1, get_client=lambda: fake)
    assert counts["analyzed"] == 1
    assert len(fake.calls) == 2
