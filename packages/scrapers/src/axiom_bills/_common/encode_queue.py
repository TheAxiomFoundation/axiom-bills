"""Encoder trigger queue — the first consumer of the staleness signals.

``enqueue_scan`` walks the local DB and materializes one ``encode_queue``
row per (bill, citation, reason) for every citation the pipeline thinks
needs encoder attention:

- **needs_new_encoding** — bills flagged by precompute-diffs because
  their amendments land inside an encoded program area with no existing
  rule file (``encoding_backlog`` sections in ``bills.diffs``);
- **stale_variant** — rule_variants whose LLM proposal was superseded by
  a fingerprint change (precompute-variants cleared the patched_yaml and
  appended a "Superseded" note), so the affected encoding should be
  re-checked at the source;
- **enacted_touch** — enacted/signed bills that amend encoded files: the
  baseline encoding itself is now stale, not just a proposed variant.

The scan is enqueue-once: an existing (bill, citation, reason) row is
never touched again, whatever its status — a dismissed row must never be
resurrected. ``corpus_citation_path`` is filled from
``encoded_rules.module_corpus_citation_path`` where the citation matches
an indexed encoding.

``run_pending`` is the LOCAL runner: for each pending row it shells out

    axiom-encode encode "<citation>" --corpus-path $AXIOM_CORPUS_PATH \
        --policy-repo-path $AXIOM_POLICY_REPO_PATH \
        --axiom-rules-engine-path $AXIOM_RULES_ENGINE_PATH \
        --output <dir>

Validate-only, NEVER ``--apply`` — applying needs the signing supervisor
and stays human-gated. Note the manual prerequisite: the encoder reads
signed corpus releases, not bill text, so for enacted bills the corpus
must have ingested the amended law (and the toolchain re-pinned) before
a queue run can produce the post-enactment encoding.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections import deque
from pathlib import Path

from .db import DEFAULT_DB
from .variants import SUPERSEDED_MARKER


REASON_NEEDS_NEW_ENCODING = "needs_new_encoding"
REASON_STALE_VARIANT = "stale_variant"
REASON_ENACTED_TOUCH = "enacted_touch"

# Env vars the local runner needs — checked up front so a half-configured
# machine fails before the first encoder invocation, not mid-queue.
RUNNER_ENV_VARS = (
    "AXIOM_CORPUS_PATH",
    "AXIOM_POLICY_REPO_PATH",
    "AXIOM_RULES_ENGINE_PATH",
)

DEFAULT_OUTPUT_ROOT = Path.home() / ".axiom-bills" / "encode-runs"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _corpus_path_map(conn: sqlite3.Connection) -> dict[str, str]:
    """citation → module_corpus_citation_path for every indexed encoding
    that recorded one (first rule wins; they agree within a module)."""
    out: dict[str, str] = {}
    for row in conn.execute(
        """
        SELECT e.citation, r.module_corpus_citation_path AS path
          FROM axiom_encodings e
          JOIN encoded_rules r ON r.encoding_id = e.id
         WHERE r.module_corpus_citation_path IS NOT NULL
         ORDER BY e.citation, r.rule_name
        """
    ):
        out.setdefault(row["citation"], row["path"])
    return out


def _diffs_payload(raw) -> dict:
    if not raw:
        return {}
    return json.loads(raw) if isinstance(raw, str) else raw


def _candidates_needs_new_encoding(
    conn: sqlite3.Connection, jurisdiction: str | None,
) -> list[tuple[str, str, str]]:
    """(bill_id, citation, reason) for every distinct backlog citation of
    every bill flagged needs_new_encoding."""
    where = ["needs_new_encoding = 1", "diffs IS NOT NULL"]
    params: list = []
    if jurisdiction:
        where.append("jurisdiction = ?")
        params.append(jurisdiction)
    out: list[tuple[str, str, str]] = []
    for bill in conn.execute(
        f"SELECT id, diffs FROM bills WHERE {' AND '.join(where)}", params,
    ).fetchall():
        seen: set[str] = set()
        for section in _diffs_payload(bill["diffs"]).get("sections", []):
            if not section.get("encoding_backlog"):
                continue
            citation = section.get("citation")
            if citation and citation not in seen:
                seen.add(citation)
                out.append((bill["id"], citation, REASON_NEEDS_NEW_ENCODING))
    return out


def _candidates_stale_variants(
    conn: sqlite3.Connection, jurisdiction: str | None,
) -> list[tuple[str, str, str]]:
    """(bill_id, citation, reason) for variants whose LLM proposal was
    superseded by a fingerprint change (precompute-variants clears the
    patched_yaml and appends a superseded note; on a fresh CI database
    hydrate-variants stamps the same marker when a remote proposal's
    fingerprint no longer matches)."""
    where = ["v.note LIKE ?"]
    params: list = [f"%{SUPERSEDED_MARKER}%"]
    if jurisdiction:
        where.append("b.jurisdiction = ?")
        params.append(jurisdiction)
    out: list[tuple[str, str, str]] = []
    for row in conn.execute(
        f"""
        SELECT DISTINCT v.bill_id, e.citation
          FROM rule_variants v
          JOIN bills b ON b.id = v.bill_id
          JOIN axiom_encodings e ON e.id = v.encoding_id
         WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchall():
        out.append((row["bill_id"], row["citation"], REASON_STALE_VARIANT))
    return out


def _candidates_enacted_touches(
    conn: sqlite3.Connection, jurisdiction: str | None,
) -> list[tuple[str, str, str]]:
    """(bill_id, citation, reason) for every encoding citation a
    became-law bill (enacted/signed/veto_overridden) actually amends
    (parsed ops, applied or not)."""
    where = [
        "touches_rulespec = 1",
        "diffs IS NOT NULL",
        "current_status IN ('enacted', 'signed', 'veto_overridden')",
    ]
    params: list = []
    if jurisdiction:
        where.append("jurisdiction = ?")
        params.append(jurisdiction)
    out: list[tuple[str, str, str]] = []
    for bill in conn.execute(
        f"SELECT id, diffs FROM bills WHERE {' AND '.join(where)}", params,
    ).fetchall():
        seen: set[str] = set()
        for section in _diffs_payload(bill["diffs"]).get("sections", []):
            encoding = section.get("encoding")
            has_ops = bool(
                (section.get("applied_ops") or [])
                + (section.get("unapplied_ops") or [])
            )
            if not encoding or not has_ops:
                continue
            citation = encoding.get("citation")
            if citation and citation not in seen:
                seen.add(citation)
                out.append((bill["id"], citation, REASON_ENACTED_TOUCH))
    return out


def enqueue_scan(db_path: str = DEFAULT_DB, *,
                 jurisdiction: str | None = None,
                 dry_run: bool = False) -> dict[str, int]:
    """Materialize encode_queue rows from the three staleness signals.

    Idempotent and enqueue-once: an existing (bill_id, citation, reason)
    row is left alone regardless of status, so a dismissed row is never
    re-enqueued. Returns per-reason enqueue counts plus totals.
    """
    counts = {
        "candidates": 0, "enqueued": 0, "existing": 0,
        REASON_NEEDS_NEW_ENCODING: 0,
        REASON_STALE_VARIANT: 0,
        REASON_ENACTED_TOUCH: 0,
    }
    conn = _connect(db_path)
    try:
        candidates = (
            _candidates_needs_new_encoding(conn, jurisdiction)
            + _candidates_stale_variants(conn, jurisdiction)
            + _candidates_enacted_touches(conn, jurisdiction)
        )
        counts["candidates"] = len(candidates)

        existing = {
            (r["bill_id"], r["citation"], r["reason"])
            for r in conn.execute(
                "SELECT bill_id, citation, reason FROM encode_queue"
            )
        }
        corpus_paths = _corpus_path_map(conn)

        for bill_id, citation, reason in candidates:
            key = (bill_id, citation, reason)
            if key in existing:
                counts["existing"] += 1
                continue
            existing.add(key)  # dedupe within this scan too
            corpus_path = corpus_paths.get(citation)
            if dry_run:
                print(
                    f"  would enqueue [{reason}] {citation}"
                    f"{'  (' + corpus_path + ')' if corpus_path else ''}"
                    f"  bill={bill_id}",
                    file=sys.stderr, flush=True,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO encode_queue
                        (id, bill_id, citation, corpus_citation_path, reason)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, bill_id, citation, corpus_path, reason),
                )
            counts["enqueued"] += 1
            counts[reason] += 1
    finally:
        conn.close()
    return counts


# ────────────────────────────────────────────────────────────────────
#  Local runner
# ────────────────────────────────────────────────────────────────────

def _pump(stream, sink, tail: deque) -> None:
    for line in iter(stream.readline, ""):
        sink.write(line)
        sink.flush()
        tail.append(line)
    stream.close()


def _run_encoder(cmd: list[str], *, tail_lines: int = 20) -> tuple[int, str]:
    """Run one encoder invocation, streaming its output live.

    Returns (exit_code, stderr_tail). Output is echoed as it arrives so
    a local user watches encoder progress instead of a silent hang.
    """
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # errors="replace": a stray non-UTF-8 byte in encoder output
            # must not raise in a pump thread — a dead pump leaves the
            # child blocked on a full pipe and t.join() hangs forever.
        )
    except OSError as exc:
        # Launch failure (binary vanished mid-queue, permissions):
        # stamp the row failed rather than crashing the whole run.
        return 127, f"failed to launch {cmd[0]}: {exc}"
    stderr_tail: deque = deque(maxlen=tail_lines)
    threads = [
        threading.Thread(target=_pump,
                         args=(proc.stdout, sys.stdout, deque(maxlen=1))),
        threading.Thread(target=_pump,
                         args=(proc.stderr, sys.stderr, stderr_tail)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    exit_code = proc.wait()
    return exit_code, "".join(stderr_tail).strip()


def run_pending(db_path: str = DEFAULT_DB, *,
                jurisdiction: str | None = None,
                limit: int | None = None,
                env: dict[str, str] | None = None) -> dict[str, int]:
    """Run `axiom-encode encode` for each pending queue row (local only).

    Never passes ``--apply`` — the encoder validates and writes its
    proposal under an --output dir; applying stays human-gated. Missing
    env vars raise before anything runs. Each row is stamped ran/failed
    with the exit code, output dir, and (on failure) a stderr tail.
    """
    env = env if env is not None else dict(os.environ)
    missing = [name for name in RUNNER_ENV_VARS if not env.get(name)]
    if missing:
        raise RuntimeError(
            "trigger-encodes --run needs local checkouts configured via "
            f"env: {', '.join(missing)} not set. Point AXIOM_CORPUS_PATH "
            "at an axiom-corpus clone, AXIOM_POLICY_REPO_PATH at the "
            "rulespec clone, and AXIOM_RULES_ENGINE_PATH at an "
            "axiom-rules-engine clone."
        )
    if shutil.which("axiom-encode") is None:
        raise RuntimeError(
            "trigger-encodes --run needs the `axiom-encode` CLI on PATH "
            "(install the encoder toolchain or activate its venv)."
        )
    output_root = Path(env.get("AXIOM_ENCODE_OUTPUT") or DEFAULT_OUTPUT_ROOT)

    counts = {"pending": 0, "ran": 0, "failed": 0}
    conn = _connect(db_path)
    try:
        where = ["q.status = 'pending'"]
        params: list = []
        if jurisdiction:
            where.append("b.jurisdiction = ?")
            params.append(jurisdiction)
        rows = conn.execute(
            f"""
            SELECT q.id, q.bill_id, q.citation, q.reason, b.number
              FROM encode_queue q
              JOIN bills b ON b.id = q.bill_id
             WHERE {' AND '.join(where)}
             ORDER BY q.enqueued_at, q.id
            """,
            params,
        ).fetchall()
        counts["pending"] = len(rows)
        if limit is not None:
            rows = rows[:limit]

        for row in rows:
            out_dir = output_root / row["id"]
            out_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                "axiom-encode", "encode", row["citation"],
                "--corpus-path", env["AXIOM_CORPUS_PATH"],
                "--policy-repo-path", env["AXIOM_POLICY_REPO_PATH"],
                "--axiom-rules-engine-path", env["AXIOM_RULES_ENGINE_PATH"],
                "--output", str(out_dir),
            ]
            print(
                f"→ [{row['reason']}] {row['number']}: "
                f"axiom-encode encode {row['citation']!r} → {out_dir}",
                file=sys.stderr, flush=True,
            )
            exit_code, stderr_tail = _run_encoder(cmd)
            if exit_code == 0:
                status = "ran"
                detail = f"exit 0; output {out_dir}"
                counts["ran"] += 1
            else:
                status = "failed"
                detail = f"exit {exit_code}; output {out_dir}"
                if stderr_tail:
                    detail += f"; stderr tail:\n{stderr_tail}"
                counts["failed"] += 1
            conn.execute(
                """
                UPDATE encode_queue
                   SET status = ?, detail = ?, resolved_at = datetime('now')
                 WHERE id = ?
                """,
                (status, detail, row["id"]),
            )
            print(f"   {status}: {row['citation']} (exit {exit_code})",
                  file=sys.stderr, flush=True)
    finally:
        conn.close()
    return counts
