"""Agentic bill ↔ encoding reconciliation.

Python port of guidance-impact-visualizer's ``src/lib/diff/analyze.ts``
plus its ``skills.ts`` prompt modules, adapted from guidance framing to
bill framing. For every bill section that touches an encoded RuleSpec
file, two enum-constrained verdicts ("nuggets") are produced:

- **billVsLaw** — the bill's amended text for the section vs the
  CURRENT corpus provision: is the change substantive, and what does
  it change?
- **modelVsLaw** — the encoded RuleSpec rules for the section vs the
  law AS AMENDED by the bill: would the current encoding be wrong
  post-enactment, and what needs re-encoding?

Each verdict comes from a tool-use analyst call: the model may consult
research tools backed by the local DB (``lookup_provision`` reads
corpus_provisions; ``lookup_rules`` reads encoded_rules /
encoded_rule_atoms / rule_variants) and must record its answer through
a ``record_verdict`` tool whose input_schema *is* the LayerDiff shape,
so status / materiality / action / confidence are enum-constrained at
the API level. Single pass — the visualizer's reviewer-audit agent is
a noted follow-up.

Idempotency mirrors ``variants._ops_fingerprint``: each stored row
records a sha256 fingerprint over the canonical JSON of the section's
ops (with applied flags), before/after text shas, and the encoding
file path. Re-running with unchanged inputs skips the LLM calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from .db import DEFAULT_DB
from .reencoder_llm import DEFAULT_MODEL


# ────────────────────────────────────────────────────────────────────
#  Verdict vocabulary (mirrors the visualizer's schema.ts)
# ────────────────────────────────────────────────────────────────────

DIFF_STATUSES = ("aligned", "adds-detail", "narrows", "conflicts", "missing")
CONFIDENCE = ("high", "medium", "low")
MATERIALITY = (
    "changes-eligibility",
    "changes-state-duty",
    "procedural",
    "cosmetic",
    "none",
)
ACTIONS = ("encode-in-model", "legal-review", "none")


# ────────────────────────────────────────────────────────────────────
#  Skill modules (ported largely verbatim from skills.ts, reframed
#  guidance → bill)
# ────────────────────────────────────────────────────────────────────

SKILL_DIFF_TAXONOMY = """\
## Diff taxonomy
Classify the gap between the two layers with exactly one status:
- aligned: the lower layer faithfully carries the upper layer's requirement.
- adds-detail: the lower layer adds operational detail the upper layer left open (no conflict).
- narrows: the lower layer is stricter or narrower than the upper layer permits.
- conflicts: the lower layer contradicts the upper layer.
- missing: an upper-layer requirement is absent from the lower layer.

Reporting discipline — DIFF, DON'T DESCRIBE:
- Identify the SINGLE most important element that diverges and state it in "divergence" in ≤25 words. Do NOT recap everything that aligns.
- If nothing material diverges, status is "aligned" and divergence is "none".
- "rationale" is at most ONE sentence justifying the call. No essays."""

SKILL_MATERIALITY = """\
## Materiality rubric
Set "materiality" to how much the divergence actually matters — judge consequence, not mere difference:
- changes-eligibility: alters WHO is an applicable, eligible, or excluded individual, or WHAT amount/benefit they receive.
- changes-state-duty: alters what a STATE or administering agency must or may do (deadlines, mandatory procedures, options).
- procedural: affects process/notice/verification mechanics without changing eligibility or core duties.
- cosmetic: wording, structure, or ordering only; no legal effect.
- none: aligned; nothing diverges."""

SKILL_ACTION = """\
## Action routing
Set "action" to the next step this finding warrants:
- encode-in-model: a real, substantive legal requirement is absent or wrong in the ENCODED MODEL and should be encoded/fixed (e.g. the bill would change what an encoded rule computes).
- legal-review: the divergence raises a question of legal authority or meaning a lawyer should resolve (e.g. the bill's amendment is ambiguous or conflicts with other law).
- none: aligned, or an immaterial difference needing no action."""

SKILL_QUOTE_FIDELITY = """\
## Quote standard
- Quote VERBATIM from the supplied texts, at the point of divergence only. Never paraphrase inside quotes.
- upstreamQuote = the higher-authority layer; downstreamQuote = the lower layer. Quote the divergent phrase, not whole sections.
- If a quote you need is not in the supplied text, use a lookup tool; if it is still unavailable, say so rather than inventing one."""

SKILL_RULESPEC = """\
## RuleSpec structure (encoded model)
A rule file has "rules"; each rule has versioned formulas (encoded logic) and proof "atoms" (a kind + verbatim source excerpt, or an import target).
- Cross-referenced conditions appear as boolean inputs whose definitions live in OTHER files. A free/unimported boolean variable is NORMAL encoding — not automatically "missing". Look up the referenced file before judging it absent.
- A genuine "missing" is a substantive legal requirement with NO rule or atom anywhere capturing it (look it up to be sure).
- An "import" atom with a target = a structural dependency. A named atom WITHOUT an expected import is a traceability gap — usually adds-detail / procedural, not a substantive miss.
- Always distinguish a real encoding gap from a RuleSpec convention."""

SKILL_BILL_CONTEXT = """\
## Context
- CURRENT LEGAL CODE: the corpus provision text for the cited section, as currently in force.
- BILL: a proposed amendment to that provision — the parsed amendment instructions and, where they could be applied mechanically, the resulting amended text.
- ENCODED MODEL: RuleSpec YAML rules (rulespec-* repos) — a machine encoding of the CURRENT law, indexed rule-by-rule with proof atoms.
Corpus available to your lookup tools: provisions cached in the local corpus table and RuleSpec rules indexed from rulespec-* checkouts. Cross-references outside those caches are unavailable — report them as unavailable rather than guessing."""


# ────────────────────────────────────────────────────────────────────
#  Tools
# ────────────────────────────────────────────────────────────────────

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status", "divergence", "materiality", "action",
                 "confidence", "rationale"],
    "properties": {
        "status": {"type": "string", "enum": list(DIFF_STATUSES)},
        "divergence": {
            "type": "string",
            "description": "The SINGLE most important element that differs, "
                           "in ≤25 words. 'none' if aligned.",
        },
        "materiality": {"type": "string", "enum": list(MATERIALITY)},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        "rationale": {
            "type": "string",
            "description": "At most ONE sentence justifying the call.",
        },
        "ambiguity": {
            "type": "string",
            "description": "When confidence is not high: the contestable "
                           "point and plausible alternative reading. Omit "
                           "if straightforward.",
        },
        "upstreamQuote": {
            "type": "string",
            "description": "Verbatim from the higher-authority layer at the "
                           "divergence, or omit.",
        },
        "downstreamQuote": {
            "type": "string",
            "description": "Verbatim from the lower layer at the divergence, "
                           "or omit.",
        },
    },
}

RECORD_VERDICT_TOOL = {
    "name": "record_verdict",
    "description": "Record the diff verdict for this layer as a tight "
                   "nugget (divergence + materiality + action).",
    "input_schema": VERDICT_SCHEMA,
}

LOOKUP_PROVISION_TOOL = {
    "name": "lookup_provision",
    "description": "Look up the full text of a statute or regulation "
                   "provision by citation (e.g. '26 USC 32(a)') or Axiom "
                   "citation path (e.g. 'us/statute/26/32'). Returns "
                   "heading and body if cached in the local corpus, "
                   "otherwise reports it unavailable.",
    "input_schema": {
        "type": "object",
        "required": ["citation"],
        "properties": {"citation": {"type": "string"}},
    },
}

LOOKUP_RULES_TOOL = {
    "name": "lookup_rules",
    "description": "Look up encoded RuleSpec rules by legal citation "
                   "(e.g. '26 USC 32(a)') or rule file path (e.g. "
                   "'statutes/26/32.yaml'). Returns rule names, kinds, "
                   "sources, proof atoms, and any pending 'if enacted' "
                   "variant drafted for this bill.",
    "input_schema": {
        "type": "object",
        "required": ["citation"],
        "properties": {"citation": {"type": "string"}},
    },
}


# ────────────────────────────────────────────────────────────────────
#  Validation
# ────────────────────────────────────────────────────────────────────

def _str(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def valid_verdict(v: Any) -> bool:
    """Strict enum validation on receipt — the schema constrains the
    API, but a retried/degraded response can still be malformed."""
    if not isinstance(v, dict):
        return False
    return (
        v.get("status") in DIFF_STATUSES
        and v.get("materiality") in MATERIALITY
        and v.get("action") in ACTIONS
        and v.get("confidence") in CONFIDENCE
        and bool(_str(v.get("rationale")) or _str(v.get("divergence")))
    )


def normalize_verdict(v: dict) -> dict:
    """Canonical LayerDiff dict for storage (validated input)."""
    out = {
        "status": v["status"],
        "divergence": _str(v.get("divergence")) or "none",
        "materiality": v["materiality"],
        "action": v["action"],
        "confidence": v["confidence"],
        "rationale": _str(v.get("rationale")),
    }
    for key in ("ambiguity", "upstreamQuote", "downstreamQuote"):
        if _str(v.get(key)):
            out[key] = _str(v.get(key))
    return out


# ────────────────────────────────────────────────────────────────────
#  Research-tool resolution against the local DB
# ────────────────────────────────────────────────────────────────────

def _truncate(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else f"{s[:n]}\n…[truncated; {len(s)} chars total]"


def _resolve_provision(conn: sqlite3.Connection, citation: str) -> str:
    c = (citation or "").strip()
    if not c:
        return "No citation given."
    row = conn.execute(
        """
        SELECT citation, citation_path, heading, body
          FROM corpus_provisions
         WHERE citation = ? OR citation_path = ?
        """, (c, c),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT citation, citation_path, heading, body
              FROM corpus_provisions
             WHERE ? LIKE citation || '%' OR citation LIKE ? || '%'
             ORDER BY length(citation) DESC LIMIT 1
            """, (c, c),
        ).fetchone()
    if row is None:
        return (f'No provision matching "{c}" is in the local corpus cache. '
                "Treat as a limitation; do not guess its content.")
    heading = row["heading"] or ""
    return f"{row['citation']} — {heading}:\n{_truncate(row['body'] or '')}"


def _encoding_payload(conn: sqlite3.Connection, enc: sqlite3.Row,
                      bill_id: str | None) -> dict:
    rules = []
    for r in conn.execute(
        """
        SELECT id, rule_name, rule_kind, rule_source, rule_dtype
          FROM encoded_rules WHERE encoding_id = ?
        """, (enc["id"],),
    ):
        atoms = [
            {"path": a["atom_path"], "kind": a["atom_kind"],
             "corpus_citation_path": a["corpus_citation_path"],
             "text": a["text"]}
            for a in conn.execute(
                """
                SELECT atom_path, atom_kind, corpus_citation_path, text
                  FROM encoded_rule_atoms WHERE rule_id = ?
                """, (r["id"],),
            )
        ]
        rules.append({
            "name": r["rule_name"], "kind": r["rule_kind"],
            "source": r["rule_source"], "dtype": r["rule_dtype"],
            "atoms": atoms,
        })
    payload = {
        "repo": enc["repo"], "citation": enc["citation"],
        "file_path": enc["file_path"], "rules": rules,
    }
    if bill_id:
        try:
            v = conn.execute(
                """
                SELECT tier, note, proposed_by, patched_yaml
                  FROM rule_variants WHERE bill_id = ? AND file_path = ?
                """, (bill_id, enc["file_path"]),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if ("no such table" not in str(exc)
                    and "no such column" not in str(exc)):
                raise
            v = None
        if v is not None:
            payload["bill_variant"] = {
                "tier": v["tier"], "note": v["note"],
                "proposed_by": v["proposed_by"],
                "patched_yaml": _truncate(v["patched_yaml"], 4000)
                if v["patched_yaml"] else None,
            }
    return payload


def _resolve_rules(conn: sqlite3.Connection, bill_id: str | None,
                   citation: str) -> str:
    c = (citation or "").strip()
    if not c:
        return "No citation given."
    enc_rows = conn.execute(
        """
        SELECT id, repo, citation, file_path
          FROM axiom_encodings
         WHERE citation = ? OR file_path = ?
            OR ? LIKE citation || '(%'
            OR ? LIKE citation || '.%'
            OR citation LIKE ? || '(%'
            OR citation LIKE ? || '.%'
        """, (c, c, c, c, c, c),
    ).fetchall()
    if not enc_rows:
        return (f'No encoded RuleSpec file matching "{c}" is indexed. '
                "Treat as not encoded rather than guessing.")
    payloads = [_encoding_payload(conn, enc, bill_id) for enc in enc_rows[:3]]
    return _truncate(json.dumps(payloads, indent=2), 8000)


def _execute_lookup(conn: sqlite3.Connection, bill_id: str | None,
                    name: str, tool_input: Any) -> str:
    citation = (tool_input or {}).get("citation", "")
    print(f"    [lookup] {name}({citation})", file=sys.stderr, flush=True)
    if name == LOOKUP_PROVISION_TOOL["name"]:
        return _resolve_provision(conn, citation)
    if name == LOOKUP_RULES_TOOL["name"]:
        return _resolve_rules(conn, bill_id, citation)
    return f"Unknown tool: {name}"


# ────────────────────────────────────────────────────────────────────
#  Anthropic client (reuses the repo's key conventions)
# ────────────────────────────────────────────────────────────────────

KEYS_ENV = Path.home() / ".axiom-bills" / "keys.env"


def _keys_env_fallback() -> str | None:
    """Local-dev fallback: read ANTHROPIC_API_KEY from
    ~/.axiom-bills/keys.env when the env var isn't set (CI always sets
    it through the workflow env)."""
    if not KEYS_ENV.exists():
        return None
    for line in KEYS_ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def make_client():
    """Anthropic client. Local import keeps unit tests light (they
    inject a fake client and never touch the SDK)."""
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() \
        or _keys_env_fallback()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not configured (env var or "
            f"{KEYS_ENV})."
        )
    return Anthropic(api_key=api_key, max_retries=2, timeout=180.0)


# ────────────────────────────────────────────────────────────────────
#  Agent loop (port of analyze.ts runAgent)
# ────────────────────────────────────────────────────────────────────

def _run_analyst(client, conn: sqlite3.Connection, bill_id: str, *,
                 system: str, user: str, model: str,
                 max_tokens: int = 2400, max_turns: int = 5,
                 attempts: int = 2) -> dict | None:
    """Agent loop: may call research tools, then must call
    record_verdict. Retries once (a fresh attempt) on schema mismatch;
    returns None on persistent failure so the caller records nothing."""
    tools = [LOOKUP_PROVISION_TOOL, LOOKUP_RULES_TOOL, RECORD_VERDICT_TOOL]
    for _attempt in range(attempts):
        messages: list[dict] = [{"role": "user", "content": user}]
        for turn in range(max_turns):
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                tool_choice=(
                    {"type": "tool", "name": RECORD_VERDICT_TOOL["name"]}
                    if turn == max_turns - 1 else {"type": "any"}
                ),
                messages=messages,
            )
            tool_uses = [b for b in resp.content
                         if getattr(b, "type", None) == "tool_use"]
            record = next(
                (t for t in tool_uses
                 if t.name == RECORD_VERDICT_TOOL["name"]), None)
            if record is not None and valid_verdict(record.input):
                return normalize_verdict(record.input)
            if not tool_uses:
                break
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": t.id,
                        "content": (
                            "Rejected: one or more required fields were "
                            "missing or not one of the allowed enum values. "
                            "Call record_verdict again with every required "
                            "field set to an allowed value."
                            if t.name == RECORD_VERDICT_TOOL["name"]
                            else _execute_lookup(conn, bill_id, t.name, t.input)
                        ),
                    }
                    for t in tool_uses
                ],
            })
    return None


# ────────────────────────────────────────────────────────────────────
#  Analyst prompts
# ────────────────────────────────────────────────────────────────────

def _bill_analyst_system() -> str:
    return "\n\n".join([
        "You are a senior U.S. legislative attorney, expert in statutory "
        "interpretation and legislative drafting. You compare a BILL's "
        "proposed amended text (downstream) against the CURRENT LEGAL "
        "CODE (upstream) and report only the delta and its stakes. Here "
        "'aligned' means the amendment leaves the provision materially "
        "unchanged (cosmetic edits only).",
        SKILL_BILL_CONTEXT,
        SKILL_DIFF_TAXONOMY,
        SKILL_MATERIALITY,
        SKILL_ACTION,
        SKILL_QUOTE_FIDELITY,
    ])


def _model_analyst_system() -> str:
    return "\n\n".join([
        "You are a rules engineer who encodes statutes and regulations "
        "into RuleSpec and audits whether an encoding faithfully captures "
        "the law. You compare the ENCODED MODEL (downstream) against the "
        "law AS IT WOULD READ IF THE BILL WERE ENACTED (upstream) and "
        "report only the delta and its stakes: would the current encoding "
        "be wrong post-enactment, and what needs re-encoding?",
        SKILL_BILL_CONTEXT,
        SKILL_DIFF_TAXONOMY,
        SKILL_MATERIALITY,
        SKILL_ACTION,
        SKILL_QUOTE_FIDELITY,
        SKILL_RULESPEC,
    ])


def _ops_block(section: dict) -> str:
    lines: list[str] = []
    for op in section.get("applied_ops") or []:
        raw = op.get("raw") or (
            f"{op.get('kind', '')} {op.get('target', '')} "
            f"{op.get('needle', '')!r} → {op.get('payload', '')!r}"
        )
        lines.append(f"[applied] {raw}")
    for op in section.get("unapplied_ops") or []:
        raw = op.get("raw") or (
            f"{op.get('kind', '')} {op.get('target', '')} "
            f"{op.get('needle', '')!r} → {op.get('payload', '')!r}"
        )
        note = op.get("note")
        lines.append(f"[could not be auto-applied{': ' + note if note else ''}] {raw}")
    return _truncate("\n".join(lines), 4000)


def _bill_analyst_user(bill_number: str, section: dict) -> str:
    citation = section["citation"]
    heading = section.get("heading") or citation
    before = section.get("current_text") or "(not in corpus cache)"
    after = section.get("applied_text") or before
    return f"""Analyze BILL {bill_number}'s amendment to {citation} — "{heading}".

<current-law citation="{citation}">
{_truncate(before)}
</current-law>

<bill-amended-text citation="{citation}">
{_truncate(after)}
</bill-amended-text>

<amendment-instructions>
{_ops_block(section)}
</amendment-instructions>

Compare the BILL'S AMENDED TEXT (downstream) against the CURRENT LEGAL \
CODE (upstream): is the change substantive, and what is the single most \
important thing it changes? Instructions marked "could not be \
auto-applied" are part of the bill even though the amended text above \
does not reflect them. Use lookup tools for cross-references, then call \
record_verdict with the single most important divergence."""


def _model_analyst_user(bill_number: str, section: dict,
                        encoded_model_json: str) -> str:
    citation = section["citation"]
    heading = section.get("heading") or citation
    after = section.get("applied_text") or section.get("current_text") \
        or "(not in corpus cache)"
    file_path = (section.get("encoding") or {}).get("file_path", "")
    return f"""Audit the ENCODED MODEL for {citation} — "{heading}" against the law AS AMENDED by BILL {bill_number}.

<amended-law citation="{citation}">
{_truncate(after)}
</amended-law>

<amendment-instructions>
{_ops_block(section)}
</amendment-instructions>

<encoded-model file="{file_path}">
{encoded_model_json}
</encoded-model>

Compare the ENCODED MODEL (downstream) against the law as amended by \
the bill (upstream): would the current encoding be wrong post-enactment, \
and what needs re-encoding? Instructions marked "could not be \
auto-applied" still amend the law even though the amended text above \
does not reflect them. Use lookup_rules to check related encoded files \
BEFORE judging anything missing, then call record_verdict with the \
single most important divergence."""


# ────────────────────────────────────────────────────────────────────
#  Section selection + fingerprint
# ────────────────────────────────────────────────────────────────────

def candidate_sections(diffs: dict | None) -> list[dict]:
    """Sections worth reconciling: an encoded file matched AND at least
    one applied/unapplied amendment op."""
    out: list[dict] = []
    for section in (diffs or {}).get("sections", []):
        has_ops = bool(
            (section.get("applied_ops") or [])
            + (section.get("unapplied_ops") or [])
        )
        if section.get("encoding") and has_ops:
            out.append(section)
    return out


def _sha_or_none(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode()).hexdigest()


def section_fingerprint(section: dict) -> str:
    """Stable hash of everything the verdicts depend on (mirrors
    variants._ops_fingerprint): the ops with applied flags, the
    before/after text shas, and the encoding file path."""
    ops = [
        {"kind": op.get("kind", ""), "target": op.get("target", ""),
         "needle": op.get("needle", ""), "payload": op.get("payload", ""),
         "applied": applied}
        for op, applied in (
            [(o, True) for o in section.get("applied_ops") or []]
            + [(o, False) for o in section.get("unapplied_ops") or []]
        )
    ]
    doc = {
        "ops": ops,
        "before_sha256": _sha_or_none(section.get("current_text")),
        "after_sha256": _sha_or_none(section.get("applied_text")),
        "encoding_file_path": (section.get("encoding") or {}).get("file_path"),
    }
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ────────────────────────────────────────────────────────────────────
#  Storage
# ────────────────────────────────────────────────────────────────────

def _upsert_reconciliation(conn: sqlite3.Connection, bill_id: str,
                           section_citation: str, payload: dict,
                           fingerprint: str, model: str) -> None:
    conn.execute(
        """
        INSERT INTO bill_reconciliations
            (id, bill_id, section_citation, payload, fingerprint, model,
             computed_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(bill_id, section_citation) DO UPDATE SET
            payload = excluded.payload,
            fingerprint = excluded.fingerprint,
            model = excluded.model,
            computed_at = datetime('now')
        """,
        (uuid.uuid4().hex, bill_id, section_citation,
         json.dumps(payload), fingerprint, model),
    )


# ────────────────────────────────────────────────────────────────────
#  Drivers
# ────────────────────────────────────────────────────────────────────

def reconcile_for_bill(conn: sqlite3.Connection, bill_id: str, *,
                       limit: int | None = None, dry_run: bool = False,
                       get_client: Callable[[], Any] | None = None,
                       model: str | None = None) -> dict[str, int]:
    """Reconcile every touched section of one bill. Idempotent: a
    stored row with the same fingerprint skips the LLM calls."""
    counts = {"sections": 0, "analyzed": 0, "skipped": 0, "failed": 0}
    used_model = model or DEFAULT_MODEL

    bill_row = conn.execute(
        "SELECT number, diffs FROM bills WHERE id = ?", (bill_id,),
    ).fetchone()
    if not bill_row or not bill_row["diffs"]:
        return counts
    diffs = (json.loads(bill_row["diffs"])
             if isinstance(bill_row["diffs"], str) else bill_row["diffs"])
    bill_number = bill_row["number"] or "unknown"

    for section in candidate_sections(diffs):
        counts["sections"] += 1
        citation = section["citation"]
        fingerprint = section_fingerprint(section)
        existing = conn.execute(
            """
            SELECT fingerprint FROM bill_reconciliations
             WHERE bill_id = ? AND section_citation = ?
            """, (bill_id, citation),
        ).fetchone()
        if existing and existing["fingerprint"] == fingerprint:
            counts["skipped"] += 1
            continue

        if dry_run:
            print(f"  would analyze {bill_number}  @  {citation}",
                  file=sys.stderr, flush=True)
            counts["would_analyze"] = counts.get("would_analyze", 0) + 1
        else:
            print(f"  → {bill_number}  @  {citation}",
                  file=sys.stderr, flush=True)
            client = get_client() if get_client else make_client()

            file_path = (section.get("encoding") or {}).get("file_path")
            enc = conn.execute(
                """
                SELECT id, repo, citation, file_path FROM axiom_encodings
                 WHERE file_path = ?
                """, (file_path,),
            ).fetchone()
            encoded_model_json = (
                _truncate(json.dumps(
                    _encoding_payload(conn, enc, bill_id), indent=2), 8000)
                if enc is not None else
                f"(rules for {file_path} are not indexed locally — use "
                "lookup_rules for related files)"
            )

            bill_verdict = _run_analyst(
                client, conn, bill_id,
                system=_bill_analyst_system(),
                user=_bill_analyst_user(bill_number, section),
                model=used_model,
            )
            model_verdict = _run_analyst(
                client, conn, bill_id,
                system=_model_analyst_system(),
                user=_model_analyst_user(bill_number, section,
                                         encoded_model_json),
                model=used_model,
            ) if bill_verdict is not None else None

            if bill_verdict is None or model_verdict is None:
                which = "billVsLaw" if bill_verdict is None else "modelVsLaw"
                print(f"     FAILED: no valid {which} verdict after retries "
                      f"for {bill_number} @ {citation} — recording nothing.",
                      file=sys.stderr, flush=True)
                counts["failed"] += 1
                continue

            payload = {
                "topic": section.get("heading") or citation,
                "section": citation,
                "billVsLaw": bill_verdict,
                "modelVsLaw": model_verdict,
            }
            _upsert_reconciliation(conn, bill_id, citation, payload,
                                   fingerprint, used_model)
            counts["analyzed"] += 1

        done = counts["analyzed"] + counts.get("would_analyze", 0)
        if limit is not None and done >= limit:
            break

    return counts


def reconcile_all(db_path: str = DEFAULT_DB, *,
                  jurisdiction: str | None = None,
                  bill_id: str | None = None,
                  limit: int | None = None,
                  dry_run: bool = False,
                  client: Any | None = None,
                  model: str | None = None) -> dict[str, int]:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    where = ["diffs IS NOT NULL"]
    params: list = []
    if jurisdiction:
        where.append("jurisdiction = ?")
        params.append(jurisdiction)
    if bill_id:
        where.append("id = ?")
        params.append(bill_id)
    bill_ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM bills WHERE {' AND '.join(where)}", params,
    ).fetchall()]

    # One client for the whole run, created lazily so dry runs (and
    # runs where every section is fingerprint-skipped) need no API key.
    holder: dict[str, Any] = {"client": client}

    def get_client():
        if holder["client"] is None:
            holder["client"] = make_client()
        return holder["client"]

    totals: dict[str, int] = {}
    remaining = limit
    for b_id in bill_ids:
        counts = reconcile_for_bill(
            conn, b_id, limit=remaining, dry_run=dry_run,
            get_client=get_client, model=model,
        )
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        if limit is not None:
            done = totals.get("analyzed", 0) + totals.get("would_analyze", 0)
            remaining = max(0, limit - done)
            if remaining == 0:
                break
    conn.close()
    return totals
