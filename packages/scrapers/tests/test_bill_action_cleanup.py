"""The cleanup in supabase/manual/bill_action_cleanup.sql, on real Postgres.

Nothing here touches production. These tests run the cleanup's real driver and
SQL on throwaway databases, as a table owner who isn't a superuser, as on Supabase.

They check that:

- the SQL fingerprint matches db.action_fingerprint, in any session zone;
- the kept rows match a model worked out without SQL: one row per action, the
  earliest stored time, the last copy's metadata, and one row per Maryland text
  for the feed's snapshot times, whatever the batch size;
- a stop anywhere loses nothing, and a batch out of order fails;
- the driver reads each kind of reply the real Management API gives;
- the old table refuses every write from prepare on, and API roles read it as
  before and can't reach the cleanup's schemas;
- after the swap, the table's columns, constraints, indexes, policies and grants
  match what it held before prepare, plus the event key;
- swap refuses a new table or an old table that doesn't match, naming the problem;
- swap-back and abort return the original table, row for row, once its unique
  index is back;
- a sync through real PostgREST after the swap adds nothing.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import ClassVar

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from axiom_bills._common import supabase_sync
from axiom_bills._common.db import action_fingerprint, action_instant
from axiom_bills.jurisdictions.us_md.bill.scrape import parse_bill as parse_maryland

from .test_bill_action_identity import ACTIONS, MARYLAND_ROW, _bill, _ci_run, free_text, moments
from .test_bill_action_postgrest import (
    _old_sync_actions,
    bills_schema,  # noqa: F401 - a fixture
    live_rest,  # noqa: F401 - a fixture
)
from .test_supabase_row_level_security import (
    MIGRATIONS,
    Database,
    PsqlError,
    Server,
    replayable,  # noqa: F401 - a fixture
    server,  # noqa: F401 - a fixture
)

DRIVER_PATH = Path(__file__).resolve().parents[3] / "supabase" / "manual" / "bill_action_cleanup.py"
MIGRATION = next(MIGRATIONS.glob("*_bill_action_event_key.sql"))
OWNER = "bill_action_cleanup_test_owner"
UTC = timezone.utc

MARYLAND = "00000000-0000-4000-8000-0000000000aa"
OTHER = "00000000-0000-4000-8000-0000000000bb"
SESSION = "00000000-0000-4000-8000-0000000000cc"


def _load_driver():
    spec = importlib.util.spec_from_file_location("bill_action_cleanup_driver", DRIVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


driver = _load_driver()


class OwnerPsql(driver.Psql):
    """The driver's own connection, as a table owner without superuser rights."""

    def run(self, sql: str) -> str:
        return super().run(f"set role {OWNER};\n{sql}")


@dataclass(frozen=True)
class Cleanup:
    """A database holding the old table, and the cleanup's driver pointed at it."""

    database: Database
    connection: driver.Psql

    def step(self, step: str, **options):
        return driver.run_step(self.connection, step, say=lambda _: None, **options)

    def through_build(self, **options) -> None:
        self.step("install")
        self.step("prepare")
        self.step("copy", **options)
        self.step("build")

    def through_verify(self, **options) -> None:
        self.through_build(**options)
        self.step("verify", **options)

    def actions(self) -> list[dict]:
        return json.loads(self.database.run(
            "select coalesce(jsonb_agg(to_jsonb(row) order by row.bill_id, row.occurred_at, row.action_text), '[]')"
            " from bills.bill_actions as row"
        ))


@pytest.fixture(scope="session")
def owner_role(replayable: Server) -> Iterator[str]:  # noqa: F811 - a fixture
    if replayable.admin.run(f"select count(*) from pg_roles where rolname = '{OWNER}'") == "0":
        replayable.admin.run(f"create role {OWNER} nologin")
    yield OWNER
    # The databases that gave the role anything went when their tests ended.
    replayable.admin.run(f"drop role if exists {OWNER}")


def _owned_by_a_plain_role(database: Database) -> Cleanup:
    """On Supabase, the postgres role owns these and isn't a superuser."""
    database.run(f"""
        grant create on database {database.name} to {OWNER};
        alter schema bills owner to {OWNER};
        alter table bills.bill_actions owner to {OWNER};
        alter table bills.bills owner to {OWNER};
    """)
    return Cleanup(database, OwnerPsql(database.url))


def _old_table_in(database: Database) -> Cleanup:
    """Give the database the state production holds before the cleanup."""
    database.run(f"""
        drop index if exists bills.bill_actions_event_key;
        insert into bills.jurisdictions (code, name, level, source_url) values
          ('us-md', 'Maryland', 'state', 'https://example.test/'),
          ('zz', 'Test state', 'state', 'https://example.test/')
          on conflict do nothing;
        insert into bills.sessions (id, jurisdiction, name) values ('{SESSION}', 'zz', 'Test session');
        insert into bills.bills (id, jurisdiction, session_id, chamber, number, source_url, title) values
          ('{MARYLAND}', 'us-md', '{SESSION}', 'lower', 'HB 1', 'https://example.test/hb1', 'Maryland bill'),
          ('{OTHER}', 'zz', '{SESSION}', 'lower', 'HB 2', 'https://example.test/hb2', 'Other bill');
    """)
    return _owned_by_a_plain_role(database)


@contextmanager
def _fresh_old_table(server_: Server, template: Database) -> Iterator[Cleanup]:
    database = server_.create_database(template=template)
    try:
        yield _old_table_in(database)
    finally:
        server_.drop_database(database)


@pytest.fixture
def old_table(
    replayable: Server,  # noqa: F811 - a fixture
    bills_schema: Database,  # noqa: F811 - a fixture
    owner_role: str,
) -> Iterator[Cleanup]:
    with _fresh_old_table(replayable, bills_schema) as cleanup:
        yield cleanup


def _sql_text(value: str | None) -> str:
    if value is None:
        return "null"
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class Copy:
    """One stored row, in the order the old syncs stored them."""

    bill: str
    occurred: datetime
    text: str
    hours_in: int = 0
    chamber: str | None = None
    status: str | None = None
    url: str | None = None


FIRST_REFRESH = datetime(2026, 6, 2, tzinfo=UTC)
# A long URL fills the page, so a few rows span several heap pages and batches.
PADDING = "x" * 1500


def _store(database: Database, copies: list[Copy]) -> list[str]:
    """Insert in order, each under a bare hash as the old sync did. Returns the ids."""
    if not copies:
        return []
    rows = ",\n".join(
        "(" + ", ".join([
            _sql_text(copy.bill) + "::uuid",
            _sql_text(copy.occurred.isoformat()) + "::timestamptz",
            f"{_sql_text(copy.chamber)}::bills.chamber",
            _sql_text(copy.text),
            f"{_sql_text(copy.status)}::bills.normalized_status",
            _sql_text(f"{copy.url}{PADDING}" if copy.url else None),
            f"md5('{place}') || md5('{place}')",
            _sql_text((FIRST_REFRESH + timedelta(hours=copy.hours_in)).isoformat()) + "::timestamptz",
        ]) + ")"
        for place, copy in enumerate(copies)
    )
    # returning gives back the insert's order, and a single insert fills the heap
    # in the same order.
    out = database.run(f"""
        insert into bills.bill_actions
          (bill_id, occurred_at, chamber, action_text, normalized_status, source_url, fingerprint, ingested_at)
        values {rows}
        returning id
    """)
    return out.split()


def _snapshot_stamp(moment: datetime) -> bool:
    return moment.second != 0 or moment.microsecond != 0


def _model(copies: list[Copy], ids: list[str]) -> list[dict]:
    """What the kept rows should hold, worked out without any SQL.

    A kept row's id comes from one of its copies, so "ids" lists them.
    """
    kept: dict[tuple, dict] = {}
    for copy, row_id in zip(copies, ids, strict=True):
        undated = copy.bill == MARYLAND and _snapshot_stamp(copy.occurred)
        moment = action_instant(copy.occurred)
        key = (copy.bill, copy.text) if undated else (copy.bill, moment, copy.text)
        stored = FIRST_REFRESH + timedelta(hours=copy.hours_in)
        known = kept.get(key)
        kept[key] = {
            "ids": {*(known["ids"] if known else ()), row_id},
            "bill_id": copy.bill,
            "action_text": copy.text,
            "occurred_at": min(moment, known["occurred_at"]) if known else moment,
            "ingested_at": min(stored, known["ingested_at"]) if known else stored,
            "chamber": copy.chamber,
            "normalized_status": copy.status,
            "source_url": f"{copy.url}{PADDING}" if copy.url else None,
            "fingerprint": action_fingerprint(moment, copy.text, undated=undated),
        }
    return sorted(kept.values(), key=lambda row: (row["bill_id"], row["occurred_at"], row["action_text"]))


def _parsed(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({
            **{k: row[k] for k in ("id", "bill_id", "action_text", "chamber", "normalized_status",
                                   "source_url", "fingerprint")},
            "occurred_at": datetime.fromisoformat(row["occurred_at"]).astimezone(UTC),
            "ingested_at": datetime.fromisoformat(row["ingested_at"]).astimezone(UTC),
        })
    return sorted(out, key=lambda row: (row["bill_id"], row["occurred_at"], row["action_text"]))


def _assert_matches_the_model(cleanup: Cleanup, copies: list[Copy], ids: list[str]) -> None:
    found, expected = _parsed(cleanup.actions()), _model(copies, ids)
    for row, model in zip(found, expected, strict=False):
        assert row["id"] in model["ids"]
    without_ids = [{k: v for k, v in row.items() if k != "id"} for row in found]
    assert without_ids == [{k: v for k, v in row.items() if k != "ids"} for row in expected]


def _catalog(database: Database) -> dict:
    """The table as the API sees it, read independently of the cleanup's checks."""
    return json.loads(database.run("""
        select jsonb_build_object(
          'columns', (select jsonb_agg(jsonb_build_array(a.attname, format_type(a.atttypid, a.atttypmod),
                                                         a.attnotnull, pg_get_expr(d.adbin, d.adrelid))
                                       order by a.attnum)
                        from pg_attribute a
                        left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
                       where a.attrelid = 'bills.bill_actions'::regclass and a.attnum > 0 and not a.attisdropped),
          'constraints', (select jsonb_object_agg(conname, pg_get_constraintdef(oid))
                            from pg_constraint where conrelid = 'bills.bill_actions'::regclass),
          'indexes', (select jsonb_object_agg(c.relname, pg_get_indexdef(i.indexrelid))
                        from pg_index i join pg_class c on c.oid = i.indexrelid
                       where i.indrelid = 'bills.bill_actions'::regclass),
          'policies', (select jsonb_agg(to_jsonb(p) order by p.policyname) from pg_policies p
                        where p.schemaname = 'bills' and p.tablename = 'bill_actions'),
          'acl', (select jsonb_agg(item::text order by item::text)
                    from pg_class c, unnest(c.relacl) as item where c.oid = 'bills.bill_actions'::regclass),
          'security', (select jsonb_build_array(relrowsecurity, relforcerowsecurity, reloptions)
                         from pg_class where oid = 'bills.bill_actions'::regclass),
          'triggers', (select coalesce(jsonb_agg(tgname order by tgname), '[]') from pg_trigger
                        where tgrelid = 'bills.bill_actions'::regclass and not tgisinternal)
        )
    """))


# --- The fingerprint in two languages ----------------------------------------


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    actions=st.lists(st.tuples(moments, free_text, st.booleans()), min_size=1, max_size=20),
    zone=st.sampled_from(["UTC", "America/New_York", "Asia/Kolkata"]),
)
def test_the_sql_fingerprint_matches_the_python_one(fingerprint_database, actions, zone) -> None:
    payload = json.dumps([
        {"at": action_instant(moment).isoformat(), "text": text, "undated": undated}
        for moment, text, undated in actions
    ])
    out = fingerprint_database.run(f"""
        set timezone = '{zone}';
        select jsonb_agg(
          bill_action_cleanup.action_fingerprint(
            (item->>'at')::timestamptz, item->>'text', (item->>'undated')::boolean)
          order by place)
          from jsonb_array_elements($payload$ {payload} $payload$::jsonb) with ordinality as x(item, place)
    """)

    assert json.loads(out) == [
        action_fingerprint(moment, text, undated=undated) for moment, text, undated in actions
    ]


@pytest.mark.parametrize(
    "moment",
    [
        datetime(1, 1, 1, tzinfo=UTC),
        # What a two-digit year in a feed would parse to.
        datetime(26, 1, 14, tzinfo=UTC),
        datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    ],
)
def test_the_two_fingerprints_agree_at_the_edges_of_the_calendar(fingerprint_database, moment) -> None:
    out = fingerprint_database.run(
        f"select bill_action_cleanup.action_fingerprint('{moment.isoformat()}'::timestamptz, 'Text', false)"
    )

    assert out == action_fingerprint(moment, "Text")


@pytest.fixture(scope="module")
def fingerprint_database(
    replayable: Server,  # noqa: F811 - a fixture
    bills_schema: Database,  # noqa: F811 - a fixture
) -> Iterator[Database]:
    database = replayable.create_database(template=bills_schema)
    database.run(driver.SQL_FILE.read_text(encoding="utf-8"))
    yield database
    replayable.drop_database(database)


# --- What the cleanup keeps ----------------------------------------------------

# A small pool, so copies of one action come up often. Times on the minute count
# as real dates in Maryland, and the rest as the feed's snapshot times.
DAYS = [datetime(2026, 1, day, tzinfo=UTC) for day in (5, 6)]
HEARING = [datetime(2026, 1, 20, 13, tzinfo=UTC)]
STAMPS = [
    datetime(2026, 6, 2, 11, 25, 6, 100000, tzinfo=UTC),
    datetime(2026, 6, 3, 8, 1, 44, 947000, tzinfo=UTC),
    datetime(2026, 8, 13, 10, 15, 9, 30000, tzinfo=UTC),
    datetime(2026, 7, 1, 2, 3, 4, tzinfo=UTC),
]
pool_moments = st.sampled_from(DAYS + HEARING + STAMPS)
pool_texts = st.sampled_from(["Introduced", "Passed by the General Assembly", "Signed"]) | free_text
copies_of_actions = st.lists(
    st.tuples(
        st.sampled_from([MARYLAND, OTHER]),
        pool_moments,
        pool_texts,
        st.sampled_from([None, "lower", "upper"]),
        st.sampled_from([None, "introduced", "signed"]),
        st.sampled_from([None, "https://example.test/a", "https://example.test/b"]),
    ),
    max_size=40,
).map(lambda rows: [
    # In the order they arrive, so heap order and ingest order agree.
    Copy(bill, moment, text, hours_in=place // 4, chamber=chamber, status=status, url=url)
    for place, (bill, moment, text, chamber, status, url) in enumerate(rows)
])


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(copies=copies_of_actions, pages=st.sampled_from([1, 2, 3, 1000]))
def test_the_kept_rows_match_the_model(
    replayable,  # noqa: F811 - a fixture
    bills_schema,  # noqa: F811 - a fixture
    owner_role,
    copies,
    pages,
) -> None:
    with _fresh_old_table(replayable, bills_schema) as cleanup:
        ids = _store(cleanup.database, copies)

        cleanup.through_verify(pages=pages)
        status = cleanup.step("status")
        problems = cleanup.step("problems")
        cleanup.step("swap")

        _assert_matches_the_model(cleanup, copies, ids)
        assert problems == []
        assert status["rows_read"] == status["rows_verified"] == len(copies)
        assert status["rows_missing"] == 0
        assert status["rows_kept"] == len(_model(copies, ids))


def test_a_refresh_of_copies_collapses_to_one_row_per_action(old_table) -> None:
    copies = [
        Copy(OTHER, DAYS[0], "Introduced", hours_in=run, url="https://example.test/a")
        for run in range(30)
    ] + [
        Copy(OTHER, DAYS[1], "Referred", hours_in=run) for run in range(30)
    ]
    _store(old_table.database, copies)

    old_table.through_verify(pages=1)
    old_table.step("swap")

    rows = _parsed(old_table.actions())
    assert [r["action_text"] for r in rows] == ["Introduced", "Referred"]
    assert {r["ingested_at"] for r in rows} == {FIRST_REFRESH}


def test_maryland_stamps_collapse_and_real_dates_stay(old_table) -> None:
    copies = [
        Copy(MARYLAND, DAYS[0], "First reading", hours_in=0),
        Copy(MARYLAND, STAMPS[0], "Passed by the General Assembly", hours_in=0),
        Copy(MARYLAND, DAYS[0], "First reading", hours_in=1),
        Copy(MARYLAND, STAMPS[1], "Passed by the General Assembly", hours_in=1),
        Copy(MARYLAND, STAMPS[2], "Passed by the General Assembly", hours_in=2),
        # The same stamps in another state are real times, so they stay.
        Copy(OTHER, STAMPS[0], "Work Session held.", hours_in=0),
        Copy(OTHER, STAMPS[1], "Work Session held.", hours_in=1),
    ]
    _store(old_table.database, copies)

    old_table.through_verify()
    old_table.step("swap")

    rows = _parsed(old_table.actions())
    by_bill = {
        bill: sorted((r["action_text"], r["occurred_at"]) for r in rows if r["bill_id"] == bill)
        for bill in (MARYLAND, OTHER)
    }
    assert by_bill[MARYLAND] == [
        ("First reading", DAYS[0]),
        ("Passed by the General Assembly", STAMPS[0]),
    ]
    assert by_bill[OTHER] == [("Work Session held.", STAMPS[0]), ("Work Session held.", STAMPS[1])]
    passed = next(r for r in rows if r["action_text"].startswith("Passed"))
    assert passed["fingerprint"] == action_fingerprint(STAMPS[0], passed["action_text"], undated=True)


def test_the_latest_ingest_wins_within_a_batch_even_when_the_heap_disagrees(old_table) -> None:
    _store(old_table.database, [
        Copy(OTHER, DAYS[0], "Introduced", hours_in=5, url="https://example.test/latest"),
        Copy(OTHER, DAYS[0], "Introduced", hours_in=1, url="https://example.test/older"),
    ])

    old_table.through_verify()
    old_table.step("swap")

    rows = _parsed(old_table.actions())
    assert len(rows) == 1
    assert rows[0]["source_url"].startswith("https://example.test/latest")
    assert rows[0]["ingested_at"] == FIRST_REFRESH + timedelta(hours=1)


def _pages_holding(database: Database, text: str) -> set[str]:
    return set(database.run(f"""
        select distinct (ctid::text::point)[0]::bigint from bills.bill_actions
         where action_text = {_sql_text(text)}
    """).split())


# Enough long rows to push whatever follows them onto another heap page.
FILLER = [
    Copy(OTHER, DAYS[1], f"Filler {place}", url="https://example.test/filler") for place in range(8)
]


def test_a_later_batch_brings_the_kept_row_up_to_date(old_table) -> None:
    _store(old_table.database, [
        Copy(OTHER, DAYS[0], "Introduced", hours_in=0, chamber="lower", status="introduced",
             url="https://example.test/first"),
        Copy(OTHER, DAYS[0], "Referred", hours_in=0, chamber="lower", url="https://example.test/first"),
        *FILLER,
        Copy(OTHER, DAYS[0], "Introduced", hours_in=2, chamber="upper", status="signed",
             url="https://example.test/last"),
        # A later copy can also clear a field.
        Copy(OTHER, DAYS[0], "Referred", hours_in=2, chamber=None, url="https://example.test/last"),
    ])
    assert len(_pages_holding(old_table.database, "Introduced")) == 2
    assert len(_pages_holding(old_table.database, "Referred")) == 2

    old_table.through_verify(pages=1)
    changed = old_table.step("status")["rows_changed"]
    old_table.step("swap")

    rows = {row["action_text"]: row for row in _parsed(old_table.actions())}
    assert changed == 2
    assert (rows["Introduced"]["chamber"], rows["Introduced"]["normalized_status"]) == ("upper", "signed")
    assert rows["Introduced"]["source_url"].startswith("https://example.test/last")
    assert rows["Referred"]["chamber"] is None
    assert rows["Introduced"]["ingested_at"] == FIRST_REFRESH


def test_between_batches_the_last_page_decides_even_over_a_later_ingest(old_table) -> None:
    """Intended. A batch can't tell which ingest time the kept row's fields came from,
    and tracking it would add a write for nearly every row of the old table. These
    fields rarely differ, and the next scrape writes over them whichever copy won."""
    _store(old_table.database, [
        Copy(OTHER, DAYS[0], "Introduced", hours_in=5, url="https://example.test/latest-ingest"),
        *FILLER,
        Copy(OTHER, DAYS[0], "Introduced", hours_in=1, url="https://example.test/last-page"),
    ])
    assert len(_pages_holding(old_table.database, "Introduced")) == 2

    old_table.through_verify(pages=1)
    old_table.step("swap")

    row = next(row for row in _parsed(old_table.actions()) if row["action_text"] == "Introduced")
    assert row["source_url"].startswith("https://example.test/last-page")
    assert row["ingested_at"] == FIRST_REFRESH + timedelta(hours=1)


def test_every_scheme_the_sync_writes_lands_in_the_new_table(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced"), Copy(MARYLAND, STAMPS[0], "Passed")])

    old_table.through_verify()
    old_table.step("swap")

    assert all(
        re.fullmatch(r"(a1|u1):[0-9a-f]{64}", row["fingerprint"]) for row in old_table.actions()
    )


# --- Stops, order and refusal --------------------------------------------------


def test_a_stop_at_any_batch_loses_nothing(old_table) -> None:
    copies = [Copy(OTHER, DAYS[0], f"Action {i}", hours_in=i, url="https://example.test/a") for i in range(40)]
    ids = _store(old_table.database, copies)
    old_table.step("install")
    old_table.step("prepare")
    pages = old_table.step("status")["heap_pages"]
    assert pages > 3

    for _ in range(pages + 1):
        status = old_table.step("copy", pages=1, max_batches=1)
    assert status["copied_through"] == pages
    # Running a finished step again adds nothing.
    assert old_table.step("copy", pages=1)["rows_read"] == 40

    old_table.step("build")
    old_table.step("build")
    old_table.step("verify", pages=2, max_batches=1)
    old_table.step("verify", pages=2)
    old_table.step("swap")

    _assert_matches_the_model(old_table, copies, ids)


def test_a_failing_batch_retries_from_the_ledger(old_table, monkeypatch) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], f"Action {i}", url="https://example.test/a") for i in range(40)])
    old_table.step("install")
    old_table.step("prepare")

    class LostReply(type(old_table.connection)):
        lost = 0

        def run(self, sql: str) -> str:
            out = super().run(sql)
            if "copy_batch" in sql and LostReply.lost < 2:
                LostReply.lost += 1
                raise RuntimeError("the reply never arrived")
            return out

    monkeypatch.setattr(driver.time, "sleep", lambda _: None)

    status = driver.run_step(LostReply(old_table.database.url), "copy", pages=1, say=lambda _: None)

    assert LostReply.lost == 2
    assert status["copied_through"] >= status["heap_pages"]
    assert status["rows_read"] == 40


def test_a_batch_out_of_order_fails(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.step("install")
    old_table.step("prepare")

    with pytest.raises(RuntimeError, match="out of order"):
        old_table.connection.call("select bill_action_cleanup.copy_batch(5, 10)")

    with pytest.raises(RuntimeError, match="out of order"):
        old_table.connection.call("select bill_action_cleanup.copy_batch(0, 0)")

    old_table.connection.call("select bill_action_cleanup.copy_batch(0, 10)")
    with pytest.raises(RuntimeError, match="out of order"):
        old_table.connection.call("select bill_action_cleanup.copy_batch(0, 10)")


def test_the_steps_refuse_to_run_out_of_order(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.step("install")

    for early_step, message in [
        ("copy", "run prepare first"),
        ("verify", "run prepare first"),
        ("build", "the copy reached page"),
        ("swap", "not swapping"),
    ]:
        with pytest.raises(RuntimeError, match=message):
            old_table.step(early_step)
    with pytest.raises(RuntimeError, match="swap has not run"):
        old_table.step("finish")
    with pytest.raises(RuntimeError, match="swap has not run"):
        old_table.step("swap-back")

    old_table.step("prepare")
    with pytest.raises(RuntimeError, match="prepare already ran"):
        old_table.step("prepare")
    with pytest.raises(RuntimeError, match="run build first"):
        old_table.step("verify")


def test_prepare_refuses_a_table_with_its_event_key(old_table) -> None:
    old_table.database.run(
        "create unique index bill_actions_event_key on bills.bill_actions (bill_id, occurred_at, md5(action_text))"
    )
    old_table.step("install")

    with pytest.raises(RuntimeError, match="holds no copies"):
        old_table.step("prepare")


@pytest.mark.parametrize(
    "write",
    [
        "insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint) "
        f"values ('{OTHER}', now(), 'New', 'new')",
        "update bills.bill_actions set source_url = 'https://example.test/changed'",
        "delete from bills.bill_actions",
        "truncate bills.bill_actions",
    ],
)
def test_the_old_table_refuses_writes_from_prepare_until_finish(old_table, write) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.step("install")
    old_table.step("prepare")

    with pytest.raises(PsqlError, match="frozen"):
        old_table.database.run(write)
    with pytest.raises(PsqlError, match="frozen"):
        old_table.database.as_role("service_role", write)


def test_a_bill_delete_fails_loudly_while_the_old_table_stays(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_verify()
    old_table.step("swap")

    with pytest.raises(PsqlError, match="frozen"):
        old_table.database.run(f"delete from bills.bills where id = '{OTHER}'")


# --- Who can read what ---------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
def test_no_api_role_reaches_the_cleanup(old_table, role) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_build()

    for sql in [
        "select * from bill_action_cleanup.state",
        "select * from bill_action_cleanup.bill_actions",
        "select bill_action_cleanup.status()",
        "select bill_action_cleanup.swap()",
        "select bill_action_cleanup.abort()",
        "select bill_action_cleanup.finish()",
        "select * from bill_action_cleanup_old.bill_actions",
    ]:
        with pytest.raises(PsqlError, match="permission denied for schema"):
            old_table.database.as_role(role, sql)


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
def test_the_api_reads_the_same_actions_through_every_step(old_table, role) -> None:
    _store(old_table.database, [
        Copy(OTHER, DAYS[0], "Introduced", hours_in=1),
        Copy(OTHER, DAYS[1], "Referred", hours_in=1),
    ])

    def read() -> str:
        return old_table.database.as_role(
            role,
            "select string_agg(occurred_at || action_text, '|' order by occurred_at) from bills.bill_actions",
        )

    before = read()
    old_table.step("install")
    old_table.step("prepare")
    assert read() == before
    old_table.step("copy")
    old_table.step("build")
    old_table.step("verify")
    assert read() == before
    old_table.step("swap")
    assert read() == before
    old_table.step("swap-back")
    assert read() == before


def test_the_swap_leaves_the_table_as_it_was_plus_the_event_key(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    before = _catalog(old_table.database)

    old_table.through_verify()
    old_table.step("swap")

    after = _catalog(old_table.database)
    event_key = after["indexes"].pop("bill_actions_event_key")
    assert "md5(action_text)" in event_key and "UNIQUE" in event_key
    assert after == before


def test_the_table_after_the_swap_refuses_a_second_copy_of_an_action(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_verify()
    old_table.step("swap")

    with pytest.raises(PsqlError, match="bill_actions_event_key"):
        old_table.database.run(f"""
            insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint)
            values ('{OTHER}', '{DAYS[0].isoformat()}', 'Introduced', 'another hash')
        """)


# --- What stops the swap -------------------------------------------------------


NEW = "bill_action_cleanup.bill_actions"
BREAKS = {
    "a missing grant": (f"revoke select on {NEW} from anon", "grants differ"),
    "an extra grant": (f"grant insert on {NEW} to anon", "grants differ"),
    "a missing policy": (f'drop policy "Public read" on {NEW}', "policies differ"),
    "row-level security off": (f"alter table {NEW} disable row level security", "row-level security"),
    "row-level security forced": (f"alter table {NEW} force row level security", "row-level security"),
    "a missing index": ("drop index bill_action_cleanup.idx_actions_bill_occurred", "indexes missing"),
    "an extra index": (f"create index stray on {NEW} (source_url)", "indexes only on the new table"),
    "a missing primary key": (f"alter table {NEW} drop constraint bill_actions_pkey", "constraints missing"),
    "a missing foreign key": (f"alter table {NEW} drop constraint bill_actions_bill_id_fkey", "constraints missing"),
    "an extra constraint": (f"alter table {NEW} add constraint stray check (action_text <> '')",
                            "constraints only on the new table"),
    "an extra column": (f"alter table {NEW} add column stray text", "columns differ"),
    "a changed default": (f"alter table {NEW} alter column ingested_at drop default", "columns differ"),
    "a lost row": (f"delete from {NEW}", "different number of rows"),
    "a stray fingerprint": (f"update {NEW} set fingerprint = 'bare'", "outside the current schemes"),
    "writes let through to the old table": (
        "alter table bills.bill_actions disable trigger bill_actions_frozen",
        "no longer refuses writes",
    ),
    "rows written while the old table let writes through": (
        "alter table bills.bill_actions disable trigger bill_actions_frozen;"
        "insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint, source_url)"
        f" select '{OTHER}', now(), 'Late ' || i, 'late ' || i, repeat('x', 1500) from generate_series(1, 20) as i;"
        "alter table bills.bill_actions enable trigger bill_actions_frozen",
        "changed size since prepare",
    ),
    "a view on the old table": ("create view bills.stray as select id from bills.bill_actions", "views depend"),
    "a foreign key to the old table": (
        "create table bills.stray (action_id uuid references bills.bill_actions (id))",
        "foreign keys reference",
    ),
    "a missing row found by verify": (
        "update bill_action_cleanup.verified set rows_missing = 1",
        "with no action in the new table",
    ),
    "a verify that read fewer rows": (
        "update bill_action_cleanup.verified set rows_read = 0",
        "read different numbers of rows",
    ),
}


@pytest.mark.parametrize("name", BREAKS)
def test_swap_refuses_a_table_that_does_not_match(old_table, name) -> None:
    statement, message = BREAKS[name]
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_verify()
    assert old_table.step("problems") == []
    old_table.database.run(statement)

    assert any(message in problem for problem in old_table.step("problems"))
    with pytest.raises(RuntimeError, match="not swapping"):
        old_table.step("swap")

    assert old_table.database.run("select to_regclass('bill_action_cleanup_old.bill_actions')") == ""
    assert old_table.database.run("select to_regclass('bill_action_cleanup.bill_actions')") != ""


def test_swap_refuses_while_the_copy_or_verify_stops_short(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], f"Action {i}", url="https://example.test/a") for i in range(40)])
    old_table.step("install")
    old_table.step("prepare")
    old_table.step("copy", pages=1, max_batches=1)
    assert any("copy has not reached" in problem for problem in old_table.step("problems"))
    old_table.step("copy")
    old_table.step("build")
    assert any("verify has not reached" in problem for problem in old_table.step("problems"))


def test_verify_finds_an_action_the_new_table_lost(old_table) -> None:
    _store(old_table.database, [
        Copy(OTHER, DAYS[0], "Introduced"),
        Copy(MARYLAND, STAMPS[0], "Passed"),
        Copy(OTHER, DAYS[1], "Referred"),
    ])
    old_table.through_build()
    old_table.database.run(f"delete from {NEW} where action_text in ('Introduced', 'Passed')")

    status = old_table.step("verify")

    assert status["rows_missing"] == 2


def test_verify_finds_a_maryland_row_dated_after_the_old_one(old_table) -> None:
    _store(old_table.database, [Copy(MARYLAND, STAMPS[0], "Passed")])
    old_table.through_build()
    old_table.database.run(f"update {NEW} set occurred_at = occurred_at + interval '1 day'")

    assert old_table.step("verify")["rows_missing"] == 1


# --- Going back ----------------------------------------------------------------


def _rows_exactly(database: Database) -> str:
    return database.run(
        "select jsonb_agg(to_jsonb(row) order by row.id) from "
        "(select *, ctid::text as place from bills.bill_actions) as row"
    )


def _rebuild_the_unique_index(database: Database) -> None:
    for statement in driver.REBUILD_UNIQUE_INDEX.split(";"):
        statement = "\n".join(
            line for line in statement.splitlines() if not line.startswith("--")
        ).strip()
        if statement:
            database.run(statement)


def test_abort_returns_the_old_table(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced", hours_in=run) for run in range(5)])
    catalog, rows = _catalog(old_table.database), _rows_exactly(old_table.database)
    old_table.through_verify()

    old_table.step("abort")
    _rebuild_the_unique_index(old_table.database)

    assert _catalog(old_table.database) == catalog
    assert _rows_exactly(old_table.database) == rows
    assert old_table.database.run("select to_regclass('bill_action_cleanup.bill_actions')") == ""
    assert old_table.step("status")["prepared"] is False


def test_the_cleanup_can_run_again_after_an_abort(old_table) -> None:
    copies = [Copy(OTHER, DAYS[0], "Introduced", hours_in=run) for run in range(5)]
    ids = _store(old_table.database, copies)
    old_table.through_verify()
    old_table.step("abort")

    old_table.through_verify()
    old_table.step("swap")

    _assert_matches_the_model(old_table, copies, ids)


def test_swap_back_and_abort_return_the_old_table(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced", hours_in=run) for run in range(5)])
    catalog, rows = _catalog(old_table.database), _rows_exactly(old_table.database)
    old_table.through_verify()
    old_table.step("swap")

    old_table.step("swap-back")

    assert _rows_exactly(old_table.database) == rows
    with pytest.raises(PsqlError, match="frozen"):
        old_table.database.run("delete from bills.bill_actions")

    old_table.step("abort")
    _rebuild_the_unique_index(old_table.database)

    assert _catalog(old_table.database) == catalog
    assert _rows_exactly(old_table.database) == rows


def test_abort_refuses_after_the_swap(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_verify()
    old_table.step("swap")

    with pytest.raises(RuntimeError, match="use swap-back"):
        old_table.step("abort")


def test_finish_leaves_only_the_new_table(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced", hours_in=run) for run in range(3)])
    old_table.through_verify()
    old_table.step("swap")
    catalog = _catalog(old_table.database)

    assert old_table.step("finish") == {"rows_now": 1}

    assert _catalog(old_table.database) == catalog
    assert old_table.database.run(
        "select count(*) from pg_namespace where nspname in ('bill_action_cleanup', 'bill_action_cleanup_old')"
    ) == "0"
    # Bills delete again, with their actions.
    old_table.database.run(f"delete from bills.bills where id = '{OTHER}'")
    assert old_table.actions() == []


# --- The Management API --------------------------------------------------------

BREAKS_OFF = "[{"


class _RecordedApi(BaseHTTPRequestHandler):
    """Replies in the shapes the real Management API gave on 6 November 2026."""

    replies: ClassVar[dict[str, list[tuple[int, str]]]] = {}
    tokens: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        sql = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["query"]
        self.tokens.append(self.headers["Authorization"])
        status, reply = self.replies[sql].pop(0)
        body = reply.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body) + (10 if reply == BREAKS_OFF else 0)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def api() -> Iterator[Callable[[dict], driver.ManagementApi]]:
    recorded = ThreadingHTTPServer(("127.0.0.1", 0), _RecordedApi)
    Thread(target=recorded.serve_forever, daemon=True).start()

    def answering(replies: dict) -> driver.ManagementApi:
        _RecordedApi.replies = {sql: list(answers) for sql, answers in replies.items()}
        connection = driver.ManagementApi("a-project", "a-token")
        connection.url = f"http://127.0.0.1:{recorded.server_port}/"
        return connection

    yield answering
    recorded.shutdown()
    recorded.server_close()


def test_the_driver_reads_each_kind_of_reply_the_api_gives(api) -> None:
    connection = api({
        "an object": [(201, '[{"status": {"prepared": true}}]')],
        "a list": [(201, '[{"to_jsonb": []}]')],
        "a string": [(201, '[{"build_next": "bill_actions_pkey"}]')],
        "a null": [(201, '[{"build_next": null}]')],
        "no rows": [(201, "[]")],
    })

    assert connection.call("an object") == {"prepared": True}
    assert connection.call("a list") == []
    assert connection.run("a string") == "bill_actions_pkey"
    assert connection.run("a null") == ""
    assert connection.run("no rows") == ""
    assert set(_RecordedApi.tokens) == {"Bearer a-token"}


def test_build_through_the_api_stops_when_nothing_is_left(api) -> None:
    connection = api({
        "select bill_action_cleanup.build_next()": [
            (201, '[{"build_next": "bill_actions_pkey"}]'),
            (201, '[{"build_next": "statistics"}]'),
            (201, '[{"build_next": null}]'),
        ],
        "select bill_action_cleanup.status()": [(201, '[{"status": {"built": true}}]')],
    })
    said: list[str] = []

    assert driver.run_step(connection, "build", say=said.append) == {"built": True}
    assert said == ["built bill_actions_pkey", "built statistics"]


def test_an_api_failure_raises_what_the_walk_retries(api) -> None:
    connection = api({
        "refused": [(400, '{"message": "Failed to run sql query: ERROR: 3F000: schema does not exist"}')],
        "broken": [(201, BREAKS_OFF)],
    })

    with pytest.raises(RuntimeError, match="400.*schema does not exist"):
        connection.run("refused")
    with pytest.raises(RuntimeError, match="broke off"):
        connection.run("broken")


# --- The migration -------------------------------------------------------------


def test_the_migration_leaves_a_cleaned_table_alone(old_table) -> None:
    _store(old_table.database, [Copy(OTHER, DAYS[0], "Introduced")])
    old_table.through_verify()
    old_table.step("swap")
    catalog = _catalog(old_table.database)

    old_table.database.run_file(MIGRATION)

    assert _catalog(old_table.database) == catalog


def test_the_migration_refuses_a_table_still_holding_its_copies(old_table) -> None:
    old_table.database.run(
        "update pg_class set reltuples = 122000000 where oid = 'bills.bill_actions'::regclass"
    )

    with pytest.raises(PsqlError, match="still holds its old copies"):
        old_table.database.run_file(MIGRATION)


def test_the_migration_adds_the_key_to_an_empty_table(old_table) -> None:
    old_table.database.run_file(MIGRATION)

    assert "bill_actions_event_key" in _catalog(old_table.database)["indexes"]


# --- A real sync after the swap -------------------------------------------------


def test_a_sync_after_the_swap_adds_nothing(
    tmp_path, live_rest, monkeypatch, owner_role,  # noqa: F811 - fixtures
) -> None:
    with monkeypatch.context() as old_code:
        old_code.setattr(supabase_sync, "_sync_actions", _old_sync_actions)
        _ci_run(tmp_path, [_bill(ACTIONS)], "old-first")
        _ci_run(tmp_path, [_bill(ACTIONS)], "old-second")
    assert len(live_rest.actions()) == 2 * len(ACTIONS)
    cleanup = _owned_by_a_plain_role(live_rest.database)
    cleanup.through_verify()
    cleanup.step("swap")
    kept = live_rest.actions()
    assert len(kept) == len(ACTIONS)

    counts = _ci_run(tmp_path, [_bill(ACTIONS)], "after")

    assert counts["bill_actions"] == 0
    assert live_rest.actions() == kept

    fresh = ACTIONS[0].model_copy(update={
        "action_text": "A new action", "occurred_at": datetime(2026, 7, 1, tzinfo=UTC),
    })
    counts = _ci_run(tmp_path, [_bill([*ACTIONS, fresh])], "new-action")

    assert counts["bill_actions"] == 1
    assert len(live_rest.actions()) == len(ACTIONS) + 1


def test_a_maryland_sync_after_the_swap_adds_nothing(
    tmp_path, live_rest, monkeypatch, owner_role,  # noqa: F811 - fixtures
) -> None:
    row = {**MARYLAND_ROW, "PassedByMGA": True}

    def scrape(stamp: str):
        bill = parse_maryland({**row, "StatusCurrentAsOf": stamp}, "2026", 2026)
        assert bill is not None
        return bill

    # Three runs of the old sync, as production holds them.
    with monkeypatch.context() as old_code:
        old_code.setattr(supabase_sync, "_sync_actions", _old_sync_actions)
        for run, stamp in enumerate(
            ["2026-02-04T17:45:08.947", "2026-02-05T09:12:44.103", "2026-02-06T08:01:02.500"]
        ):
            _ci_run(tmp_path, [scrape(stamp)], f"old-{run}", jurisdiction="us-md")
    actions = len(scrape("2026-02-04T17:45:08.947").actions)
    assert len(live_rest.actions()) == 3 * actions
    cleanup = _owned_by_a_plain_role(live_rest.database)
    cleanup.through_verify()
    cleanup.step("swap")
    kept = live_rest.actions()
    assert len(kept) == actions

    counts = _ci_run(tmp_path, [scrape("2026-08-14T09:12:44.103")], "after", jurisdiction="us-md")

    assert counts["bill_actions"] == 0
    assert live_rest.actions() == kept
    passed = next(r for r in kept if r["action_text"] == "Passed by the General Assembly")
    assert datetime.fromisoformat(passed["occurred_at"]) == datetime(2026, 2, 4, 17, 45, 8, 947000, tzinfo=UTC)
