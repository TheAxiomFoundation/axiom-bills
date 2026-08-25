"""Tests for the precompute-graph builder.

build_graph must derive everything from the repo itself — nodes from
the path-is-citation convention, edges from doc-level imports, per-rule
import atoms, and formula identifiers naming other modules — with no
program-specific section lists.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from textwrap import dedent

import pytest

from axiom_bills._common.rulespec_graph import build_graph, write_graph


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"

# 42 CFR 435.551 — imported by 552 (module import + import atom) and a
# formula reference; itself references the statute via an identifier.
REG_551_YAML = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/regulation/42/435/551
      summary: |-
        Applicable individual definition.
        Second line that must not leak into the label.
    rules:
      - name: applicable_individual
        kind: derived
        dtype: Boolean
        period: Month
        source: 42 CFR 435.551(a)
        versions:
          - effective_from: '0001-01-01'
            formula: |-
              enrolled and coverage_required_under_1396a_xx
""")

# 42 CFR 435.552 — module import + import atom + formula reference all
# pointing at 551 (the import must win), plus a deferred output.
REG_552_YAML = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/regulation/42/435/552
      summary: |-
        Demonstrating community engagement.
      deferred_outputs:
        - output: us:regulations/42-cfr/435/552#seasonal_worker_path
          source: "42 CFR 435.552(a)(7)"
          reason: Cited seasonal-worker definition unavailable.
    imports:
      - us:regulations/42-cfr/435/551#applicable_individual
    rules:
      - name: hours_requirement
        kind: parameter
        dtype: Count
        source: 42 CFR 435.552(a)(1)
        versions:
          - effective_from: '0001-01-01'
            formula: |-
              80
      - name: engagement_demonstrated
        kind: derived
        dtype: Boolean
        period: Month
        source: 42 CFR 435.552(a)
        metadata:
          proof:
            atoms:
              - path: versions[0].formula
                kind: import
                import:
                  target: us:regulations/42-cfr/435/551#applicable_individual
              - path: versions[0].formula
                kind: import
                import:
                  target: us:regulations/42-cfr/435/552#hours_requirement
        versions:
          - effective_from: '0001-01-01'
            formula: |-
              applicable_individual_under_435_551 and work_hours >= hours_requirement
""")

# 42 U.S.C. 1396a(xx) — referenced from 551's formula only.
STATUTE_YAML = dedent("""\
    format: rulespec/v1
    module:
      source_verification:
        corpus_citation_path: us/statute/42/1396a/xx
      summary: |-
        Community engagement requirement (statute).
    rules:
      - name: coverage_required
        kind: derived
        dtype: Boolean
        source: 42 USC 1396a(xx)
        versions:
          - effective_from: '0001-01-01'
            formula: |-
              true
""")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "rulespec-us-fixture"
    (root / "regulations" / "42-cfr" / "435").mkdir(parents=True)
    (root / "statutes" / "42" / "1396a").mkdir(parents=True)
    (root / "regulations" / "42-cfr" / "435" / "551.yaml").write_text(REG_551_YAML)
    (root / "regulations" / "42-cfr" / "435" / "552.yaml").write_text(REG_552_YAML)
    (root / "statutes" / "42" / "1396a" / "xx.yaml").write_text(STATUTE_YAML)
    # Repo-walk conventions shared with index-encodings: test fixtures
    # and dot-directories are skipped.
    (root / "regulations" / "42-cfr" / "435" / "551.test.yaml").write_text("x: 1")
    (root / ".github").mkdir()
    (root / ".github" / "ci.yaml").write_text("x: 1")
    return root


@pytest.fixture
def graph(repo):
    return build_graph(repo, "rulespec-us-fixture")


def _section(graph, node_id):
    return next(s for s in graph["sections"] if s["id"] == node_id)


def _edge(graph, src, dst):
    return next(
        (e for e in graph["edges"] if e["from"] == src and e["to"] == dst),
        None,
    )


def test_nodes_derived_from_paths(graph):
    assert {s["id"] for s in graph["sections"]} == {
        "42 CFR 435.551", "42 CFR 435.552", "42 USC 1396a(xx)",
    }
    node = _section(graph, "42 CFR 435.551")
    assert node["legalId"] == "42 CFR 435.551"
    assert node["label"] == "Applicable individual definition."
    assert node["group"] == "regulations/42-cfr/435"
    assert node["layer"] == "baseline"
    assert node["ruleCount"] == 1
    assert node["rules"][0] == {
        "name": "applicable_individual",
        "kind": "derived",
        "dtype": "Boolean",
        "period": "Month",
        "source": "42 CFR 435.551(a)",
    }
    assert _section(graph, "42 USC 1396a(xx)")["group"] == "statutes/42"


def test_groups_have_humanish_labels(graph):
    groups = {g["id"]: g["label"] for g in graph["groups"]}
    assert groups == {
        "regulations/42-cfr/435": "Regulations / 42 CFR / 435",
        "statutes/42": "Statutes / 42",
    }


def test_deferred_outputs_extracted(graph):
    deferred = _section(graph, "42 CFR 435.552")["deferred"]
    assert deferred == [{
        "output": "seasonal_worker_path",
        "reason": "Cited seasonal-worker definition unavailable.",
        "source": "42 CFR 435.552(a)(7)",
    }]
    assert _section(graph, "42 CFR 435.551")["deferred"] == []


def test_import_edge_from_module_imports_and_atoms(graph):
    edge = _edge(graph, "42 CFR 435.551", "42 CFR 435.552")
    assert edge is not None
    assert edge["type"] == "import"
    assert edge["via"] == "applicable_individual"


def test_reference_edge_from_formula_identifier(graph):
    edge = _edge(graph, "42 USC 1396a(xx)", "42 CFR 435.551")
    assert edge == {
        "from": "42 USC 1396a(xx)",
        "to": "42 CFR 435.551",
        "type": "reference",
    }


def test_import_wins_over_reference_and_edges_dedup(graph):
    # 552 both imports 551 and references it in a formula identifier:
    # exactly one edge survives, and it is the import.
    edges_551_552 = [
        e for e in graph["edges"]
        if e["from"] == "42 CFR 435.551" and e["to"] == "42 CFR 435.552"
    ]
    assert len(edges_551_552) == 1
    assert edges_551_552[0]["type"] == "import"


def test_no_self_edges(graph):
    # 552's second import atom targets its own hours_requirement rule.
    assert all(e["from"] != e["to"] for e in graph["edges"])


def test_meta_and_counts(graph):
    meta = graph["meta"]
    assert meta["program"] == "rulespec-us-fixture"
    # tmp_path is not a git checkout → provenance falls back to unknown.
    assert meta["generatedFrom"] == "rulespec-us-fixture@unknown"
    assert meta["counts"] == {
        "sections": 3,
        "rules": 4,
        "deferredOutputs": 1,
        "edges": 2,
    }
    assert meta["counts"]["edges"] == len(graph["edges"])


def test_write_graph_upserts_single_row(tmp_path, graph):
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript((MIGRATIONS / "059_encoding_graphs.sql").read_text())
    conn.close()

    write_graph("rulespec-us-fixture", graph, db_path=str(db_path))
    write_graph("rulespec-us-fixture", graph, db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT repo, graph, generated_from FROM encoding_graphs"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    repo_name, payload, generated_from = rows[0]
    assert repo_name == "rulespec-us-fixture"
    assert generated_from == "rulespec-us-fixture@unknown"
    assert json.loads(payload)["meta"]["counts"]["sections"] == 3
