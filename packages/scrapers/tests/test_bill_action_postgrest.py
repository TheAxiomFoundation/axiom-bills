"""Whole syncs against real PostgREST on real Postgres.

test_bill_action_identity.py runs the sync against a stand-in for PostgREST. This
file checks what the stand-in assumes, and that these tests can see the bug:

- Two runs of the old sync store every action twice.
- A repeat run of the new sync touches no row: id, ingested_at and xmin stay put.
- A payload without id and ingested_at takes their defaults on insert and leaves
  them alone on conflict.
- A read pages past PostgREST's 1,000-row limit.

These tests need the Postgres URL the row-level security tests use, plus the
PostgREST binary:

    AXIOM_BILLS_TEST_POSTGREST=/path/to/postgrest pytest

Without it they skip, except under CI, where they fail.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import httpx
import pytest

from axiom_bills._common import supabase_sync
from axiom_bills._common.models import BillAction
from axiom_bills.jurisdictions.us_md.bill.scrape import parse_bill as parse_maryland

from .test_bill_action_identity import ACTIONS, MARYLAND_ROW, _bill, _ci_run
from .test_supabase_row_level_security import (
    IN_CI,
    MIGRATIONS,
    Database,
    Server,
    replayable,  # noqa: F401 - a fixture
    server,  # noqa: F401 - a fixture
)

POSTGREST = os.environ.get("AXIOM_BILLS_TEST_POSTGREST")
JWT_SECRET = "a-secret-for-these-tests-and-nothing-else"


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _service_token() -> str:
    signing_input = ".".join(
        _base64url(json.dumps(part).encode())
        for part in ({"alg": "HS256", "typ": "JWT"}, {"role": "service_role"})
    )
    signature = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url(signature)}"


@pytest.fixture(scope="session")
def bills_schema(replayable: Server) -> Database:  # noqa: F811 - a fixture
    database = replayable.create_database()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        database.run_file(path)
    return database


@dataclass(frozen=True)
class LiveRest:
    database: Database
    url: str

    def actions(self) -> list[dict]:
        """Every stored action, with what shows whether a write touched it."""
        return json.loads(self.database.run(
            "select coalesce(jsonb_agg(to_jsonb(row) order by row.id), '[]') from ("
            " select *, xmin::text as stored_by, ctid::text as place from bills.bill_actions"
            ") as row"
        ))


@pytest.fixture
def live_rest(
    replayable: Server,  # noqa: F811 - a fixture
    bills_schema: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LiveRest]:
    if not POSTGREST:
        if IN_CI:
            pytest.fail("CI is set, but AXIOM_BILLS_TEST_POSTGREST isn't, so these checks can't run")
        pytest.skip("AXIOM_BILLS_TEST_POSTGREST is not set")
    database = replayable.create_database(template=bills_schema)
    # Production holds the old table, without the key that only the cleanup adds.
    database.run("drop index if exists bills.bill_actions_event_key")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [POSTGREST],
        env={
            "PGRST_DB_URI": database.url,
            "PGRST_DB_SCHEMAS": "bills",
            "PGRST_DB_ANON_ROLE": "anon",
            "PGRST_DB_MAX_ROWS": "1000",
            "PGRST_DB_POOL": "2",
            "PGRST_JWT_SECRET": JWT_SECRET,
            "PGRST_SERVER_HOST": "127.0.0.1",
            "PGRST_SERVER_PORT": str(port),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    token = _service_token()
    try:
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                pytest.fail(f"PostgREST exited: {process.stdout.read()}")
            try:
                if httpx.get(url, headers={"Authorization": f"Bearer {token}"}).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("PostgREST didn't start within 30 seconds")
            time.sleep(0.2)
        monkeypatch.setattr(supabase_sync, "SUPABASE_URL", url)
        monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", token)
        monkeypatch.setattr(supabase_sync, "REST", url)
        yield LiveRest(database, url)
    finally:
        process.terminate()
        process.wait(timeout=10)
        replayable.drop_database(database)


def _old_sync_actions(client: httpx.Client, local: sqlite3.Connection,
                      bill_id_map: dict[str, str]) -> int:
    """Section 4 of sync() as it ran until this fix, with its fingerprint."""
    rows = []
    for r in local.execute("""
        SELECT id, bill_id, occurred_at, chamber, action_text,
               normalized_status, source_url, ingested_at
          FROM bill_actions
    """):
        digest = hashlib.sha256()
        digest.update(r["bill_id"].encode())
        digest.update(r["occurred_at"].encode())
        digest.update(r["action_text"].encode())
        rows.append({
            "id": r["id"],
            "bill_id": bill_id_map.get(r["bill_id"], r["bill_id"]),
            "occurred_at": r["occurred_at"],
            "chamber": r["chamber"],
            "action_text": r["action_text"],
            "normalized_status": r["normalized_status"],
            "source_url": r["source_url"],
            "fingerprint": digest.hexdigest(),
            "ingested_at": r["ingested_at"],
        })
    child_id_map = supabase_sync._remote_child_ids(
        client, "bill_actions", rows=rows, select="fingerprint", key_columns=("fingerprint",),
    )
    for row in rows:
        row["id"] = child_id_map[row["id"]]
    return supabase_sync._upsert(client, "bill_actions", rows, on_conflict="bill_id,fingerprint")


def test_the_old_sync_stores_a_copy_per_run_and_the_new_one_adds_none(
    tmp_path, live_rest, monkeypatch
) -> None:
    with monkeypatch.context() as old_code:
        old_code.setattr(supabase_sync, "_sync_actions", _old_sync_actions)
        _ci_run(tmp_path, [_bill(ACTIONS)], "old-first")
        _ci_run(tmp_path, [_bill(ACTIONS)], "old-second")
    copies = live_rest.actions()
    assert len(copies) == 2 * len(ACTIONS)

    counts = _ci_run(tmp_path, [_bill(ACTIONS)], "new")

    assert counts["bill_actions"] == 0
    assert live_rest.actions() == copies


def test_a_repeat_run_touches_no_row(tmp_path, live_rest) -> None:
    first = _ci_run(tmp_path, [_bill(ACTIONS), _bill(ACTIONS, number="HB2")], "first")
    stored = live_rest.actions()
    assert first["bill_actions"] == len(stored) == 2 * len(ACTIONS)

    second = _ci_run(tmp_path, [_bill(ACTIONS), _bill(ACTIONS, number="HB2")], "second")

    assert second["bill_actions"] == 0
    assert live_rest.actions() == stored


def test_a_new_row_takes_the_column_defaults(tmp_path, live_rest) -> None:
    _ci_run(tmp_path, [_bill(ACTIONS)], "first")
    local = sqlite3.connect(tmp_path / "first.sqlite")
    local_ids = {row[0] for row in local.execute("SELECT id FROM bill_actions")}
    local.close()

    stored = live_rest.actions()

    assert {row["id"].replace("-", "") for row in stored}.isdisjoint(local_ids)
    assert live_rest.database.run(
        "select bool_and(ingested_at > now() - interval '5 minutes') from bills.bill_actions"
    ) == "t"


def test_a_metadata_fix_keeps_the_id_and_first_stored_time(tmp_path, live_rest) -> None:
    _ci_run(tmp_path, [_bill(ACTIONS)], "first")
    before = {row["fingerprint"]: row for row in live_rest.actions()}
    fixed = [ACTIONS[0].model_copy(update={"source_url": "https://example.test/fixed"}), *ACTIONS[1:]]

    counts = _ci_run(tmp_path, [_bill(fixed)], "second")

    after = {row["fingerprint"]: row for row in live_rest.actions()}
    assert counts["bill_actions"] == 1
    assert after.keys() == before.keys()
    changed = [f for f in after if after[f] != before[f]]
    assert len(changed) == 1
    row, original = after[changed[0]], before[changed[0]]
    assert row["source_url"] == "https://example.test/fixed"
    assert row["id"] == original["id"]
    assert row["ingested_at"] == original["ingested_at"]
    assert row["occurred_at"] == original["occurred_at"]


def test_maryland_keeps_one_row_and_its_first_date_when_the_feed_moves(tmp_path, live_rest) -> None:
    row = {**MARYLAND_ROW, "PassedByMGA": True}

    def scrape(stamp: str):
        bill = parse_maryland({**row, "StatusCurrentAsOf": stamp}, "2026", 2026)
        assert bill is not None
        return bill.model_copy(update={"jurisdiction": "us-zz"})

    _ci_run(tmp_path, [scrape("2026-02-04T17:45:08.947")], "first")
    stored = live_rest.actions()

    counts = _ci_run(tmp_path, [scrape("2026-02-05T09:12:44.103")], "second")

    assert counts["bill_actions"] == 0
    assert live_rest.actions() == stored
    assert live_rest.database.run(
        "select occurred_at from bills.bill_actions where action_text = 'Passed by the General Assembly'"
    ) == "2026-02-04 17:45:08.947+00"


def test_a_read_pages_past_the_row_limit(tmp_path, live_rest) -> None:
    action = BillAction(occurred_at=datetime(2026, 1, 5), action_text="Introduced")
    _ci_run(tmp_path, [_bill([action])], "first")
    # 1,500 old copies. The latest ingest sorts last by fingerprint, so a read
    # that stops at PostgREST's limit never sees it.
    live_rest.database.run("""
        insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint, ingested_at)
        select bill_id, occurred_at, action_text, md5(i::text) || md5(i::text),
               timestamptz '2026-06-02' + i * interval '1 minute'
          from bills.bill_actions, generate_series(1, 1500) as i;
        insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint, ingested_at)
        select bill_id, occurred_at, action_text, repeat('f', 64), timestamptz '2026-08-13'
          from bills.bill_actions limit 1;
        update bills.bill_actions
           set fingerprint = md5(ingested_at::text) || md5(ingested_at::text),
               ingested_at = timestamptz '2026-06-01'
         where fingerprint like 'a1:%';
    """)
    before = len(live_rest.actions())
    fixed = action.model_copy(update={"source_url": "https://example.test/fixed"})

    counts = _ci_run(tmp_path, [_bill([fixed])], "second")

    assert counts["bill_actions"] == 1
    assert len(live_rest.actions()) == before
    assert live_rest.database.run(
        "select fingerprint from bills.bill_actions where source_url is not null"
    ) == "f" * 64
