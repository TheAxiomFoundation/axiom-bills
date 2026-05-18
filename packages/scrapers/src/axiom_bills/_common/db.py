"""Writer: ScrapeResult → SQLite.

Upserts bills by (jurisdiction, session, chamber, number). Inserts actions
keyed by fingerprint so a re-scrape is idempotent and append-only. After
actions land, refresh bill.current_status from the highest-ranked action.

The DB path defaults to ~/axiom-bills/db/axiom_bills.sqlite. Override with
AXIOM_BILLS_DB env var.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import Bill, BillAction, NormalizedStatus, ScrapeResult, STATUS_ORDER


def _default_db_path() -> str:
    here = Path(__file__).resolve()
    # packages/scrapers/src/axiom_bills/_common/db.py → repo root four levels up
    repo_root = here.parents[4]
    return str(repo_root / "db" / "axiom_bills.sqlite")


DEFAULT_DB = os.environ.get("AXIOM_BILLS_DB") or _default_db_path()


@contextmanager
def connect(path: str = DEFAULT_DB):
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; we BEGIN explicitly
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _new_id() -> str:
    return uuid.uuid4().hex


def _fingerprint(bill_id: str, action: BillAction) -> str:
    h = hashlib.sha256()
    h.update(bill_id.encode())
    h.update(action.occurred_at.isoformat().encode())
    h.update(action.action_text.encode())
    return h.hexdigest()


def write(result: ScrapeResult, db_path: str = DEFAULT_DB) -> dict[str, int]:
    """Persist a ScrapeResult. Returns counts for the audit log."""
    counts = {"bills_seen": len(result.bills), "bills_new": 0, "actions_new": 0}

    with connect(db_path) as conn:
        session_id = _upsert_session(conn, result)

        for bill in result.bills:
            bill_id, is_new = _upsert_bill(conn, bill, session_id)
            if is_new:
                counts["bills_new"] += 1
            counts["actions_new"] += _insert_actions(conn, bill_id, bill.actions)
            _upsert_versions(conn, bill_id, bill.versions)
            _refresh_current_status(conn, bill_id)

        conn.execute(
            """
            INSERT INTO scrape_runs (id, jurisdiction, finished_at,
                                     bills_seen, bills_new, actions_new)
            VALUES (?, ?, datetime('now'), ?, ?, ?)
            """,
            (
                _new_id(),
                result.jurisdiction,
                counts["bills_seen"],
                counts["bills_new"],
                counts["actions_new"],
            ),
        )

    return counts


def _upsert_session(conn: sqlite3.Connection, result: ScrapeResult) -> str:
    row = conn.execute(
        "SELECT id FROM sessions WHERE jurisdiction = ? AND name = ?",
        (result.jurisdiction, result.session.name),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE sessions
               SET start_date = COALESCE(?, start_date),
                   end_date   = COALESCE(?, end_date),
                   is_current = ?
             WHERE id = ?
            """,
            (
                result.session.start_date.isoformat() if result.session.start_date else None,
                result.session.end_date.isoformat() if result.session.end_date else None,
                1 if result.session.is_current else 0,
                row["id"],
            ),
        )
        return row["id"]
    new_id = _new_id()
    conn.execute(
        """
        INSERT INTO sessions (id, jurisdiction, name, start_date, end_date, is_current)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_id,
            result.jurisdiction,
            result.session.name,
            result.session.start_date.isoformat() if result.session.start_date else None,
            result.session.end_date.isoformat() if result.session.end_date else None,
            1 if result.session.is_current else 0,
        ),
    )
    return new_id


def _upsert_bill(
    conn: sqlite3.Connection, bill: Bill, session_id: str
) -> tuple[str, bool]:
    existing = conn.execute(
        """
        SELECT id FROM bills
         WHERE jurisdiction = ? AND session_id = ?
           AND chamber = ?      AND number = ?
        """,
        (bill.jurisdiction, session_id, bill.chamber.value, bill.number),
    ).fetchone()

    sponsors_json = json.dumps([s.model_dump() for s in bill.sponsors])
    subjects_json = json.dumps(bill.subjects)

    if existing:
        conn.execute(
            """
            UPDATE bills
               SET title           = COALESCE(?, title),
                   summary         = COALESCE(?, summary),
                   subjects        = ?,
                   sponsors        = ?,
                   source_url      = ?,
                   last_scraped_at = datetime('now')
             WHERE id = ?
            """,
            (
                bill.title, bill.summary, subjects_json, sponsors_json,
                bill.source_url, existing["id"],
            ),
        )
        return existing["id"], False

    new_id = _new_id()
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           title, summary, subjects, sponsors, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id, bill.jurisdiction, session_id, bill.chamber.value, bill.number,
            bill.title, bill.summary, subjects_json, sponsors_json, bill.source_url,
        ),
    )
    return new_id, True


def _insert_actions(
    conn: sqlite3.Connection, bill_id: str, actions: list[BillAction]
) -> int:
    if not actions:
        return 0
    inserted = 0
    for action in actions:
        fp = _fingerprint(bill_id, action)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO bill_actions
                (id, bill_id, occurred_at, chamber, action_text,
                 normalized_status, source_url, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id(),
                bill_id,
                action.occurred_at.isoformat(),
                action.chamber.value if action.chamber else None,
                action.action_text,
                action.normalized_status.value if action.normalized_status else None,
                action.source_url,
                fp,
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    return inserted


def _upsert_versions(conn: sqlite3.Connection, bill_id: str, versions) -> None:
    for v in versions:
        existing = conn.execute(
            "SELECT id FROM bill_versions WHERE bill_id = ? AND label = ?",
            (bill_id, v.label),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE bill_versions SET source_url = ?, format = ? WHERE id = ?",
                (v.source_url, v.format, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO bill_versions (id, bill_id, label, source_url, format)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_new_id(), bill_id, v.label, v.source_url, v.format),
            )


def _refresh_current_status(conn: sqlite3.Connection, bill_id: str) -> None:
    """Roll up bill_actions → bills.current_status using STATUS_ORDER."""
    rows = conn.execute(
        """
        SELECT normalized_status, occurred_at
          FROM bill_actions
         WHERE bill_id = ? AND normalized_status IS NOT NULL
        """,
        (bill_id,),
    ).fetchall()
    if not rows:
        return
    best_rank = -1
    best: tuple[str, str] | None = None
    for row in rows:
        status = NormalizedStatus(row["normalized_status"])
        rank = STATUS_ORDER[status]
        if rank > best_rank:
            best_rank = rank
            best = (status.value, row["occurred_at"])
    if best is not None:
        conn.execute(
            "UPDATE bills SET current_status = ?, current_status_at = ? WHERE id = ?",
            (best[0], best[1], bill_id),
        )
