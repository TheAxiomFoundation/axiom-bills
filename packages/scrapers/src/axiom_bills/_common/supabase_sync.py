"""Sync local SQLite → Supabase Postgres for the bills schema.

Reads the local axiom_bills.sqlite database, transforms each table to
the Postgres shape, and upserts into the matching ``bills.*`` table on
the Supabase project pointed at by:

    SUPABASE_URL          — https://<project>.supabase.co
    SUPABASE_SERVICE_KEY  — service-role key (never anon)

The script is idempotent: runs as many times as you like, mutates only
the rows whose primary key matches. It also precomputes per-bill diffs
into the ``bills.bills.diffs`` JSONB column so the frontend can fetch
finished diff data without any API service.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import httpx


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

REST = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else None


def _client() -> httpx.Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars before running."
        )
    return httpx.Client(
        base_url=REST,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Profile": "bills",   # writes into the `bills` schema
            "Accept-Profile": "bills",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        timeout=60.0,
    )


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _select_all(client: httpx.Client, table: str, params: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    page_size = 1000
    start = 0
    while True:
        end = start + page_size - 1
        resp = client.get(
            f"/{table}",
            params=params,
            headers={"Range": f"{start}-{end}"},
        )
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Supabase read from {table} failed ({resp.status_code}): "
                f"{resp.text[:500]}"
            )
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def _remote_rows_by_in(
    client: httpx.Client,
    table: str,
    *,
    select: str,
    column: str,
    values: Iterable[str],
    chunk: int = 100,
) -> list[dict]:
    unique_values = sorted({value for value in values if value})
    rows: list[dict] = []
    for batch in _chunks(unique_values, chunk):
        rows.extend(_select_all(
            client,
            table,
            {
                "select": select,
                column: f"in.({','.join(batch)})",
                "order": "id.asc",
            },
        ))
    return rows


def _upsert(client: httpx.Client, table: str, rows: list[dict], *,
            on_conflict: str | None = None, chunk: int = 500) -> int:
    if not rows:
        return 0
    written = 0
    for batch in _chunks(rows, chunk):
        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        resp = client.post(f"/{table}", params=params, content=json.dumps(batch))
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Supabase write to {table} failed ({resp.status_code}): "
                f"{resp.text[:500]}"
            )
        written += len(batch)
    return written


def _local(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(local: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(r) for r in local.execute(sql).fetchall()]


def _has_column(local: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in local.execute(f"PRAGMA table_info({table})"))


def _bool(v) -> bool:
    return bool(v) if v not in (None, "") else False


def _remote_session_ids(client: httpx.Client, local_rows: list[sqlite3.Row]) -> dict[str, str]:
    remote_rows = _remote_rows_by_in(
        client,
        "sessions",
        select="id,jurisdiction,name",
        column="jurisdiction",
        values=(r["jurisdiction"] for r in local_rows),
    )
    existing = {
        (r["jurisdiction"], r["name"]): r["id"]
        for r in remote_rows
    }
    return {
        r["id"]: existing.get((r["jurisdiction"], r["name"]), r["id"])
        for r in local_rows
    }


def _remote_bill_ids(client: httpx.Client, rows: list[dict]) -> dict[str, str]:
    remote_rows = _remote_rows_by_in(
        client,
        "bills",
        select="id,jurisdiction,session_id,chamber,number",
        column="session_id",
        values=(r["session_id"] for r in rows),
    )
    existing = {
        (r["jurisdiction"], r["session_id"], r["chamber"], r["number"]): r["id"]
        for r in remote_rows
    }
    mapped = {
        r["id"]: existing.get(
            (r["jurisdiction"], r["session_id"], r["chamber"], r["number"]),
            r["id"],
        )
        for r in rows
    }
    missing_rows = [r for r in rows if mapped[r["id"]] == r["id"]]
    if not missing_rows:
        return mapped

    # Large refreshes can span thousands of bills; keep a second lookup by
    # jurisdiction so an incomplete session-id page cannot make an upsert
    # rewrite a bill primary key that child rows already reference.
    jurisdiction_rows = _remote_rows_by_in(
        client,
        "bills",
        select="id,jurisdiction,session_id,chamber,number",
        column="jurisdiction",
        values=(r["jurisdiction"] for r in missing_rows),
    )
    fallback: dict[tuple[Any, ...], str | None] = {}
    for r in jurisdiction_rows:
        key = (r["jurisdiction"], r["chamber"], r["number"])
        if key in fallback:
            fallback[key] = None
        else:
            fallback[key] = r["id"]

    for r in missing_rows:
        key = (r["jurisdiction"], r["chamber"], r["number"])
        if fallback.get(key):
            mapped[r["id"]] = fallback[key]
    return mapped


def _remote_child_ids(
    client: httpx.Client,
    table: str,
    *,
    rows: list[dict],
    select: str,
    key_columns: tuple[str, ...],
) -> dict[str, str]:
    remote_rows = _remote_rows_by_in(
        client,
        table,
        select=f"id,bill_id,{select}",
        column="bill_id",
        values=(r["bill_id"] for r in rows),
    )
    existing = {
        tuple(r[column] for column in ("bill_id", *key_columns)): r["id"]
        for r in remote_rows
    }
    return {
        r["id"]: existing.get(
            tuple(r[column] for column in ("bill_id", *key_columns)),
            r["id"],
        )
        for r in rows
    }


def sync(db_path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    local = _local(db_path)
    with _client() as client:
        # 1. Jurisdictions — seeded by the migration but include our
        #    local ones in case they drift.
        rows = _rows(local,
            "SELECT code, name, level, source_url, coverage, created_at FROM jurisdictions")
        counts["jurisdictions"] = _upsert(
            client, "jurisdictions", rows, on_conflict="code"
        )

        # 2. Sessions
        session_rows = local.execute(
            "SELECT id, jurisdiction, name, start_date, end_date, is_current FROM sessions"
        ).fetchall()
        session_id_map = _remote_session_ids(client, session_rows)
        rows = []
        for r in session_rows:
            rows.append({
                "id": session_id_map[r["id"]],
                "jurisdiction": r["jurisdiction"],
                "name": r["name"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "is_current": _bool(r["is_current"]),
            })
        counts["sessions"] = _upsert(
            client, "sessions", rows, on_conflict="jurisdiction,name"
        )

        # 3. Bills — includes the diffs JSONB.
        bills_rows: list[dict] = []
        diffs_expr = "diffs" if _has_column(local, "bills", "diffs") else "NULL AS diffs"
        for r in local.execute(f"""
            SELECT id, jurisdiction, session_id, chamber, number, title, summary,
                   subjects, sponsors, source_url, current_status, current_status_at,
                   kind, first_seen_at, last_scraped_at, {diffs_expr}
              FROM bills
        """):
            bills_rows.append({
                "id": r["id"],
                "jurisdiction": r["jurisdiction"],
                "session_id": session_id_map.get(r["session_id"], r["session_id"]),
                "chamber": r["chamber"],
                "number": r["number"],
                "title": r["title"],
                "summary": r["summary"],
                "subjects": json.loads(r["subjects"] or "[]"),
                "sponsors": json.loads(r["sponsors"] or "[]"),
                "source_url": r["source_url"],
                "current_status": r["current_status"],
                "current_status_at": r["current_status_at"],
                "kind": r["kind"],
                "first_seen_at": r["first_seen_at"],
                "last_scraped_at": r["last_scraped_at"],
                "diffs": json.loads(r["diffs"]) if r["diffs"] else None,
            })
        bill_id_map = _remote_bill_ids(client, bills_rows)
        for row in bills_rows:
            row["id"] = bill_id_map[row["id"]]
        counts["bills"] = _upsert(
            client, "bills", bills_rows,
            on_conflict="jurisdiction,session_id,chamber,number",
        )

        # 4. Bill actions
        rows = []
        for r in local.execute("""
            SELECT id, bill_id, occurred_at, chamber, action_text,
                   normalized_status, source_url, fingerprint, ingested_at
              FROM bill_actions
        """):
            rows.append({
                "id": r["id"],
                "bill_id": bill_id_map.get(r["bill_id"], r["bill_id"]),
                "occurred_at": r["occurred_at"],
                "chamber": r["chamber"],
                "action_text": r["action_text"],
                "normalized_status": r["normalized_status"],
                "source_url": r["source_url"],
                "fingerprint": r["fingerprint"],
                "ingested_at": r["ingested_at"],
            })
        child_id_map = _remote_child_ids(
            client,
            "bill_actions",
            rows=rows,
            select="fingerprint",
            key_columns=("fingerprint",),
        )
        for row in rows:
            row["id"] = child_id_map[row["id"]]
        counts["bill_actions"] = _upsert(
            client, "bill_actions", rows, on_conflict="bill_id,fingerprint"
        )

        # 5. Bill versions
        rows = []
        for r in local.execute("""
            SELECT id, bill_id, label, source_url, format, text_sha256, fetched_at
              FROM bill_versions
        """):
            row = dict(r)
            row["bill_id"] = bill_id_map.get(row["bill_id"], row["bill_id"])
            rows.append(row)
        child_id_map = _remote_child_ids(
            client,
            "bill_versions",
            rows=rows,
            select="label",
            key_columns=("label",),
        )
        for row in rows:
            row["id"] = child_id_map[row["id"]]
        counts["bill_versions"] = _upsert(
            client, "bill_versions", rows, on_conflict="bill_id,label"
        )

        # 6. Bill texts — these are large but worth syncing so the
        #    frontend can show the latest version.
        rows = []
        for r in local.execute("""
            SELECT id, bill_id, version_label, source_url, format, text,
                   text_sha256, fetched_at
              FROM bill_texts
        """):
            row = dict(r)
            row["bill_id"] = bill_id_map.get(row["bill_id"], row["bill_id"])
            rows.append(row)
        child_id_map = _remote_child_ids(
            client,
            "bill_texts",
            rows=rows,
            select="version_label",
            key_columns=("version_label",),
        )
        for row in rows:
            row["id"] = child_id_map[row["id"]]
        counts["bill_texts"] = _upsert(
            client, "bill_texts", rows, on_conflict="bill_id,version_label", chunk=200
        )

        # 7. Bill citations
        rows = []
        for r in local.execute("""
            SELECT id, bill_id, raw, citation, source, extracted_at
              FROM bill_citations
        """):
            row = dict(r)
            row["bill_id"] = bill_id_map.get(row["bill_id"], row["bill_id"])
            rows.append(row)
        child_id_map = _remote_child_ids(
            client,
            "bill_citations",
            rows=rows,
            select="citation,source",
            key_columns=("citation", "source"),
        )
        for row in rows:
            row["id"] = child_id_map[row["id"]]
        counts["bill_citations"] = _upsert(
            client, "bill_citations", rows, on_conflict="bill_id,citation,source"
        )

        # 8. Encodings + rules + atoms
        rows = []
        for r in local.execute("""
            SELECT id, jurisdiction, repo, kind, citation, file_path, indexed_at
              FROM axiom_encodings
        """):
            rows.append(dict(r))
        counts["axiom_encodings"] = _upsert(client, "axiom_encodings", rows, on_conflict="id")

        rows = []
        for r in local.execute("""
            SELECT id, encoding_id, rule_name, rule_kind, rule_source, rule_dtype,
                   module_corpus_citation_path, indexed_at
              FROM encoded_rules
        """):
            rows.append(dict(r))
        counts["encoded_rules"] = _upsert(client, "encoded_rules", rows, on_conflict="id")

        rows = []
        for r in local.execute("""
            SELECT id, rule_id, atom_path, atom_kind, corpus_citation_path, text
              FROM encoded_rule_atoms
        """):
            rows.append(dict(r))
        counts["encoded_rule_atoms"] = _upsert(client, "encoded_rule_atoms", rows, on_conflict="id")

        # rule_variants — Pipeline B's per-bill patched YAML payloads.
        # Skipped silently if the local table doesn't exist yet (older
        # SQLite snapshots before migration 007).
        try:
            rows = []
            for r in local.execute("""
                SELECT id, bill_id, encoding_id, file_path, tier,
                       patched_rule_names, baseline_yaml, patched_yaml,
                       diff_summary, note, effective_from, computed_at,
                       proposed_by, proposed_model
                  FROM rule_variants
            """):
                rows.append({
                    "id": r["id"],
                    "bill_id": bill_id_map.get(r["bill_id"], r["bill_id"]),
                    "encoding_id": r["encoding_id"],
                    "file_path": r["file_path"],
                    "tier": r["tier"],
                    "patched_rule_names": json.loads(r["patched_rule_names"] or "[]"),
                    "baseline_yaml": r["baseline_yaml"],
                    "patched_yaml": r["patched_yaml"],
                    "diff_summary": r["diff_summary"],
                    "note": r["note"],
                    "effective_from": r["effective_from"],
                    "computed_at": r["computed_at"],
                    "proposed_by": r["proposed_by"],
                    "proposed_model": r["proposed_model"],
                })
            counts["rule_variants"] = _upsert(
                client, "rule_variants", rows, on_conflict="id", chunk=200,
            )
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            counts["rule_variants"] = 0

    local.close()
    return counts
