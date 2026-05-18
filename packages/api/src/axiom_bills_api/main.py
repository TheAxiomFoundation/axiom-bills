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
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


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
            j.source_url,
            (SELECT COUNT(*) FROM bills b WHERE b.jurisdiction = j.code) AS bill_count,
            (SELECT COUNT(*) FROM bills b
              WHERE b.jurisdiction = j.code AND b.current_status = 'enacted') AS enacted_count
        FROM jurisdictions j
        ORDER BY CASE j.level WHEN 'federal' THEN 0 ELSE 1 END, j.name ASC
        """
    )


@app.get("/jurisdictions/{code}")
def get_jurisdiction(code: str) -> dict:
    rows = query("SELECT * FROM jurisdictions WHERE code = ?", (code,))
    if not rows:
        raise HTTPException(404, f"unknown jurisdiction: {code}")
    return rows[0]


@app.get("/jurisdictions/{code}/bills")
def bills_for_jurisdiction(
    code: str,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    params: list = [code]
    where = ["b.jurisdiction = ?"]
    if status:
        where.append("b.current_status = ?")
        params.append(status)
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT
            b.id, b.number, b.title, b.chamber,
            b.current_status, b.current_status_at,
            b.first_seen_at, b.source_url,
            s.name AS session_name
        FROM bills b
        JOIN sessions s ON s.id = b.session_id
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(b.current_status_at, b.first_seen_at) DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    return {"bills": rows, "limit": limit, "offset": offset}


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
    bill["actions"] = query(
        """
        SELECT occurred_at, chamber, action_text, normalized_status, source_url
        FROM bill_actions
        WHERE bill_id = ?
        ORDER BY occurred_at DESC
        """,
        (bill_id,),
    )
    bill["versions"] = query(
        """
        SELECT label, source_url, format, fetched_at
        FROM bill_versions
        WHERE bill_id = ?
        ORDER BY label
        """,
        (bill_id,),
    )
    return bill


@app.get("/recent")
def recent_status_changes(
    status: str = "enacted",
    limit: int = 50,
) -> list[dict]:
    """Cross-jurisdiction firehose by status change.

    Default = enacted: the canonical 'new law' feed Pipeline B subscribes to.
    """
    return query(
        """
        SELECT
            b.id, b.jurisdiction, b.number, b.title,
            b.current_status, b.current_status_at, b.source_url,
            j.name AS jurisdiction_name,
            j.level AS jurisdiction_level
        FROM bills b
        JOIN jurisdictions j ON j.code = b.jurisdiction
        WHERE b.current_status = ?
        ORDER BY b.current_status_at DESC
        LIMIT ?
        """,
        (status, limit),
    )
