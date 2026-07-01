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
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx


# Supabase/PostgREST occasionally times out or returns a transient 5xx on a
# big write (large bills batches carry the diffs JSONB). Retry those with
# backoff so a single blip doesn't fail the whole nightly refresh.
_RETRY_STATUS = {408, 429, 502, 503, 504}


def _send_with_retry(
    send: Callable[[], httpx.Response],
    *,
    what: str,
    attempts: int = 4,
    base_delay: float = 2.0,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = send()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
            continue
        if resp.status_code in _RETRY_STATUS and attempt < attempts - 1:
            time.sleep(base_delay * (2 ** attempt))
            continue
        return resp
    assert last_exc is not None
    raise last_exc


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
        resp = _send_with_retry(
            lambda: client.get(
                f"/{table}",
                params=params,
                headers={"Range": f"{start}-{end}"},
            ),
            what=f"read {table}",
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
                # Order by the FILTER column (then id for stable Range
                # pagination), not id alone. Ordering by id.asc let Postgres
                # walk the id PK index applying the `column in (...)` filter
                # row-by-row until it filled the 1000-row window; on a large
                # child table like bill_actions that scan grew into a 57014
                # statement timeout. Leading with the filter column forces the
                # planner onto the index that already covers it
                # (e.g. idx_actions_bill_occurred on bill_actions(bill_id,...)),
                # so it probes just the matching rows.
                "order": f"{column}.asc,id.asc",
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
        payload = json.dumps(batch)
        resp = _send_with_retry(
            lambda: client.post(f"/{table}", params=params, content=payload),
            what=f"write {table}",
        )
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
    # Look up existing remote bills by JURISDICTION, not session_id.
    # bills.session_id has no index, so a `session_id=in.(...)` lookup is a
    # full-table sequential scan that timed out (57014) once the table grew.
    # jurisdiction is indexed (idx_bills_jurisdiction_status), and a sync only
    # ever covers a single jurisdiction, so this one query is both fast and
    # sufficient — we derive the precise key match and the ambiguity-safe
    # fallback from the same rows instead of issuing a second query.
    remote_rows = _remote_rows_by_in(
        client,
        "bills",
        select="id,jurisdiction,session_id,chamber,number",
        column="jurisdiction",
        values=(r["jurisdiction"] for r in rows),
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

    # Fallback for bills whose remote session_id differs from the local one
    # (session re-keying): match on (jurisdiction, chamber, number) when it's
    # unambiguous, so an upsert can't rewrite a bill PK that child rows
    # already reference.
    fallback: dict[tuple[Any, ...], str | None] = {}
    for r in remote_rows:
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

        # 3. Bills — includes the diffs JSONB, but only when this run
        #    actually computed some. A run that skipped precompute-diffs
        #    (state matrix jobs, FETCH_TEXTS=false) has NULL everywhere
        #    locally, and shipping those NULLs would erase the diffs a
        #    previous run wrote to Supabase.
        include_diffs = (
            _has_column(local, "bills", "diffs")
            and local.execute(
                "SELECT 1 FROM bills WHERE diffs IS NOT NULL LIMIT 1"
            ).fetchone() is not None
        )
        bills_rows: list[dict] = []
        diffs_expr = "diffs" if include_diffs else "NULL AS diffs"
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
                **({"diffs": json.loads(r["diffs"]) if r["diffs"] else None}
                   if include_diffs else {}),
            })
        bill_id_map = _remote_bill_ids(client, bills_rows)
        for row in bills_rows:
            row["id"] = bill_id_map[row["id"]]
        # Small chunk: each bill row carries the diffs JSONB, so big batches
        # produce multi-MB request bodies that time out server-side.
        counts["bills"] = _upsert(
            client, "bills", bills_rows,
            on_conflict="jurisdiction,session_id,chamber,number",
            chunk=50,
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

        # 8. Encodings + rules + atoms + rule_variants.
        #
        # Skipped entirely when the local axiom_encodings table is empty:
        # a run that never indexed a rulespec checkout (state matrix jobs)
        # has nothing true to say about these tables, and pushing an
        # empty picture would corrupt what a federal run wrote.
        enc_rows = _rows(local, """
            SELECT id, jurisdiction, repo, kind, citation, file_path, indexed_at
              FROM axiom_encodings
        """)
        if not enc_rows:
            counts["axiom_encodings"] = 0
        else:
            # Remote file_path is unique; adopt the remote id where the
            # same file already exists so an id-churning local re-index
            # can't 23505 against it — mirroring how bills preserve ids.
            remote_encs = _remote_rows_by_in(
                client, "axiom_encodings",
                select="id,file_path",
                column="repo",
                values=(r["repo"] for r in enc_rows),
            )
            remote_by_path = {r["file_path"]: r["id"] for r in remote_encs}
            enc_id_map = {
                r["id"]: remote_by_path.get(r["file_path"], r["id"])
                for r in enc_rows
            }
            for r in enc_rows:
                r["id"] = enc_id_map[r["id"]]
            counts["axiom_encodings"] = _upsert(
                client, "axiom_encodings", enc_rows, on_conflict="file_path"
            )

            # A local index run owns the full slice for its repo(s):
            # remote encodings whose YAML vanished from the checkout are
            # stale — delete them (rules/atoms/variants cascade).
            local_paths = {r["file_path"] for r in enc_rows}
            stale_ids = sorted(
                r["id"] for r in remote_encs
                if r["file_path"] not in local_paths
            )
            for batch in _chunks(stale_ids, 100):
                resp = _send_with_retry(
                    lambda: client.delete(
                        "/axiom_encodings",
                        params={"id": f"in.({','.join(batch)})"},
                    ),
                    what="delete stale axiom_encodings",
                )
                if resp.status_code >= 300:
                    raise RuntimeError(
                        f"Supabase delete from axiom_encodings failed "
                        f"({resp.status_code}): {resp.text[:500]}"
                    )

            # encoded_rules/atoms get fresh uuids on every local re-index
            # and have no natural key remotely — upserting by id would
            # accumulate duplicates forever. Replace the slice instead:
            # delete remote rules for the encodings we're syncing (atoms
            # cascade), then insert.
            synced_enc_ids = sorted({r["id"] for r in enc_rows})
            for batch in _chunks(synced_enc_ids, 100):
                resp = _send_with_retry(
                    lambda: client.delete(
                        "/encoded_rules",
                        params={"encoding_id": f"in.({','.join(batch)})"},
                    ),
                    what="delete encoded_rules",
                )
                if resp.status_code >= 300:
                    raise RuntimeError(
                        f"Supabase delete from encoded_rules failed "
                        f"({resp.status_code}): {resp.text[:500]}"
                    )

            rule_rows = _rows(local, """
                SELECT id, encoding_id, rule_name, rule_kind, rule_source, rule_dtype,
                       module_corpus_citation_path, indexed_at
                  FROM encoded_rules
            """)
            for r in rule_rows:
                r["encoding_id"] = enc_id_map.get(r["encoding_id"], r["encoding_id"])
            counts["encoded_rules"] = _upsert(client, "encoded_rules", rule_rows, on_conflict="id")

            atom_rows = _rows(local, """
                SELECT id, rule_id, atom_path, atom_kind, corpus_citation_path, text
                  FROM encoded_rule_atoms
            """)
            counts["encoded_rule_atoms"] = _upsert(
                client, "encoded_rule_atoms", atom_rows, on_conflict="id"
            )

            # rule_variants — Pipeline B's per-bill patched YAML payloads.
            # Upsert on the natural key (bill_id, file_path); ids churn
            # with every local recompute, so adopt the remote id first
            # like every other child table.
            try:
                has_fingerprint = _has_column(
                    local, "rule_variants", "source_ops_fingerprint")
                extra_cols = (
                    ", source_ops_fingerprint, source_text_sha256"
                    if has_fingerprint else ""
                )
                rows = []
                for r in local.execute(f"""
                    SELECT id, bill_id, encoding_id, file_path, tier,
                           patched_rule_names, baseline_yaml, patched_yaml,
                           diff_summary, note, effective_from, computed_at,
                           proposed_by, proposed_model{extra_cols}
                      FROM rule_variants
                """):
                    rows.append({
                        "id": r["id"],
                        "bill_id": bill_id_map.get(r["bill_id"], r["bill_id"]),
                        "encoding_id": enc_id_map.get(r["encoding_id"], r["encoding_id"]),
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
                        **({
                            "source_ops_fingerprint": r["source_ops_fingerprint"],
                            "source_text_sha256": r["source_text_sha256"],
                        } if has_fingerprint else {}),
                    })
                child_id_map = _remote_child_ids(
                    client,
                    "rule_variants",
                    rows=rows,
                    select="file_path",
                    key_columns=("file_path",),
                )
                for row in rows:
                    row["id"] = child_id_map[row["id"]]
                counts["rule_variants"] = _upsert(
                    client, "rule_variants", rows,
                    on_conflict="bill_id,file_path", chunk=200,
                )
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                counts["rule_variants"] = 0

    local.close()
    return counts


def hydrate_llm_proposals(db_path: str) -> dict[str, int]:
    """Pull still-valid LLM proposals from Supabase into local SQLite.

    CI runs start from an empty SQLite, so proposals from earlier runs
    live only in Supabase. Run this after ``precompute-variants`` and
    before ``propose-llm-variants``: any remote proposal whose
    source_ops_fingerprint still matches the freshly computed local row
    is copied down, so the LLM is only called for genuinely new or
    changed variants — and the following ``sync-supabase`` pushes the
    hydrated values back instead of overwriting them with NULL.
    """
    counts = {"candidates": 0, "hydrated": 0, "stale_remote": 0}
    local = _local(db_path)
    try:
        pending = [dict(r) for r in local.execute("""
            SELECT v.id, v.bill_id, v.file_path, v.source_ops_fingerprint,
                   b.jurisdiction, b.session_id, b.chamber, b.number
              FROM rule_variants v
              JOIN bills b ON b.id = v.bill_id
             WHERE v.patched_yaml IS NULL
               AND v.tier IN ('list', 'structural')
               AND v.source_ops_fingerprint IS NOT NULL
        """)]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "no such column" in str(exc):
            local.close()
            return counts
        raise
    counts["candidates"] = len(pending)
    if not pending:
        local.close()
        return counts

    with _client() as client:
        session_rows = local.execute(
            "SELECT id, jurisdiction, name FROM sessions"
        ).fetchall()
        session_id_map = _remote_session_ids(client, session_rows)
        bill_lookup_rows = list({
            row["bill_id"]: {
                "id": row["bill_id"],
                "jurisdiction": row["jurisdiction"],
                "session_id": session_id_map.get(row["session_id"], row["session_id"]),
                "chamber": row["chamber"],
                "number": row["number"],
            }
            for row in pending
        }.values())
        bill_id_map = _remote_bill_ids(client, bill_lookup_rows)

        remote_rows = _remote_rows_by_in(
            client,
            "rule_variants",
            select=("bill_id,file_path,patched_yaml,proposed_by,"
                    "proposed_model,source_ops_fingerprint"),
            column="bill_id",
            values=(bill_id_map[r["bill_id"]] for r in pending),
        )
        remote_by_key = {
            (r["bill_id"], r["file_path"]): r
            for r in remote_rows
            if r["proposed_by"] == "llm" and r["patched_yaml"]
        }

        for row in pending:
            remote = remote_by_key.get(
                (bill_id_map[row["bill_id"]], row["file_path"])
            )
            if remote is None:
                continue
            if remote["source_ops_fingerprint"] != row["source_ops_fingerprint"]:
                counts["stale_remote"] += 1
                continue
            local.execute(
                """
                UPDATE rule_variants
                   SET patched_yaml = ?, proposed_by = 'llm',
                       proposed_model = ?, note = NULL
                 WHERE id = ?
                """,
                (remote["patched_yaml"], remote["proposed_model"], row["id"]),
            )
            counts["hydrated"] += 1
        local.commit()
    local.close()
    return counts
