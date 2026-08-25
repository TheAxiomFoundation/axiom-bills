"""Build a RuleSpec dependency-graph snapshot from a rulespec-* checkout.

Python port of guidance-impact-visualizer's generate-rulespec-graph.mjs,
generalized: nothing here knows about Medicaid, Part 435, or any other
specific program. Everything is derived from the repo itself:

  - one node per module YAML, id = the citation its path encodes
    (same path-is-citation convention `index-encodings` uses)
  - edges from doc-level ``imports:`` lists and per-rule
    ``metadata.proof.atoms[].import.target`` entries (type ``import``)
  - edges from formula identifiers that name another module's citation
    segments, e.g. ``..._section_435_119`` (type ``reference``) — the
    candidate patterns are built from the repo's own file paths rather
    than a hard-coded section regex
  - encoding gaps from each module's ``deferred_outputs``

The output dict matches the visualizer's ``RulespecGraph`` JSON contract
(meta/groups/sections/edges) so the ported web UI renders it unchanged.
Every node is ``layer: "baseline"``; the bill overlay is client-side.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .db import connect, DEFAULT_DB
from .encodings import parse_citation_from_path


# How much of the directory path identifies a node's group. Statutes
# group by title (statutes/26), regulations by part
# (regulations/42-cfr/435), policies by agency (policies/usda).
_GROUP_DEPTH = {"statute": 2, "regulation": 3, "policy": 2}


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _group_id(rel: Path, kind: str) -> str:
    parent = rel.parent.parts
    depth = _GROUP_DEPTH.get(kind, len(parent))
    return "/".join(parent[:depth]) or (parent[0] if parent else "other")


def _group_label(group_id: str) -> str:
    """Human-ish label for a path-derived group: title-cased components."""
    words = []
    for comp in group_id.split("/"):
        if comp.endswith("-cfr"):
            words.append(comp.removesuffix("-cfr") + " CFR")
        elif any(c.isalpha() for c in comp):
            words.append(comp.replace("-", " ").title())
        else:
            words.append(comp)
    return " / ".join(words)


def _rule_summaries(doc: dict) -> list[dict]:
    rules = doc.get("rules") or []
    if not isinstance(rules, list):
        return []
    out = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        out.append({
            "name": rule.get("name") or "",
            "kind": rule.get("kind") or "derived",
            "dtype": rule.get("dtype"),
            "period": rule.get("period"),
            "source": rule.get("source"),
        })
    return out


def _deferred_outputs(doc: dict) -> list[dict]:
    module = doc.get("module") or {}
    if not isinstance(module, dict):
        return []
    items = module.get("deferred_outputs") or []
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append({
            "output": str(item.get("output") or "").split("#")[-1],
            "reason": item.get("reason") or "",
            "source": item.get("source"),
        })
    return out


def _formulas_of(doc: dict) -> str:
    """All formula text in a module, for reference scanning."""
    chunks = []
    for rule in doc.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for version in rule.get("versions") or []:
            if isinstance(version, dict) and version.get("formula"):
                chunks.append(str(version["formula"]))
    return "\n".join(chunks)


def _atom_import_targets(doc: dict) -> list[str]:
    """Per-rule import-atom targets, e.g. 'us:regulations/42-cfr/435/551#rule'."""
    targets = []
    for rule in doc.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        atoms = (((rule.get("metadata") or {}).get("proof") or {})
                 .get("atoms")) or []
        if not isinstance(atoms, list):
            continue
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            imp = atom.get("import") or {}
            if isinstance(imp, dict) and imp.get("target"):
                targets.append(str(imp["target"]))
    return targets


def _split_target(target: str) -> tuple[str, str | None]:
    """'us:regulations/42-cfr/435/551#rule' → ('regulations/42-cfr/435/551', 'rule')."""
    path_part, _, fragment = target.partition("#")
    if ":" in path_part:
        path_part = path_part.split(":", 1)[1]
    return path_part.strip("/"), (fragment or None)


def _reference_pattern(rel: Path, kind: str) -> re.Pattern | None:
    """Regex matching formula identifiers that cite this module.

    Built from the module's own path segments — e.g.
    regulations/42-cfr/435/119.yaml → ``435[sep]119`` — so the scan works
    for any citation scheme in the repo without hard-coded section
    ranges. A single bare number would match far too much, so patterns
    always use at least two segments (title+section for a whole-section
    statute file), and very short combinations are skipped entirely —
    e.g. statutes/26/2/a would yield ``2_a``, which false-positives on
    unrelated subdivision chains like ``subsection_c_2_A_i``. Policies
    have no numeric citation; they only get edges via explicit imports.
    """
    parts = rel.parts
    leaf = parts[-1].removesuffix(".yaml")
    inner = (*parts[1:-1], leaf)
    if kind == "statute":
        # statutes/<title>/<section>[/<sub>...] — prefer section+subdivisions,
        # fall back to title+section when the file is a whole section.
        segments = list(inner[1:]) if len(inner) > 2 else list(inner)
    elif kind == "regulation":
        # regulations/<title>-cfr/<part>/<section>[...] — part onward.
        segments = list(inner[1:])
    else:
        return None
    if len(segments) < 2 or sum(len(s) for s in segments) < 4:
        return None
    joined = "[^0-9a-z]".join(re.escape(s) for s in segments)
    return re.compile(rf"(?<![0-9a-z]){joined}(?![0-9a-z])", re.IGNORECASE)


def _git_short_sha(repo_path: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_graph(repo_path: Path, repo_name: str) -> dict:
    """Walk a rulespec-* clone and derive its RulespecGraph payload."""
    # Same repo-walking conventions as encodings.index_repo: every
    # *.yaml except test fixtures and dot-directories, keyed by the
    # citation the path encodes; unrecognized paths are skipped.
    modules: list[dict] = []  # {citation, kind, rel, doc}
    seen_citations: set[str] = set()
    for yaml_path in sorted(repo_path.rglob("*.yaml")):
        if yaml_path.name.endswith(".test.yaml"):
            continue
        rel = yaml_path.relative_to(repo_path)
        if any(p.startswith(".") for p in rel.parts):
            continue
        parsed = parse_citation_from_path(rel)
        if parsed is None:
            continue
        kind, citation = parsed
        if citation in seen_citations:
            continue
        seen_citations.add(citation)
        # Node creation is best-effort like index_repo: a YAML that
        # fails to parse still gets its file-level node.
        try:
            with yaml_path.open() as f:
                doc = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            doc = None
        if not isinstance(doc, dict):
            doc = {}
        modules.append({
            "citation": citation, "kind": kind, "rel": rel, "doc": doc,
        })

    # path-is-citation lookup for resolving import targets like
    # "us:regulations/42-cfr/435/551#applicable_individual".
    citation_by_module_path = {
        str(m["rel"].with_suffix("")): m["citation"] for m in modules
    }
    patterns = [
        (m["citation"], pattern)
        for m in modules
        if (pattern := _reference_pattern(m["rel"], m["kind"])) is not None
    ]

    edge_map: dict[tuple[str, str], dict] = {}

    def add_edge(src: str, dst: str, edge_type: str, via: str | None = None):
        if src == dst:
            return
        key = (src, dst)
        # Imports are stronger evidence than formula references; keep the import.
        if key in edge_map and edge_map[key]["type"] == "import":
            return
        edge = {"from": src, "to": dst, "type": edge_type}
        if via:
            edge["via"] = via
        edge_map[key] = edge

    sections = []
    group_ids: dict[str, None] = {}  # insertion-ordered set
    for m in modules:
        doc = m["doc"]
        citation = m["citation"]
        module = doc.get("module") or {}
        if not isinstance(module, dict):
            module = {}
        rules = _rule_summaries(doc)
        group = _group_id(m["rel"], m["kind"])
        group_ids.setdefault(group)
        sections.append({
            "id": citation,
            "legalId": citation,
            "label": _first_line(module.get("summary")) or citation,
            "group": group,
            "layer": "baseline",
            "summary": str(module.get("summary") or "").strip(),
            "ruleCount": len(rules),
            "rules": rules,
            "deferred": _deferred_outputs(doc),
        })

        # (a) doc-level imports[] + (b) per-rule import atoms — an edge
        # from the imported module into this one.
        imports = doc.get("imports") or []
        module_targets = [str(t) for t in imports if t] if isinstance(imports, list) else []
        for target in module_targets + _atom_import_targets(doc):
            module_path, fragment = _split_target(target)
            dep = citation_by_module_path.get(module_path)
            if dep:
                add_edge(dep, citation, "import", via=fragment)

        # (c) formula identifiers naming another module's citation.
        formulas = _formulas_of(doc)
        if formulas:
            for dep, pattern in patterns:
                if dep != citation and pattern.search(formulas):
                    add_edge(dep, citation, "reference")

    edges = sorted(edge_map.values(), key=lambda e: (e["from"], e["to"]))
    sections.sort(key=lambda s: s["id"])
    return {
        "meta": {
            "program": repo_name,
            "generatedFrom": f"{repo_name}@{_git_short_sha(repo_path)}",
            "extractedAt": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "counts": {
                "sections": len(sections),
                "rules": sum(s["ruleCount"] for s in sections),
                "deferredOutputs": sum(len(s["deferred"]) for s in sections),
                "edges": len(edges),
            },
        },
        "groups": [
            {"id": gid, "label": _group_label(gid)} for gid in group_ids
        ],
        "sections": sections,
        "edges": edges,
    }


def write_graph(repo_name: str, graph: dict, db_path: str = DEFAULT_DB) -> None:
    """Upsert one graph snapshot row per repo into encoding_graphs."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO encoding_graphs (repo, graph, generated_from, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(repo) DO UPDATE SET
              graph = excluded.graph,
              generated_from = excluded.generated_from,
              generated_at = excluded.generated_at
            """,
            (
                repo_name,
                json.dumps(graph),
                graph["meta"]["generatedFrom"],
                graph["meta"]["extractedAt"],
            ),
        )
