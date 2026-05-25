"""Index local rulespec-* repos into the axiom_encodings table.

A RuleSpec file's *path* is its citation address:

  statutes/26/32.yaml         → 26 USC 32
  statutes/26/32/a/1.yaml     → 26 USC 32(a)(1)
  statutes/26/45A.yaml        → 26 USC 45A
  regulations/7-cfr/273/3.yaml → 7 CFR 273.3
  policies/usda/snap/fy-2026-cola/...   → policy (no statutory citation)

We treat the path as authoritative — same convention axiom-encode uses
when it lays files down via `--apply`. If the path encoding ever changes,
this module is the one place to update.

We also parse each YAML's rules + proof atoms into encoded_rules and
encoded_rule_atoms tables. The proof atoms are how Pipeline B detects
"this bill's amendment overlaps text that a rule is grounded in" — see
axiom-architecture's docs/corpus-encoding-mapping.md.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import yaml

from .db import connect, DEFAULT_DB


def _statute_citation(parts: tuple[str, ...]) -> str | None:
    """statutes/<title>/<section>[/<sub>/<para>/...].yaml → '<title> USC <section>(...)'."""
    if not parts:
        return None
    title = parts[0]
    if not title.isdigit():
        return None
    if len(parts) == 1:
        return f"{title} USC"
    section = parts[1]
    suffix = ""
    for part in parts[2:]:
        suffix += f"({part})"
    return f"{title} USC {section}{suffix}"


def _regulation_citation(parts: tuple[str, ...]) -> str | None:
    """regulations/<title>-cfr/<part>/<section>.yaml → '<title> CFR <part>.<section>'."""
    if len(parts) < 3:
        return None
    title_part = parts[0]
    if not title_part.endswith("-cfr"):
        return None
    title = title_part.removesuffix("-cfr")
    if not title.isdigit():
        return None
    part_no = parts[1]
    section = parts[2]
    suffix = ""
    for extra in parts[3:]:
        suffix += f"({extra})"
    return f"{title} CFR {part_no}.{section}{suffix}"


def _policy_citation(parts: tuple[str, ...]) -> str | None:
    """policies/<agency>/.../<name>.yaml → 'policy:<agency>/...' for traceability."""
    if not parts:
        return None
    return "policy:" + "/".join(parts)


def parse_citation_from_path(repo_relative: Path) -> tuple[str, str] | None:
    """Return (kind, citation) for a YAML path inside a rulespec-* repo.

    Returns None for unrecognized paths (e.g. dotfiles, top-level READMEs).
    """
    parts = repo_relative.parts
    if not parts or not parts[-1].endswith(".yaml"):
        return None
    # Strip the .yaml from the leaf.
    leaf = parts[-1].removesuffix(".yaml")
    inner = (*parts[1:-1], leaf)
    top = parts[0]

    if top == "statutes":
        cite = _statute_citation(inner)
        return ("statute", cite) if cite else None
    if top == "regulations":
        cite = _regulation_citation(inner)
        return ("regulation", cite) if cite else None
    if top == "policies":
        cite = _policy_citation(inner)
        return ("policy", cite) if cite else None
    return None


def _index_rules(conn, encoding_id: str, yaml_doc: dict,
                 default_corpus_path: str | None) -> tuple[int, int]:
    """Parse rules + proof atoms out of a YAML doc into encoded_rules.

    The module-level `source_verification.corpus_citation_path` is
    inherited as the default for each rule's atoms, since most atoms
    just say `corpus_citation_path: us/statute/26/213` (the parent
    section row) and the granular `source` lives on the rule itself.
    """
    rules_written = 0
    atoms_written = 0
    rules = yaml_doc.get("rules") or []
    if not isinstance(rules, list):
        return 0, 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO encoded_rules
              (id, encoding_id, rule_name, rule_kind, rule_source,
               rule_dtype, module_corpus_citation_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                encoding_id,
                rule.get("name") or "",
                rule.get("kind"),
                rule.get("source") or "",
                rule.get("dtype"),
                default_corpus_path,
            ),
        )
        rules_written += 1

        atoms = (((rule.get("metadata") or {}).get("proof") or {}).get("atoms")) or []
        if not isinstance(atoms, list):
            continue
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            src = atom.get("source") or {}
            if not isinstance(src, dict):
                continue
            text = src.get("text")
            corpus_path = src.get("corpus_citation_path") or default_corpus_path
            # Skip atoms with no quoted text — they exist (e.g. when the
            # atom is just a citation pointer) but contribute nothing to
            # the bill-overlap match.
            if not text:
                continue
            conn.execute(
                """
                INSERT INTO encoded_rule_atoms
                  (id, rule_id, atom_path, atom_kind, corpus_citation_path, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    rule_id,
                    atom.get("path"),
                    atom.get("kind"),
                    corpus_path,
                    text,
                ),
            )
            atoms_written += 1
    return rules_written, atoms_written


def index_repo(repo_path: Path, jurisdiction: str, repo_name: str,
               db_path: str = DEFAULT_DB) -> dict[str, int]:
    """Walk a rulespec-* clone and upsert its YAML inventory + rules."""
    counts = {
        "scanned": 0, "indexed": 0, "skipped": 0,
        "rules": 0, "atoms": 0,
    }
    with connect(db_path) as conn:
        # Replace the slice for this repo so renames don't leave stale rows.
        # encoded_rules and encoded_rule_atoms cascade via ON DELETE CASCADE.
        conn.execute(
            "DELETE FROM axiom_encodings WHERE jurisdiction = ? AND repo = ?",
            (jurisdiction, repo_name),
        )
        for yaml_path in repo_path.rglob("*.yaml"):
            if yaml_path.name.endswith(".test.yaml"):
                continue
            if any(p.startswith(".") for p in yaml_path.relative_to(repo_path).parts):
                continue

            counts["scanned"] += 1
            rel = yaml_path.relative_to(repo_path)
            parsed = parse_citation_from_path(rel)
            if parsed is None:
                counts["skipped"] += 1
                continue
            kind, citation = parsed
            encoding_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT OR REPLACE INTO axiom_encodings
                  (id, jurisdiction, repo, kind, citation, file_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (encoding_id, jurisdiction, repo_name, kind, citation, str(rel)),
            )
            counts["indexed"] += 1

            # Parse the YAML for rules + proof atoms. Failures here
            # don't abort the indexing — the file-level entry is the
            # baseline; rule-level enrichment is best-effort.
            try:
                with yaml_path.open() as f:
                    doc = yaml.safe_load(f)
            except (yaml.YAMLError, OSError):
                continue
            if not isinstance(doc, dict):
                continue
            module = doc.get("module") or {}
            corpus_path = (
                ((module.get("source_verification") or {})
                 .get("corpus_citation_path"))
            )
            r, a = _index_rules(conn, encoding_id, doc, corpus_path)
            counts["rules"] += r
            counts["atoms"] += a
    return counts
