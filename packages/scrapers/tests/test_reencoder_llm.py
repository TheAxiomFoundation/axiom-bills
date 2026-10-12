"""Tests for the LLM-assisted Tier 3 reencoder.

The LLM call itself is mocked — these tests cover the deterministic
parts (prompt assembly, response parsing, output validation) so we
have correctness coverage without API roundtrips or flake.
"""

from __future__ import annotations

from datetime import date
import json
from textwrap import dedent

import httpx
import pytest
import yaml

from axiom_bills._common.reencoder_llm import (
    LLMProposal,
    ProposalRejected,
    build_prompt,
    parse_response,
    propose_via_anthropic,
    validate_proposal,
)


# ────────────────────────────────────────────────────────────────────
#  Fixtures
# ────────────────────────────────────────────────────────────────────

BASELINE = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/26/24
      summary: |-
        26 USC 24(e)(1): No credit shall be allowed ... unless the
        taxpayer includes the name and taxpayer identification number
        of such qualifying child on the return.
    rules:
      - name: ctc_child_identification_requirement_satisfied
        kind: derived
        source: 26 USC 24(e)(1)
        versions:
          - effective_from: '2018-01-01'
            formula: |-
              qualifying_child_tin_included_on_return
    """)

OP_TEXT = (
    "Section 24(e) of the Internal Revenue Code of 1986 is amended to "
    "read as follows: (e) Social Security Number Requirements.--(1) In "
    "general.--No credit shall be allowed under this section to a "
    "taxpayer with respect to any qualifying child unless the taxpayer "
    "includes the social security number of the taxpayer (in the case "
    "of a joint return, of both spouses) and of such child on the "
    "return of tax for the taxable year."
)


# ────────────────────────────────────────────────────────────────────
#  Prompt builder — deterministic input → expected substring presence
# ────────────────────────────────────────────────────────────────────


def test_prompt_includes_baseline_yaml():
    prompt = build_prompt(
        baseline_yaml=BASELINE,
        citation="26 USC 24(e)",
        bill_number="H.R.778",
        bill_op_text=OP_TEXT,
        effective_from=date(2025, 1, 28),
    )
    assert "format: rulespec/v1" in prompt
    assert "ctc_child_identification_requirement_satisfied" in prompt


def test_prompt_includes_citation_and_bill_id():
    prompt = build_prompt(
        baseline_yaml=BASELINE,
        citation="26 USC 24(e)",
        bill_number="H.R.778",
        bill_op_text=OP_TEXT,
        effective_from=date(2025, 1, 28),
    )
    assert "26 USC 24(e)" in prompt
    assert "H.R.778" in prompt


def test_prompt_includes_effective_date():
    prompt = build_prompt(
        baseline_yaml=BASELINE,
        citation="26 USC 24(e)",
        bill_number="H.R.778",
        bill_op_text=OP_TEXT,
        effective_from=date(2026, 7, 1),
    )
    assert "2026-07-01" in prompt


def test_prompt_demands_baseline_preservation():
    """The prompt must instruct the model to preserve historical versions."""
    prompt = build_prompt(
        baseline_yaml=BASELINE,
        citation="26 USC 24(e)",
        bill_number="H.R.778",
        bill_op_text=OP_TEXT,
        effective_from=date(2025, 1, 28),
    )
    assert "preserve" in prompt.lower() or "keep" in prompt.lower()
    # Must mention the existing effective_from so the model knows what
    # the historical anchor is.
    assert "2018-01-01" in prompt


# ────────────────────────────────────────────────────────────────────
#  Response parsing — strip Claude markdown fences and prose
# ────────────────────────────────────────────────────────────────────


def test_parse_response_extracts_fenced_yaml():
    response = (
        "Here's the proposed re-encoding:\n\n"
        "```yaml\nformat: rulespec/v1\nrules:\n  - name: foo\n    source: 26 USC 24\n```\n"
        "\nThis adds the new version while preserving baseline.\n"
    )
    out = parse_response(response)
    assert "format: rulespec/v1" in out
    assert "rules:" in out
    assert "```" not in out


def test_parse_response_accepts_unfenced_yaml():
    response = "format: rulespec/v1\nrules:\n  - name: foo\n    source: 26 USC 24\n"
    out = parse_response(response)
    assert "format: rulespec/v1" in out


def test_parse_response_handles_yaml_fence_tag():
    response = "```yml\nformat: rulespec/v1\n```"
    out = parse_response(response)
    assert "format: rulespec/v1" in out
    assert "```" not in out


# ────────────────────────────────────────────────────────────────────
#  Validation — reject malformed / unsafe proposals
# ────────────────────────────────────────────────────────────────────


def test_validate_accepts_well_formed_proposal():
    proposal = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/24
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_ssn_included_on_return
        """)
    out = validate_proposal(
        proposal, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28)
    )
    assert isinstance(out, LLMProposal)
    assert "ctc_child_identification_requirement_satisfied" in out.patched_yaml


def test_validate_accepts_unquoted_new_effective_date():
    proposal = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/24
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: 2025-01-28
                formula: |-
                  qualifying_child_ssn_included_on_return
        """)
    out = validate_proposal(
        proposal, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28)
    )
    assert isinstance(out, LLMProposal)


def test_validate_rejects_non_yaml():
    # YAML is permissive (lots of garbage parses as a scalar), so use a
    # genuinely malformed string.
    with pytest.raises(ProposalRejected):
        validate_proposal(
            "{ unclosed: [stuff",
            baseline_yaml=BASELINE,
            effective_from=date(2025, 1, 28),
        )


def test_validate_rejects_missing_rules_block():
    bad = "format: rulespec/v1\nmodule:\n  summary: hello\n"
    with pytest.raises(ProposalRejected, match="rules"):
        validate_proposal(bad, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28))


def test_validate_rejects_proposal_that_drops_baseline_version():
    """If the model replaces the historical version instead of appending,
    that loses historical-computation fidelity. Reject."""
    bad = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/24
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_ssn_included_on_return
        """)
    with pytest.raises(ProposalRejected, match="baseline.*version"):
        validate_proposal(bad, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28))


def test_validate_rejects_proposal_changing_historical_formula():
    """Historical versions must be preserved exactly apart from formatting."""
    bad = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/24
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_ssn_included_on_return
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_ssn_included_on_return
        """)
    with pytest.raises(ProposalRejected, match="historical version"):
        validate_proposal(bad, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28))


def test_validate_rejects_proposal_missing_new_effective_date():
    """Must contain a version with effective_from == effective_from arg."""
    bad = dedent("""\
        format: rulespec/v1
        module:
          source_verification:
            corpus_citation_path: us/statute/26/24
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
        """)
    with pytest.raises(ProposalRejected, match="effective_from"):
        validate_proposal(bad, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28))


def test_validate_rejects_proposal_dropping_baseline_rules():
    """A proposal that silently removes a rule the baseline had is suspect;
    bills almost never delete encoded rules. Reject so a human reviews."""
    baseline_two_rules = dedent("""\
        format: rulespec/v1
        rules:
          - name: rule_a
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  a
          - name: rule_b
            source: 26 USC 24(e)(2)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  b
        """)
    proposal = dedent("""\
        format: rulespec/v1
        rules:
          - name: rule_a
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  a
              - effective_from: '2025-01-28'
                formula: |-
                  a2
        """)
    with pytest.raises(ProposalRejected, match="dropped"):
        validate_proposal(
            proposal, baseline_yaml=baseline_two_rules, effective_from=date(2025, 1, 28)
        )


def test_validate_rejects_proposal_with_only_duplicate_new_versions():
    """If every "new version" the model adds has the same formula as
    the baseline, the proposal doesn't actually encode anything new.
    Reject so the variant stays "needs human review"."""
    proposal_yaml = dedent("""\
        format: rulespec/v1
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_tin_included_on_return
        """)
    with pytest.raises(ProposalRejected, match="semantically new"):
        validate_proposal(
            proposal_yaml, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28)
        )


def test_validate_strips_duplicate_new_version_when_some_rules_change():
    """Sibling rules that the LLM padded with identical-formula new
    versions get cleaned up; the variant carries only the rules that
    actually changed."""
    baseline = dedent("""\
        format: rulespec/v1
        rules:
          - name: real_change_rule
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
          - name: padding_rule
            source: 26 USC 24(e)(2)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  not taxpayer_identification_number_issued_after_return_due_date
        """)
    proposal = dedent("""\
        format: rulespec/v1
        rules:
          - name: real_change_rule
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_ssn_included_on_return
          - name: padding_rule
            source: 26 USC 24(e)(2)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  not taxpayer_identification_number_issued_after_return_due_date
              - effective_from: '2025-01-28'
                formula: |-
                  not taxpayer_identification_number_issued_after_return_due_date
        """)
    out = validate_proposal(
        proposal, baseline_yaml=baseline, effective_from=date(2025, 1, 28)
    )
    patched = yaml.safe_load(out.patched_yaml)
    by_name = {r["name"]: r for r in patched["rules"]}
    # Real change kept its new version.
    assert len(by_name["real_change_rule"]["versions"]) == 2
    # Padding rule was cleaned back to a single (baseline) version.
    assert len(by_name["padding_rule"]["versions"]) == 1
    assert by_name["padding_rule"]["versions"][0]["effective_from"] == "2018-01-01"


def test_validate_treats_whitespace_only_diff_as_duplicate():
    """A new version that differs only in whitespace from baseline is
    still a no-op semantically."""
    proposal_yaml = dedent("""\
        format: rulespec/v1
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: '2025-01-28'
                formula: |
                      qualifying_child_tin_included_on_return
        """)
    with pytest.raises(ProposalRejected, match="semantically new"):
        validate_proposal(
            proposal_yaml, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28)
        )


def test_validate_preserves_baseline_yaml_in_proposal_attr():
    """LLMProposal returned object should hold the original raw YAML
    for callers to render side-by-side."""
    proposal_yaml = dedent("""\
        format: rulespec/v1
        rules:
          - name: ctc_child_identification_requirement_satisfied
            kind: derived
            source: 26 USC 24(e)(1)
            versions:
              - effective_from: '2018-01-01'
                formula: |-
                  qualifying_child_tin_included_on_return
              - effective_from: '2025-01-28'
                formula: |-
                  qualifying_child_ssn_included_on_return
        """)
    out = validate_proposal(
        proposal_yaml, baseline_yaml=BASELINE, effective_from=date(2025, 1, 28)
    )
    assert out.baseline_yaml == BASELINE
    assert "qualifying_child_ssn_included_on_return" in out.patched_yaml


@pytest.fixture
def anthropic_transport(monkeypatch):
    """Exercise SDK serialization without sending requests to a provider."""
    import anthropic

    requests = []
    response = {
        "id": "msg_offline",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "content": [],
    }

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    with anthropic.Anthropic(
        api_key="offline-test-key",
        base_url="https://anthropic.invalid",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
        yield requests, response


def _propose(**kwargs):
    return propose_via_anthropic(
        baseline_yaml=BASELINE,
        citation="26 USC 24(e)",
        bill_number="H.R.778",
        bill_op_text=OP_TEXT,
        effective_from=date(2025, 1, 28),
        **kwargs,
    )


@pytest.mark.parametrize("model", [None, "custom-model-override"])
def test_propose_serializes_sonnet_request_and_parses_text_blocks(
    anthropic_transport, model
):
    requests, response = anthropic_transport
    proposal = yaml.safe_load(BASELINE)
    proposal["rules"][0]["versions"].append({
        "effective_from": "2025-01-28",
        "formula": "qualifying_child_ssn_included_on_return",
    })
    response["content"] = [
        {"type": "thinking", "thinking": "Checking the amendment.",
         "signature": "offline-signature"},
        {"type": "text", "text": "```yaml"},
        {"type": "text", "text": yaml.safe_dump(proposal) + "```"},
    ]

    result = _propose(model=model)

    assert len(requests) == 1
    request = requests[0]
    assert request["model"] == (model or "claude-sonnet-5-5")
    assert result.model == request["model"]
    assert result.baseline_yaml == BASELINE
    assert "qualifying_child_ssn_included_on_return" in result.patched_yaml
    assert request["output_config"] == {"effort": "low"}
    assert request["max_tokens"] == 16000
    assert not {"temperature", "top_p", "top_k", "thinking", "tool_choice"} & request.keys()
    assert request["messages"][-1]["role"] == "user"


@pytest.mark.parametrize(
    ("stop_reason", "error", "message"),
    [
        ("refusal", ProposalRejected, "refused"),
        ("max_tokens", RuntimeError, "truncated"),
    ],
)
def test_propose_rejects_refusal_and_truncation_before_parsing(
    anthropic_transport, stop_reason, error, message
):
    requests, response = anthropic_transport
    response["stop_reason"] = stop_reason
    response["content"] = [{"type": "text", "text": "{ unclosed: [stuff"}]

    with pytest.raises(error, match=message):
        _propose()

    assert len(requests) == 1


def test_propose_rejects_response_without_text(anthropic_transport):
    _, response = anthropic_transport
    proposal = yaml.safe_load(BASELINE)
    proposal["rules"][0]["versions"].append({
        "effective_from": "2025-01-28",
        "formula": "qualifying_child_ssn_included_on_return",
    })
    # A valid proposal that appears only in a thinking block must not be
    # parsed: the proposal is read from text blocks alone.
    response["content"] = [
        {"type": "thinking",
         "thinking": "```yaml\n" + yaml.safe_dump(proposal) + "```",
         "signature": "offline-signature"},
    ]

    with pytest.raises(ProposalRejected, match="not a YAML mapping"):
        _propose()
