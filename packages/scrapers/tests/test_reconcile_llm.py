"""Tests for the agentic bill↔encoding reconciliation stage.

The LLM is never called — a fake client is injected. Coverage:

* fingerprint stability and skip logic (unchanged inputs → no calls),
* section selection (encoding match + ≥1 op) against a fixture DB,
* payload validation: required fields, types, enums, and truncation;
  retry paths and persistent failure recording a layer-less failure sentinel,
* lookup-tool citation normalization (the LLM's '26 U.S.C. 32' /
  'IRC section 32' forms must still match the normalized store),
* upsert uniqueness on (bill_id, section_citation).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from anthropic import Anthropic

from axiom_bills._common.reconcile_llm import (
    _resolve_provision,
    _resolve_rules,
    _run_analyst,
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
    "057_bill_touch_flags.sql",
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
                           source_url, diffs, touches_rulespec)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1',
                ?, 1)
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
    def __init__(self, blocks: list, stop_reason: str = "tool_use"):
        self.content = blocks
        self.stop_reason = stop_reason


def _verdict_resp(tool_input: dict) -> _Resp:
    return _Resp([_ToolUse("record_verdict", tool_input)])


VALID_VERDICT = {
    "status": "conflicts",
    "divergence": "Credit amount rises from $600 to $750.",
    "materiality": "changes-eligibility",
    "action": "encode-in-model",
    "confidence": "high",
    "rationale": "The bill strikes $600 and inserts $750.",
    "ambiguity": None,
    "upstreamQuote": "$600",
    "downstreamQuote": "$750",
}


FINAL_NUDGE = "Research is complete. Call record_verdict now."


def _snapshot(value):
    """Copy dicts and lists all the way down, keeping response blocks
    as-is, so a later in-place edit of an already-sent turn shows up as
    a difference between recorded requests."""
    if isinstance(value, dict):
        return {k: _snapshot(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_snapshot(v) for v in value]
    return value


class FakeMessages:
    """Yields queued responses; optionally repeats the last one forever
    (for persistent-failure loops). Raises if called with none left."""

    def __init__(self, responses: list, repeat_last: bool = False):
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.calls: list[dict] = []

    def create(self, **kwargs):
        # Snapshot the request as sent; the agent keeps appending to (and
        # must never edit) its original message list.
        self.calls.append(_snapshot(kwargs))
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


def test_candidate_sections_merge_same_citation():
    """Two bill sections amending the same target citation collapse to
    one candidate — otherwise they fight over the UNIQUE(bill_id,
    section_citation) row and re-analyze each other forever."""
    first = _encoded_section()
    second = _encoded_section(applied_ops=[{
        "kind": "strike-insert", "target": "26 USC 32(a)",
        "needle": "taxable year", "payload": "calendar year",
    }])
    merged = candidate_sections({"sections": [first, second]})
    assert len(merged) == 1
    m = merged[0]
    # First section supplies texts + applied ops; the second section's
    # applied op is carried as unapplied (its edit is not reflected in
    # the first section's applied text) with an explanatory note.
    assert m["applied_ops"] == first["applied_ops"]
    assert [op["needle"] for op in m["unapplied_ops"]] == ["taxable year"]
    assert m["unapplied_ops"][0]["note"]
    # The merged fingerprint covers both sections' ops, and merging is
    # deterministic across runs.
    assert section_fingerprint(m) != section_fingerprint(first)
    again = candidate_sections({"sections": [first, second]})
    assert section_fingerprint(again[0]) == section_fingerprint(m)


def test_dry_run_selects_only_qualifying_bills(db_path):
    with sqlite3.connect(db_path) as raw:
        # A bill whose only section has no encoding: never selected
        # (touches_rulespec stays 0, matching its diffs).
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
        # touches_rulespec=0 despite encoded-looking diffs: the
        # precomputed flag is the selection predicate — the diffs blob
        # of a non-touching bill is never even parsed.
        raw.execute(
            """
            INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                               source_url, diffs, touches_rulespec)
            VALUES ('b3', 'us', 's1', 'lower', 'HR3',
                    'https://example.gov/hr3', ?, 0)
            """,
            (_diffs([_encoded_section()]),),
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

def test_sdk_serializes_sonnet_request_and_preserves_thinking(conn):
    """Exercise the installed SDK without allowing any network traffic."""
    thinking = {
        "type": "thinking", "thinking": "", "signature": "test-signature",
    }
    lookup = {
        "type": "tool_use", "id": "lookup1", "name": "lookup_provision",
        "input": {"citation": "26 USC 32"},
    }
    verdict = dict(VALID_VERDICT, ambiguity=None, upstreamQuote=None)
    replies = [
        [thinking, lookup],
        [{"type": "tool_use", "id": "verdict1", "name": "record_verdict",
          "input": verdict}],
    ]
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={
            "id": f"msg{len(requests)}", "type": "message",
            "role": "assistant", "model": payload["model"],
            "content": replies.pop(0), "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    with Anthropic(
        api_key="test-key", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        result = _run_analyst(
            client, conn, "b1", system="Analyze the amendment.",
            user="Compare the credit amounts.", model="claude-sonnet-5-5",
            max_turns=2,
        )

    assert result == {key: value for key, value in verdict.items()
                      if value is not None}
    assert len(requests) == 2
    for request in requests:
        assert request["model"] == "claude-sonnet-5-5"
        assert request["max_tokens"] == 16000
        assert request["output_config"] == {"effort": "medium"}
        assert request["tool_choice"] == {"type": "auto"}
        assert "MUST call record_verdict" in request["system"][0]["text"]
        assert not {"temperature", "top_p", "top_k", "thinking"} & request.keys()
        tool = next(t for t in request["tools"]
                    if t["name"] == "record_verdict")
        assert tool["strict"] is True
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for field in ("ambiguity", "upstreamQuote", "downstreamQuote"):
            assert schema["properties"][field]["type"] == ["string", "null"]

    # The last turn keeps the same system prompt and tool set (editing
    # either invalidates the replayed thinking block); the nudge to
    # record the verdict follows the tool results instead.
    assert len(requests[0]["tools"]) == 3
    assert requests[1]["tools"] == requests[0]["tools"]
    assert requests[1]["system"] == requests[0]["system"]
    history = requests[1]["messages"]
    assert history[:1] == requests[0]["messages"]
    assert history[1] == {"role": "assistant", "content": [thinking, lookup]}
    assert history[2]["content"][0]["tool_use_id"] == "lookup1"
    assert "The credit is $600." in history[2]["content"][0]["content"]
    assert history[2]["content"][-1] == {"type": "text", "text": FINAL_NUDGE}


def _nudges(messages: list) -> int:
    return sum(
        1
        for m in messages if isinstance(m["content"], list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("text") == FINAL_NUDGE
    )


@pytest.mark.parametrize("max_turns", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("research_turns", [0, 1, 2, 3, 4, 5])
def test_analyst_history_is_append_only(conn, max_turns, research_turns):
    """For every turn budget and every point at which the verdict
    arrives (or never does): each request in an attempt resends the
    same system prompt and tools and extends the previous request's
    messages without editing them, and the final-turn nudge appears
    once, just before the attempt's last request."""
    responses = [
        _Resp([_ToolUse("lookup_provision", {"citation": "26 USC 32"},
                        block_id=f"tu{i}")])
        for i in range(research_turns)
    ] + [_verdict_resp(VALID_VERDICT)]
    fake = FakeClient(responses, repeat_last=True)
    result = _run_analyst(
        fake, conn, "b1", system="Analyze.", user="Compare.",
        model="claude-sonnet-5-5", max_turns=max_turns, attempts=1,
    )
    calls = fake.calls
    if research_turns < max_turns:
        assert result == {key: value for key, value in VALID_VERDICT.items()
                          if value is not None}
        assert len(calls) == research_turns + 1
    else:
        assert result is None
        assert len(calls) == max_turns
    for prev, cur in zip(calls, calls[1:]):
        assert cur["system"] == calls[0]["system"]
        assert cur["tools"] == calls[0]["tools"]
        assert cur["tool_choice"] == {"type": "auto"}
        assert cur["messages"][:len(prev["messages"])] == prev["messages"]
    expected_nudge = 1 if len(calls) == max_turns and max_turns > 1 else 0
    assert _nudges(calls[-1]["messages"]) == expected_nudge
    if expected_nudge:
        assert calls[-1]["messages"][-1]["content"][-1]["text"] == FINAL_NUDGE


def test_missing_final_verdict_retries_after_bounded_research(conn):
    fake = FakeClient([
        _Resp([_ToolUse("lookup_provision", {"citation": "26 USC 32"})]),
        _Resp([SimpleNamespace(type="text", text="Analysis without a verdict.")],
              stop_reason="end_turn"),
        _verdict_resp(VALID_VERDICT),
    ])
    result = _run_analyst(
        fake, conn, "b1", system="Analyze.", user="Compare.",
        model="claude-sonnet-5-5", max_turns=2,
    )
    assert result == {key: value for key, value in VALID_VERDICT.items()
                      if value is not None}
    assert len(fake.calls) == 3
    assert fake.calls[1]["tools"] == fake.calls[0]["tools"]
    assert fake.calls[1]["messages"][-1]["content"][-1] == {
        "type": "text", "text": FINAL_NUDGE,
    }
    # One fresh attempt follows the bounded research attempt.
    assert fake.calls[2]["messages"] == fake.calls[0]["messages"]


def test_missing_verdict_retries_once_then_records_failure(conn, capsys):
    fake = FakeClient([_Resp([], stop_reason="end_turn")], repeat_last=True)
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts == {"sections": 1, "analyzed": 0, "skipped": 0, "failed": 1}
    assert len(fake.calls) == 2
    assert "FAILED: no valid record_verdict after 2 attempts" in capsys.readouterr().err
    payload = json.loads(conn.execute(
        "SELECT payload FROM bill_reconciliations WHERE bill_id='b1'",
    ).fetchone()["payload"])
    assert payload["failed"] is True
    assert "billVsLaw" not in payload and "modelVsLaw" not in payload


def test_refusal_is_handled_before_reading_content(conn, capsys):
    # Deliberately no content attribute: inspecting it on refusal is a bug.
    fake = FakeClient([SimpleNamespace(stop_reason="refusal")])
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts == {"sections": 1, "analyzed": 0, "skipped": 0, "failed": 1}
    assert len(fake.calls) == 1
    assert "analyst refused the request" in capsys.readouterr().err
    payload = json.loads(conn.execute(
        "SELECT payload FROM bill_reconciliations WHERE bill_id='b1'",
    ).fetchone()["payload"])
    assert payload["failed"] is True
    assert "billVsLaw" not in payload and "modelVsLaw" not in payload


def test_truncation_is_handled_before_reading_content(conn, capsys):
    # Truncated content must never be inspected, accepted, or replayed.
    fake = FakeClient([SimpleNamespace(stop_reason="max_tokens")],
                      repeat_last=True)
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts == {"sections": 1, "analyzed": 0, "skipped": 0, "failed": 1}
    assert len(fake.calls) == 2
    assert fake.calls[1]["messages"] == fake.calls[0]["messages"]
    assert "analyst response truncated" in capsys.readouterr().err
    payload = json.loads(conn.execute(
        "SELECT payload FROM bill_reconciliations WHERE bill_id='b1'",
    ).fetchone()["payload"])
    assert payload["failed"] is True
    assert "billVsLaw" not in payload and "modelVsLaw" not in payload


@pytest.mark.parametrize("issue", [
    "truncated-incomplete", "truncated-complete", "truncated-lookup",
    "incomplete", "bad-type",
])
@pytest.mark.parametrize("recovers", [True, False])
def test_sdk_invalid_verdict_retries_or_records_failure(conn, issue, recovers):
    """Real SDK, offline transport: malformed results never reach storage."""
    thinking = {
        "type": "thinking", "thinking": "", "signature": "test-signature",
    }
    lookup = {
        "type": "tool_use", "id": "lookup1", "name": "lookup_provision",
        "input": {"citation": "26 USC 32"},
    }
    bad_input = dict(VALID_VERDICT)
    if issue in ("truncated-incomplete", "incomplete"):
        for key in ("rationale", "ambiguity", "upstreamQuote", "downstreamQuote"):
            bad_input.pop(key)
    elif issue == "bad-type":
        bad_input["upstreamQuote"] = 17
    truncated = issue.startswith("truncated-")
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        call = len(requests)
        if call == 1:
            content, stop_reason = [thinking, lookup], "tool_use"
        else:
            invalid = call == 2 or not recovers
            block = {
                "type": "tool_use", "id": f"verdict{call}",
                "name": "record_verdict",
                "input": bad_input if invalid else VALID_VERDICT,
            }
            if invalid and issue == "truncated-lookup":
                # Executing this incomplete lookup would raise on .strip().
                block.update(name="lookup_provision", input={"citation": 17})
            content = [block]
            stop_reason = "max_tokens" if invalid and truncated else "tool_use"
        return httpx.Response(200, json={
            "id": f"msg{call}", "type": "message", "role": "assistant",
            "model": payload["model"], "content": content,
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 16000},
        })

    with Anthropic(
        api_key="test-key", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        counts = reconcile_for_bill(conn, "b1", get_client=lambda: client)

    assert counts == {
        "sections": 1, "analyzed": int(recovers), "skipped": 0,
        "failed": int(not recovers),
    }
    assert len(requests) == (4 if recovers else (3 if truncated else 10))
    if truncated:
        # Discard the entire truncated attempt, including prior research.
        assert requests[2]["messages"] == requests[0]["messages"]
    else:
        # Complete but invalid tool input receives corrective feedback.
        assert requests[2]["messages"][:3] == requests[1]["messages"]
        assert "Rejected:" in requests[2]["messages"][-1]["content"][0]["content"]
    bill_requests = requests[:-1] if recovers else requests
    for request in bill_requests:
        assert request["system"] == requests[0]["system"]
        assert request["tools"] == requests[0]["tools"]
    row = conn.execute(
        "SELECT payload, fingerprint FROM bill_reconciliations WHERE bill_id='b1'",
    ).fetchone()
    payload = json.loads(row["payload"])
    assert row["fingerprint"] == section_fingerprint(_encoded_section())
    if recovers:
        expected = {key: value for key, value in VALID_VERDICT.items()
                    if value is not None}
        assert payload["billVsLaw"] == payload["modelVsLaw"] == expected
        assert "failed" not in payload
    else:
        assert payload["failed"] is True
        assert "billVsLaw" not in payload and "modelVsLaw" not in payload
        assert reconcile_for_bill(conn, "b1", get_client=lambda: None) == {
            "sections": 1, "analyzed": 0, "skipped": 1, "failed": 0,
        }


def test_valid_verdict_rejects_bad_enums():
    assert valid_verdict(VALID_VERDICT)
    for key in ("status", "materiality", "action", "confidence"):
        bad = dict(VALID_VERDICT, **{key: "bogus"})
        assert not valid_verdict(bad), key
    assert not valid_verdict(None)
    assert not valid_verdict(dict(VALID_VERDICT, rationale="", divergence=""))


@pytest.mark.parametrize("field", list(VALID_VERDICT))
def test_valid_verdict_rejects_missing_required_fields(field):
    incomplete = dict(VALID_VERDICT)
    incomplete.pop(field)
    assert not valid_verdict(incomplete)


@pytest.mark.parametrize("field", list(VALID_VERDICT))
@pytest.mark.parametrize("bad_value", [True, 17, [], {}])
def test_valid_verdict_rejects_invalid_field_types(field, bad_value):
    assert not valid_verdict(dict(VALID_VERDICT, **{field: bad_value}))


@pytest.mark.parametrize("field", [
    "status", "divergence", "materiality", "action", "confidence", "rationale",
])
def test_valid_verdict_rejects_null_required_strings(field):
    assert not valid_verdict(dict(VALID_VERDICT, **{field: None}))


def test_valid_verdict_accepts_nullable_details():
    assert valid_verdict(dict(VALID_VERDICT, ambiguity=None,
                              upstreamQuote=None, downstreamQuote=None))


def test_valid_verdict_rejects_unexpected_fields():
    assert not valid_verdict(dict(VALID_VERDICT, unexpected="extra"))


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


def test_persistent_invalid_records_failure_sentinel(conn):
    fake = FakeClient(
        [_verdict_resp(dict(VALID_VERDICT, materiality="huge"))],
        repeat_last=True,
    )
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake)
    assert counts["failed"] == 1
    assert counts["analyzed"] == 0
    # 2 attempts × 5 turns for the billVsLaw analyst; modelVsLaw skipped.
    assert len(fake.calls) == 10

    # The failure is recorded as a layer-less sentinel keyed by the
    # section's fingerprint: invisible to the web (which drops rows
    # lacking billVsLaw/modelVsLaw) but enough for the skip to fire.
    row = conn.execute(
        "SELECT payload, fingerprint FROM bill_reconciliations"
        " WHERE bill_id='b1'"
    ).fetchone()
    payload = json.loads(row["payload"])
    assert payload["failed"] is True
    assert "billVsLaw" in payload["error"]
    assert "billVsLaw" not in payload and "modelVsLaw" not in payload
    assert row["fingerprint"] == section_fingerprint(_encoded_section())

    # Re-run with unchanged inputs: the sentinel satisfies the
    # fingerprint skip, so no attempts × max_turns re-burn.
    def _no_client():
        raise AssertionError("client requested on an unchanged section")
    counts = reconcile_for_bill(conn, "b1", get_client=_no_client)
    assert counts == {"sections": 1, "analyzed": 0, "skipped": 1, "failed": 0}


def test_failure_after_input_change_evicts_stale_verdicts(conn):
    """When the fingerprint changed but both analyst attempts fail, the
    old row's verdicts must not keep serving as current — the sentinel
    upsert replaces them under the NEW fingerprint."""
    fake = FakeClient([_verdict_resp(VALID_VERDICT)] * 2)
    reconcile_for_bill(conn, "b1", get_client=lambda: fake)

    new_section = _encoded_section(applied_ops=[{
        "kind": "strike-insert", "target": "26 USC 32(a)",
        "needle": "$600", "payload": "$900",
    }], after="The credit is $900.")
    conn.execute("UPDATE bills SET diffs=? WHERE id='b1'",
                 (_diffs([new_section]),))

    # Every response is empty (no tool use): both attempts give up.
    fake2 = FakeClient([_Resp([])], repeat_last=True)
    counts = reconcile_for_bill(conn, "b1", get_client=lambda: fake2)
    assert counts["failed"] == 1

    rows = conn.execute(
        "SELECT payload, fingerprint FROM bill_reconciliations"
        " WHERE bill_id='b1'"
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload"])
    assert payload["failed"] is True
    assert "billVsLaw" not in payload  # stale verdicts gone
    assert rows[0]["fingerprint"] == section_fingerprint(new_section)


# ────────────────────────────────────────────────────────────────────
#  Lookup-tool citation normalization
# ────────────────────────────────────────────────────────────────────

def test_resolve_provision_normalizes_citation_drift(conn):
    # The store holds '26 USC 32'; the LLM's format drift must still
    # find it instead of misreporting the provision as unavailable.
    for drift in ("26 U.S.C. 32", "IRC section 32", "IRC § 32"):
        assert "The credit is $600." in _resolve_provision(conn, drift), drift


def test_resolve_provision_falls_back_to_parent_citation_path(conn):
    # A provision whose stored citation string doesn't prefix-match is
    # still reachable through the corpus_client-style citation_path
    # parent walk.
    conn.execute(
        """
        INSERT INTO corpus_provisions (citation_path, citation,
                                       jurisdiction, doc_type, heading, body)
        VALUES ('us/statute/26/24', 'Section 24 of the IRC', 'us', 'statute',
                'Child tax credit', 'The CTC text.')
        """
    )
    assert "The CTC text." in _resolve_provision(conn, "26 U.S.C. 24(h)(2)")


def test_resolve_rules_normalizes_citation_drift(conn):
    # axiom_encodings holds '26 USC 32(a)'; the LLM's drifted forms
    # must not make the analyst wrongly report "not encoded".
    for drift in ("26 U.S.C. 32(a)", "IRC section 32(a)", "IRC § 32(a)"):
        out = _resolve_rules(conn, None, drift)
        assert "example_credit_amount" in out, drift


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


def test_limit_counts_failed_sections_too(conn):
    """A persistent verdict failure must consume the cap, not walk every
    remaining candidate — otherwise an API/model regression makes the
    hourly spend unbounded despite --limit."""
    two_sections = [
        _encoded_section(),
        _encoded_section(citation="26 USC 32(b)"),
    ]
    conn.execute("UPDATE bills SET diffs=? WHERE id='b1'",
                 (_diffs(two_sections),))
    # Every response is empty (no tool use): each analyst attempt gives
    # up immediately, so section 1 fails after 2 calls (2 attempts of
    # the billVsLaw analyst; modelVsLaw never runs).
    fake = FakeClient([_Resp([])], repeat_last=True)
    counts = reconcile_for_bill(conn, "b1", limit=1, get_client=lambda: fake)
    assert counts["failed"] == 1
    assert counts["analyzed"] == 0
    # Section 2 was never attempted: the failure consumed the limit.
    assert len(fake.calls) == 2
