"""axiom-bills read API (SQLite-backed).

Strictly read-only. The scraper CLI is the only writer.

Routes:
  GET /health
  GET /jurisdictions
  GET /jurisdictions/{code}
  GET /jurisdictions/{code}/bills?status=&limit=&offset=
  GET /bills/{bill_id}
  GET /recent?status=enacted|signed|enrolled  (cross-jurisdiction)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# A bill version is the textual artifact produced by a particular action
# (Introduced in House → IH printing; Passed House → EH printing; etc.).
# The frontend used to render a flat list of these below the action
# timeline; it makes more sense to anchor each version to the action it
# came from. The mapping is jurisdiction-specific because each chamber
# has its own action vocabulary.

VERSION_FORMAT_SUFFIXES = ("-html", "-pdf", "-xml", "-txt")

FEDERAL_VERSION_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    # An action can produce multiple printings (a Senate-passage action
    # produces both 'engrossed-in-senate' and 'agreed-to-senate' for a
    # resolution), so we collect *every* matching stage per action rather
    # than first-match-wins. Each stage is still claimed by only one
    # action — the first action whose text matches it.
    ("public-law",           re.compile(r"became public law", re.I)),
    ("enrolled-bill",        re.compile(r"presented to\s+president|enrolled\s+bill|enrolled\s+and\s+signed", re.I)),
    ("engrossed-in-senate",  re.compile(r"passed[/ ]agreed to in.*senate|engrossed in senate", re.I)),
    ("engrossed-in-house",   re.compile(r"passed[/ ]agreed to in.*house|engrossed in house", re.I)),
    ("agreed-to-senate",     re.compile(r"passed[/ ]agreed to in.*senate|on agreeing to the (resolution|amendment).*agreed", re.I)),
    ("agreed-to-house",      re.compile(r"passed[/ ]agreed to in.*house|on agreeing to the (resolution|amendment).*agreed", re.I)),
    ("placed-on-calendar-senate", re.compile(r"placed on (the )?senate (legislative )?calendar", re.I)),
    ("placed-on-calendar-house",  re.compile(r"placed on (the )?(union|house) calendar", re.I)),
    ("referred-in-senate",   re.compile(r"received in the senate", re.I)),
    ("referred-in-house",    re.compile(r"received in the house", re.I)),
    ("reported-in-house",    re.compile(r"reported.*\bhouse\b.*committee|reported by.*house", re.I)),
    ("reported-in-senate",   re.compile(r"reported.*\bsenate\b.*committee|reported by.*senate", re.I)),
    ("introduced-in-senate", re.compile(r"^introduced in senate|^submitted in senate", re.I)),
    ("introduced-in-house",  re.compile(r"^introduced in house|^submitted in house", re.I)),
]

VERSION_PATTERNS_BY_JURISDICTION: dict[str, list[tuple[str, "re.Pattern[str]"]]] = {
    "us": FEDERAL_VERSION_PATTERNS,
}


def _stage_of(label: str) -> str:
    """Strip the format suffix from a bill_versions.label to get its stage.

    `engrossed-in-house-html` → `engrossed-in-house`. Falls back to the
    whole label when there's no recognized format suffix.
    """
    for suf in VERSION_FORMAT_SUFFIXES:
        if label.endswith(suf):
            return label[: -len(suf)]
    return label


def _stage_label(stage: str) -> str:
    """Human label for a stage key. Best effort — title-case the slug."""
    return stage.replace("-", " ").title()


def _attach_versions_to_actions(
    jurisdiction: str, actions: list[dict], versions: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Decorate each action with its version printing.

    Returns (decorated_actions, unclaimed_stages). Actions are mutated
    in place to add a `versions` key (list of {format, source_url, label}).
    Unclaimed stages are the fallback list the frontend can show below
    the timeline.
    """
    stages: dict[str, list[dict]] = {}
    for v in versions:
        key = _stage_of(v["label"])
        stages.setdefault(key, []).append(
            {"format": v["format"], "source_url": v["source_url"], "label": v["label"]}
        )

    for action in actions:
        action["versions"] = []

    patterns = VERSION_PATTERNS_BY_JURISDICTION.get(jurisdiction, [])
    claimed: set[str] = set()
    for action in actions:
        text = action.get("action_text") or ""
        attached: list[dict] = []
        for stage_name, pattern in patterns:
            if stage_name in claimed or stage_name not in stages:
                continue
            if pattern.search(text):
                attached.extend(stages[stage_name])
                claimed.add(stage_name)
        action["versions"] = attached

    unclaimed = [
        {
            "stage": stage,
            "stage_label": _stage_label(stage),
            "formats": formats,
        }
        for stage, formats in stages.items()
        if stage not in claimed
    ]
    return actions, unclaimed

# Vocabulary kept in lockstep with the SQL CHECK constraints. Trust the
# DB enum as source of truth: if these drift, the CHECK rejects the
# write and we'll know.
ALL_KINDS = (
    "substantive", "placeholder", "ceremonial",
    "appropriations", "procedural", "vehicle", "unknown",
)
DEFAULT_KINDS = ("substantive",)

# Public Axiom app URL — every corpus provision is addressable at
# {AXIOM_APP_URL}/{citation_path}. Mirrors axiom-foundation.org/src/lib/urls.ts.
AXIOM_APP_URL = os.environ.get("AXIOM_APP_URL", "https://app.axiom-foundation.org")


def _default_db_path() -> str:
    # packages/api/src/axiom_bills_api/main.py → repo root four levels up
    return str(Path(__file__).resolve().parents[4] / "db" / "axiom_bills.sqlite")


DB_PATH = os.environ.get("AXIOM_BILLS_DB") or _default_db_path()

app = FastAPI(title="axiom-bills API", version="0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def _decode_json_columns(row: dict, columns: tuple[str, ...]) -> dict:
    for col in columns:
        if col in row and isinstance(row[col], str):
            try:
                row[col] = json.loads(row[col])
            except (TypeError, ValueError):
                pass
    return row


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": DB_PATH, "exists": Path(DB_PATH).exists()}


@app.get("/jurisdictions")
def list_jurisdictions() -> list[dict]:
    return query(
        """
        SELECT
            j.code,
            j.name,
            j.level,
            j.coverage,
            j.source_url,
            (SELECT COUNT(*) FROM bills b WHERE b.jurisdiction = j.code) AS bill_count,
            (SELECT COUNT(*) FROM bills b
              WHERE b.jurisdiction = j.code AND b.current_status = 'enacted') AS enacted_count,
            (SELECT MAX(finished_at) FROM scrape_runs r
              WHERE r.jurisdiction = j.code AND r.error IS NULL) AS last_scraped_at
        FROM jurisdictions j
        ORDER BY CASE j.level WHEN 'federal' THEN 0 ELSE 1 END,
                 CASE j.coverage WHEN 'full' THEN 0 WHEN 'stub' THEN 1 ELSE 2 END,
                 j.name ASC
        """
    )


@app.get("/coverage")
def coverage_summary() -> dict:
    """Aggregate roll-up for the dashboard coverage section."""
    rows = query(
        """
        SELECT coverage, COUNT(*) AS n
        FROM jurisdictions
        GROUP BY coverage
        """
    )
    totals = {r["coverage"]: r["n"] for r in rows}
    by_state = query(
        """
        SELECT code, name, coverage, source_url
        FROM jurisdictions
        WHERE level = 'state'
        ORDER BY
          CASE coverage WHEN 'full' THEN 0 WHEN 'stub' THEN 1 ELSE 2 END,
          name
        """
    )
    return {
        "totals": {
            "full":    totals.get("full", 0),
            "stub":    totals.get("stub", 0),
            "planned": totals.get("planned", 0),
        },
        "states": by_state,
    }


@app.get("/jurisdictions/{code}")
def get_jurisdiction(code: str) -> dict:
    rows = query("SELECT * FROM jurisdictions WHERE code = ?", (code,))
    if not rows:
        raise HTTPException(404, f"unknown jurisdiction: {code}")
    return rows[0]


ALL_RELEVANCE = ("any", "touches_corpus", "touches_rulespec")
DEFAULT_RELEVANCE = "any"


@app.get("/jurisdictions/{code}/bills")
def bills_for_jurisdiction(
    code: str,
    status: str | None = None,
    kind: list[str] = Query(default=list(DEFAULT_KINDS)),  # noqa: B008
    relevance: str = DEFAULT_RELEVANCE,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List bills for a jurisdiction.

    `kind` is repeatable: `?kind=substantive&kind=appropriations`. The
    default of just 'substantive' is what every reasonable consumer
    wants — placeholders and ceremonial resolutions shouldn't bury the
    real signal.

    `relevance` filters by what an extracted citation matches:
        any              — no filter
        touches_corpus   — at least one citation has a corpus row
        touches_rulespec — at least one citation matches a rulespec-us
                           encoding (the Pipeline-B work-item signal)
    """
    kinds = [k for k in kind if k in ALL_KINDS] or list(DEFAULT_KINDS)
    if relevance not in ALL_RELEVANCE:
        relevance = DEFAULT_RELEVANCE
    placeholders = ",".join("?" for _ in kinds)
    params: list = [code, *kinds]
    where = ["b.jurisdiction = ?", f"b.kind IN ({placeholders})"]
    if status:
        where.append("b.current_status = ?")
        params.append(status)

    if relevance == "touches_corpus":
        where.append("""
            EXISTS (
                SELECT 1 FROM bill_citations c
                JOIN corpus_provisions p ON (
                       p.citation = c.citation
                    OR c.citation LIKE p.citation || '(%'
                    OR c.citation LIKE p.citation || '.%'
                    OR p.citation LIKE c.citation || '(%'
                    OR p.citation LIKE c.citation || '.%'
                )
                WHERE c.bill_id = b.id
            )
        """)
    elif relevance == "touches_rulespec":
        where.append("""
            EXISTS (
                SELECT 1 FROM bill_citations c
                JOIN axiom_encodings e ON (
                       e.citation = c.citation
                    OR c.citation LIKE e.citation || '(%'
                    OR c.citation LIKE e.citation || '.%'
                    OR e.citation LIKE c.citation || '(%'
                    OR e.citation LIKE c.citation || '.%'
                )
                WHERE c.bill_id = b.id
            )
        """)
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT
            b.id, b.number, b.title, b.chamber, b.kind,
            b.current_status, b.current_status_at,
            b.first_seen_at, b.source_url,
            s.name AS session_name,
            (SELECT MAX(occurred_at) FROM bill_actions a WHERE a.bill_id = b.id)
              AS latest_action_at
        FROM bills b
        JOIN sessions s ON s.id = b.session_id
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(
          (SELECT MAX(occurred_at) FROM bill_actions a WHERE a.bill_id = b.id),
          b.first_seen_at
        ) DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    # Decorate each row with matched encodings AND matched corpus
    # provisions so the list view can surface what an individual bill
    # touches without forcing the user into the detail page. Both use
    # the same ancestor/descendant match as /affected-encodings and
    # the relevance EXISTS filter.
    bill_ids = [r["id"] for r in rows]
    matched_enc: dict[str, list[dict]] = {bid: [] for bid in bill_ids}
    matched_corp: dict[str, list[dict]] = {bid: [] for bid in bill_ids}
    if bill_ids:
        bid_placeholders = ",".join("?" for _ in bill_ids)
        encoding_rows = query(
            f"""
            SELECT DISTINCT
                c.bill_id,
                e.repo, e.kind, e.citation, e.file_path,
                ('https://github.com/TheAxiomFoundation/' || e.repo
                  || '/blob/main/' || e.file_path) AS github_url
            FROM bill_citations c
            JOIN axiom_encodings e ON (
                   e.citation = c.citation
                OR c.citation LIKE e.citation || '(%'
                OR c.citation LIKE e.citation || '.%'
                OR e.citation LIKE c.citation || '(%'
                OR e.citation LIKE c.citation || '.%'
            )
            WHERE c.bill_id IN ({bid_placeholders})
            ORDER BY length(e.citation) ASC
            """,
            tuple(bill_ids),
        )
        for er in encoding_rows:
            bid = er.pop("bill_id")
            if bid in matched_enc:
                matched_enc[bid].append(er)

        corpus_rows = query(
            f"""
            SELECT DISTINCT
                c.bill_id,
                p.citation, p.citation_path, p.heading
            FROM bill_citations c
            JOIN corpus_provisions p ON (
                   p.citation = c.citation
                OR c.citation LIKE p.citation || '(%'
                OR c.citation LIKE p.citation || '.%'
                OR p.citation LIKE c.citation || '(%'
                OR p.citation LIKE c.citation || '.%'
            )
            WHERE c.bill_id IN ({bid_placeholders})
            ORDER BY length(p.citation) ASC
            """,
            tuple(bill_ids),
        )
        for cr in corpus_rows:
            bid = cr.pop("bill_id")
            if bid in matched_corp:
                matched_corp[bid].append({
                    **cr,
                    "axiom_url": f"{AXIOM_APP_URL}/{cr['citation_path']}",
                })
    for r in rows:
        r["matched_encodings"] = matched_enc.get(r["id"], [])
        r["matched_corpus"] = matched_corp.get(r["id"], [])
    return {
        "bills": rows,
        "limit": limit,
        "offset": offset,
        "applied_kinds": kinds,
        "applied_relevance": relevance,
    }


@app.get("/jurisdictions/{code}/kinds")
def kind_breakdown(code: str) -> dict:
    """Counts per kind for a jurisdiction. Used by the kind-filter UI."""
    rows = query(
        """
        SELECT kind, COUNT(*) AS n
        FROM bills
        WHERE jurisdiction = ?
        GROUP BY kind
        """,
        (code,),
    )
    out = {k: 0 for k in ALL_KINDS}
    for r in rows:
        out[r["kind"]] = r["n"]
    return out


@app.get("/bills/{bill_id}")
def bill_detail(bill_id: str) -> dict:
    bill_rows = query(
        """
        SELECT b.*, s.name AS session_name, j.name AS jurisdiction_name
        FROM bills b
        JOIN sessions s      ON s.id   = b.session_id
        JOIN jurisdictions j ON j.code = b.jurisdiction
        WHERE b.id = ?
        """,
        (bill_id,),
    )
    if not bill_rows:
        raise HTTPException(404, f"unknown bill: {bill_id}")
    bill = _decode_json_columns(bill_rows[0], ("subjects", "sponsors"))
    actions = query(
        """
        SELECT occurred_at, chamber, action_text, normalized_status, source_url
        FROM bill_actions
        WHERE bill_id = ?
        ORDER BY occurred_at DESC
        """,
        (bill_id,),
    )
    versions = query(
        """
        SELECT label, source_url, format, fetched_at
        FROM bill_versions
        WHERE bill_id = ?
        ORDER BY label
        """,
        (bill_id,),
    )
    actions, unclaimed = _attach_versions_to_actions(bill["jurisdiction"], actions, versions)
    bill["actions"] = actions
    bill["unclaimed_versions"] = unclaimed
    # Keep the flat versions list available for clients that want it,
    # but the frontend should prefer the per-action grouping.
    bill["versions"] = versions
    # Return every stored text version, newest first. The frontend
    # exposes a selector when more than one exists; otherwise the
    # single row is the only "version" the user can view.
    bill["texts"] = query(
        """
        SELECT version_label, format, text, fetched_at
          FROM bill_texts
         WHERE bill_id = ?
         ORDER BY fetched_at DESC
        """,
        (bill_id,),
    )
    return bill


@app.get("/bills/{bill_id}/affected-rules")
def bill_affected_rules(bill_id: str) -> dict:
    """Rule-level Pipeline-B trigger.

    For each amendment op extracted from the bill, check whether the
    strike-text appears verbatim in any encoded rule's proof atom. Hits
    are the rules whose grounding has *demonstrably* changed — those
    are the ones that need re-encoding. See
    axiom-architecture/docs/corpus-encoding-mapping.md.

    Returns:
        rules: rule rows with the bill citations + ops + atom snippets
               that triggered the match. Each is a Pipeline-B work item.
        scope: rules whose source matches a bill citation but whose
               atoms were not touched — they might need re-validation
               but are lower priority.
    """
    # Lazy import to avoid pulling the parser at API startup.
    from axiom_bills._common.amendments import parse_amendments_for_citation

    bill_rows = query(
        """
        SELECT b.id, b.jurisdiction
        FROM bills b WHERE b.id = ?
        """,
        (bill_id,),
    )
    if not bill_rows:
        raise HTTPException(404, f"unknown bill: {bill_id}")

    text_row = query(
        "SELECT text FROM bill_texts WHERE bill_id = ? ORDER BY fetched_at DESC LIMIT 1",
        (bill_id,),
    )
    bill_text = text_row[0]["text"] if text_row else ""

    citations = query(
        "SELECT DISTINCT citation FROM bill_citations WHERE bill_id = ?",
        (bill_id,),
    )

    def _is_specific_needle(needle: str) -> bool:
        """Filter generic-phrase noise out of Pipeline-B signals.

        'taxable year' / 'calendar year' / 'such individual' appear in
        many bills and many encoded atoms purely because federal legal
        prose reuses them — they're not meaningful Pipeline-B triggers.
        Heuristic: a struck phrase counts only if it contains a digit,
        dollar sign, or percent sign (specific value), or is long
        enough (≥ 25 chars) that overlap is unlikely to be coincidence.
        """
        if not needle or len(needle) < 8:
            return False
        if any(c.isdigit() or c in "$%" for c in needle):
            return True
        return len(needle) >= 25

    rules_in_scope: dict[str, dict] = {}
    rules_with_atom_hit: dict[str, dict] = {}

    for c in citations:
        citation = c["citation"]
        # Source-match rules: rule_source is a descendant or ancestor of
        # the bill's citation under proper boundary rules. Same SQL
        # pattern as /affected-encodings.
        scope_rules = query(
            """
            SELECT r.id, r.rule_name, r.rule_kind, r.rule_source, r.rule_dtype,
                   e.repo, e.kind, e.file_path, e.citation AS encoding_citation,
                   ('https://github.com/TheAxiomFoundation/' || e.repo
                     || '/blob/main/' || e.file_path) AS github_url
            FROM encoded_rules r
            JOIN axiom_encodings e ON e.id = r.encoding_id
            WHERE r.rule_source = ?
               OR ? LIKE r.rule_source || '(%'
               OR ? LIKE r.rule_source || '.%'
               OR r.rule_source LIKE ? || '(%'
               OR r.rule_source LIKE ? || '.%'
            """,
            (citation, citation, citation, citation, citation),
        )
        for r in scope_rules:
            rules_in_scope.setdefault(r["id"], {**r, "matches": []})

        # Atom-overlap: for each amendment op the bill applies to this
        # citation, look for the strike-text in any rule's proof atom.
        ops = parse_amendments_for_citation(bill_text, citation)
        for op in ops:
            needle = op.needle if op.kind in ("strike-insert", "strike") else None
            # For replace-all and add-end, the op's `payload` is new
            # text — it doesn't overlap existing atom text by
            # construction. Such ops change the SECTION, not any
            # existing rule's grounding (any *new* rule that comes from
            # the new text needs encoding from scratch, but no existing
            # atom is invalidated).
            if not needle:
                continue
            if not _is_specific_needle(needle):
                continue
            atom_hits = query(
                """
                SELECT r.id AS rule_id, r.rule_name, r.rule_source,
                       a.atom_path, a.atom_kind, a.text AS atom_text,
                       e.repo, e.file_path, e.citation AS encoding_citation,
                       ('https://github.com/TheAxiomFoundation/' || e.repo
                         || '/blob/main/' || e.file_path) AS github_url
                FROM encoded_rule_atoms a
                JOIN encoded_rules r ON r.id = a.rule_id
                JOIN axiom_encodings e ON e.id = r.encoding_id
                WHERE a.text LIKE ?
                """,
                (f"%{needle}%",),
            )
            for h in atom_hits:
                entry = rules_with_atom_hit.setdefault(h["rule_id"], {
                    "rule_name": h["rule_name"],
                    "rule_source": h["rule_source"],
                    "repo": h["repo"],
                    "file_path": h["file_path"],
                    "encoding_citation": h["encoding_citation"],
                    "github_url": h["github_url"],
                    "matches": [],
                })
                entry["matches"].append({
                    "bill_citation": citation,
                    "strike_text": needle,
                    "atom_path": h["atom_path"],
                    "atom_kind": h["atom_kind"],
                    "atom_text": h["atom_text"],
                })

    return {
        "atom_hits": list(rules_with_atom_hit.values()),
        "scope_only": [
            r for r in rules_in_scope.values()
            if r["id"] not in rules_with_atom_hit
        ],
        "totals": {
            "in_scope": len(rules_in_scope),
            "atom_hits": len(rules_with_atom_hit),
        },
    }


@app.get("/bills/{bill_id}/diffs")
def bill_diffs(bill_id: str) -> dict:
    """Return one section per AmendmentBlock parsed from the bill text.

    Phase 1+2+3 of the parser audit: target-first parser instead of
    citation-window scanning. Each section corresponds to a single
    "Section X is amended" block in the bill — no more duplicate tabs
    for the same amendment with different citation granularity.
    Operations carry precise targets (block target + any "in paragraph
    (P)" narrowing), so the applier slices and replaces at the right
    scope rather than blind substring-matching on the parent body.
    Parse failures land in `parse_warnings` so a reviewer can see what
    the parser couldn't digest.
    """
    text_row = query(
        """
        SELECT text FROM bill_texts
         WHERE bill_id = ?
         ORDER BY fetched_at DESC LIMIT 1
        """,
        (bill_id,),
    )
    bill_text = text_row[0]["text"] if text_row else ""

    from axiom_bills._common.corpus_client import fetch as fetch_corpus
    from axiom_bills._common.amendments import (
        normalize_legal_text,
        slice_subsection,
        unified_diff,
    )
    from axiom_bills._common.amendment_blocks import (
        apply_block,
        parse_bill_amendments,
    )

    def _encoding_for(citation: str) -> dict | None:
        rows = query(
            """
            SELECT jurisdiction, repo, kind, citation, file_path
            FROM axiom_encodings
            WHERE citation = ?
               OR ? LIKE citation || '(%'
               OR ? LIKE citation || '.%'
               OR citation LIKE ? || '(%'
               OR citation LIKE ? || '.%'
            ORDER BY length(citation) DESC
            LIMIT 1
            """,
            (citation, citation, citation, citation, citation),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "repo": row["repo"],
            "kind": row["kind"],
            "citation": row["citation"],
            "file_path": row["file_path"],
            "github_url": f"https://github.com/TheAxiomFoundation/{row['repo']}/blob/main/{row['file_path']}",
        }

    blocks = parse_bill_amendments(bill_text)

    # Also include any extracted bill_citations that the structured
    # parser didn't pick up — they may have encodings worth showing
    # even without amendment ops. We dedupe by target so a citation
    # already covered by a block doesn't show twice.
    extracted = query(
        "SELECT DISTINCT citation FROM bill_citations WHERE bill_id = ? ORDER BY citation",
        (bill_id,),
    )
    block_targets = {b.target for b in blocks}
    extra_citations = [r["citation"] for r in extracted
                       if r["citation"] not in block_targets]

    sections: list[dict] = []

    for block in blocks:
        target = block.target
        encoding = _encoding_for(target)
        prov = fetch_corpus(target, db_path=DB_PATH)
        if prov is None or not prov.body:
            sections.append(_unmatched_section(
                target, encoding,
                parse_warnings=block.parse_warnings,
                operations=block.operations,
                block_raw=block.raw,
            ))
            continue

        applied_result = apply_block(block, prov.body, slice_subsection)
        # Diff is computed against the block's *scope* (the slice), not
        # the full corpus body — keeps the visible change tight.
        before = applied_result.before_text or prov.body
        after = applied_result.after_text or before
        before_norm = normalize_legal_text(before)
        after_norm = normalize_legal_text(after)
        diff = unified_diff(before_norm, after_norm) if applied_result.applied else []

        sections.append({
            "citation": target,
            "in_corpus": True,
            "exact_corpus_match": prov.is_exact_match,
            "sliced_subsection": not prov.is_exact_match,
            "matched_corpus_path": prov.citation_path,
            "heading": prov.heading,
            "citation_path": prov.citation_path,
            "current_text": before_norm,
            "applied_text": after_norm,
            "diff": diff,
            "applied_ops":   [_op_dict(o) for o in applied_result.applied],
            "unapplied_ops": [{**_op_dict(o), "note": note}
                              for o, note in applied_result.unapplied],
            "parse_warnings": block.parse_warnings,
            "block_raw": block.raw[:1200] if block.parse_warnings else None,
            "has_rulespec":  bool(encoding),
            "encoding":      encoding,
            "axiom_url":     f"{AXIOM_APP_URL}/{prov.citation_path}",
            "source_url":    prov.source_url,
        })

    # Tail: citations that aren't tied to any amendment block. These
    # are typically cross-references in the bill's prose. We show them
    # only when there's an encoding (otherwise they're pure noise).
    for citation in extra_citations:
        encoding = _encoding_for(citation)
        if not encoding:
            continue
        prov = fetch_corpus(citation, db_path=DB_PATH)
        if prov is None or not prov.body:
            sections.append(_unmatched_section(citation, encoding))
            continue
        sections.append({
            "citation": citation,
            "in_corpus": True,
            "exact_corpus_match": prov.is_exact_match,
            "sliced_subsection": False,
            "matched_corpus_path": prov.citation_path,
            "heading": prov.heading,
            "citation_path": prov.citation_path,
            "current_text": normalize_legal_text(prov.body),
            "applied_text": normalize_legal_text(prov.body),
            "diff": [],
            "applied_ops":   [],
            "unapplied_ops": [],
            "parse_warnings": [],
            "block_raw": None,
            "has_rulespec":  True,
            "encoding":      encoding,
            "axiom_url":     f"{AXIOM_APP_URL}/{prov.citation_path}",
            "source_url":    prov.source_url,
        })

    return {"sections": sections}


def _unmatched_section(citation: str, encoding: dict | None, *,
                       parse_warnings: list | None = None,
                       operations: list | None = None,
                       block_raw: str | None = None) -> dict:
    """Section payload when corpus has no row for this target."""
    return {
        "citation": citation,
        "in_corpus": False,
        "exact_corpus_match": False,
        "sliced_subsection": False,
        "matched_corpus_path": None,
        "heading": None,
        "citation_path": None,
        "current_text": None,
        "applied_text": None,
        "diff": [],
        "applied_ops": [],
        "unapplied_ops": [_op_dict(o) for o in (operations or [])],
        "parse_warnings": parse_warnings or [],
        "block_raw": block_raw[:1200] if block_raw else None,
        "has_rulespec": bool(encoding),
        "encoding": encoding,
        "axiom_url": None,
        "source_url": None,
    }


def _op_dict(op) -> dict:
    return {
        "kind":   getattr(op, "kind", ""),
        "target": getattr(op, "target", ""),
        "needle": getattr(op, "needle", ""),
        "payload": getattr(op, "payload", ""),
        "anchor": getattr(op, "anchor", ""),
        "redesignate_to": getattr(op, "redesignate_to", ""),
        "raw":    getattr(op, "raw", ""),
    }


@app.get("/bills/{bill_id}/affected-encodings")
def bill_affected_encodings(bill_id: str) -> dict:
    """For a bill's extracted citations, return which Axiom encodings exist.

    The shape is split into matched (citation has a RuleSpec) and
    unmatched (citation extracted but no encoded file in any rulespec-*
    repo yet). Both are useful: matched is the Pipeline B work list;
    unmatched is the encoder backlog.
    """
    citations = query(
        """
        SELECT raw, citation, source
        FROM bill_citations
        WHERE bill_id = ?
        ORDER BY citation
        """,
        (bill_id,),
    )
    if not citations:
        return {"matched": [], "unmatched": [], "citations": []}

    matched: list[dict] = []
    unmatched: list[dict] = []
    for c in citations:
        # Bidirectional ancestor/descendant match with proper section
        # boundaries — otherwise `26 USC 22%` would incorrectly grab
        # `26 USC 213`. A citation continues onto the next level only
        # via `(` (USC subscript) or `.` (CFR part.section).
        encodings = query(
            """
            SELECT jurisdiction, repo, kind, citation, file_path
            FROM axiom_encodings
            WHERE citation = ?
               OR ? LIKE citation || '(%'
               OR ? LIKE citation || '.%'
               OR citation LIKE ? || '(%'
               OR citation LIKE ? || '.%'
            """,
            (
                c["citation"],
                c["citation"],
                c["citation"],
                c["citation"],
                c["citation"],
            ),
        )
        if encodings:
            matched.append({**c, "encodings": encodings})
        else:
            unmatched.append(c)
    return {
        "matched": matched,
        "unmatched": unmatched,
        "citations": citations,
    }


@app.get("/recent")
def recent_status_changes(
    status: str = "enacted",
    kind: list[str] = Query(default=list(DEFAULT_KINDS)),  # noqa: B008
    limit: int = 50,
) -> list[dict]:
    """Cross-jurisdiction firehose by status change.

    Default = enacted substantive bills: the canonical 'new law' feed
    Pipeline B subscribes to. Ceremonial enactments (post-office namings)
    are excluded by default — they don't need RuleSpec encoding work.
    """
    kinds = [k for k in kind if k in ALL_KINDS] or list(DEFAULT_KINDS)
    placeholders = ",".join("?" for _ in kinds)
    return query(
        f"""
        SELECT
            b.id, b.jurisdiction, b.number, b.title, b.kind,
            b.current_status, b.current_status_at, b.source_url,
            j.name AS jurisdiction_name,
            j.level AS jurisdiction_level
        FROM bills b
        JOIN jurisdictions j ON j.code = b.jurisdiction
        WHERE b.current_status = ? AND b.kind IN ({placeholders})
        ORDER BY b.current_status_at DESC
        LIMIT ?
        """,
        (status, *kinds, limit),
    )
