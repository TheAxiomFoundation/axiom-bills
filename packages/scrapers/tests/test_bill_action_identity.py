"""A repeat scrape must add no row to bills.bill_actions.

Each CI refresh starts from an empty SQLite that gives every bill a new random
id. The old fingerprint hashed that id, so the sync's unique key
(bill_id, fingerprint) never matched and every run stored another copy of every
action: 122 million rows for about 1.5 million actions. Maryland added a second
way in: it dated two actions with the time the state wrote its feed.

These properties hold for every input:

- A repeat scrape or sync adds no row and writes no row.
- Every distinct action survives.
- An action the remote table already holds, in any number of old copies, gains
  no row.
- An existing row keeps its id, date, text, fingerprint and ingested_at.
- A fingerprint depends only on the moment and text, however the time is written.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_bills._common import db as bills_db
from axiom_bills._common import supabase_sync
from axiom_bills._common.db import action_fingerprint, is_undated_fingerprint
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillKind,
    Chamber,
    NormalizedStatus,
    ScrapeResult,
    Session,
)
from axiom_bills.jurisdictions.us_de.bill.scrape import parse_feed_item
from axiom_bills.jurisdictions.us_ma.bill.scrape import parse_bill as parse_massachusetts
from axiom_bills.jurisdictions.us_md.bill.scrape import parse_bill as parse_maryland
from axiom_bills.jurisdictions.us_or.bill.scrape import parse_measure

from .test_maryland_scraper import ROW as MARYLAND_ROW

SQLITE_MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
EASTERN = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc


# --- Strategies ------------------------------------------------------------

zones = st.sampled_from([None, UTC, EASTERN, PACIFIC, timezone(timedelta(hours=5, minutes=30))])
moments = st.datetimes(
    min_value=datetime(1990, 1, 1), max_value=datetime(2035, 1, 1), timezones=zones
)
# Postgres text can't hold NUL, and UTF-8 can't hold a lone surrogate.
free_text = st.text(
    st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=40,
)
# A small pool, so generated actions often share text and need telling apart.
texts = st.sampled_from(["Introduced", "Referred", "Passed", "Signed"]) | free_text
bills = st.sampled_from(
    [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
)
chambers = st.sampled_from([None, "lower", "upper"])
statuses = st.sampled_from([None, "introduced", "signed"])
urls = st.sampled_from([None, "https://example.test/a", "https://example.test/b"])


def _local_row(bill, moment, text, is_undated, chamber, status, url) -> dict:
    return {
        "bill_id": bill.replace("-", "") if bill.startswith("1") else bill,
        "occurred_at": moment.isoformat(),
        "chamber": chamber,
        "action_text": text,
        "normalized_status": status,
        "source_url": url,
        "fingerprint": action_fingerprint(moment, text, undated=is_undated),
    }


local_rows = st.lists(
    st.builds(_local_row, bills, moments, texts, st.booleans(), chambers, statuses, urls),
    max_size=12,
)


def _stored_row(bill, moment, text, chamber, status, url, fingerprint, ingested_hours) -> dict:
    """A remote row from before the fix: any bare hash, any number of copies."""
    return {
        "id": str(uuid.uuid4()),
        "bill_id": bill,
        "occurred_at": bills_db.action_instant(moment).isoformat(),
        "chamber": chamber,
        "action_text": text,
        "normalized_status": status,
        "source_url": url,
        "fingerprint": fingerprint,
        "ingested_at": (datetime(2026, 6, 1, tzinfo=UTC) + timedelta(hours=ingested_hours)).isoformat(),
    }


stored_rows = st.lists(
    st.builds(
        _stored_row,
        bills,
        moments,
        texts,
        chambers,
        statuses,
        urls,
        st.text("0123456789abcdef", min_size=64, max_size=64),
        st.integers(0, 2000),
    ),
    max_size=20,
    unique_by=lambda row: (row["bill_id"], row["fingerprint"]),
)


def _apply(remote: list[dict], writes: list[dict]) -> list[dict]:
    """A PostgREST upsert on (bill_id, fingerprint), in plain Python."""
    rows = [dict(row) for row in remote]
    index = {(supabase_sync._bill_key(r["bill_id"]), r["fingerprint"]): r for r in rows}
    for write in writes:
        key = (supabase_sync._bill_key(write["bill_id"]), write["fingerprint"])
        if key in index:
            index[key].update(write)
        else:
            row = {"id": str(uuid.uuid4()), "ingested_at": "2026-11-06T00:00:00+00:00", **write}
            rows.append(row)
            index[key] = row
    return rows


def _action_key(row: dict) -> tuple:
    """How a person would count this row's action."""
    bill = supabase_sync._bill_key(row["bill_id"])
    if is_undated_fingerprint(row["fingerprint"]):
        return bill, row["action_text"]
    return bill, supabase_sync._instant(row["occurred_at"]), row["action_text"]


# --- The fingerprint -------------------------------------------------------


@given(moment=moments, text=texts)
def test_a_fingerprint_ignores_how_the_time_is_written(moment, text) -> None:
    fingerprint = action_fingerprint(moment, text)
    in_utc = bills_db.action_instant(moment)
    assert action_fingerprint(in_utc, text) == fingerprint
    assert action_fingerprint(in_utc.astimezone(EASTERN), text) == fingerprint
    assert action_fingerprint(in_utc.replace(tzinfo=None), text) == fingerprint


@given(moment=moments, text=texts)
def test_a_fingerprint_survives_the_sqlite_round_trip(moment, text) -> None:
    stored = datetime.fromisoformat(moment.isoformat())
    assert action_fingerprint(stored, text) == action_fingerprint(moment, text)


@given(a=moments, b=moments, text_a=texts, text_b=texts)
def test_a_fingerprint_tells_distinct_actions_apart(a, b, text_a, text_b) -> None:
    same_moment = bills_db.action_instant(a) == bills_db.action_instant(b)
    same = action_fingerprint(a, text_a) == action_fingerprint(b, text_b)
    assert same == (same_moment and text_a == text_b)


@given(a=moments, b=moments, text=texts)
def test_an_undated_fingerprint_ignores_the_date(a, b, text) -> None:
    assert action_fingerprint(a, text, undated=True) == action_fingerprint(b, text, undated=True)
    assert is_undated_fingerprint(action_fingerprint(a, text, undated=True))
    assert not is_undated_fingerprint(action_fingerprint(a, text))


@given(moment=moments, text=texts)
def test_undated_and_dated_fingerprints_never_match(moment, text) -> None:
    assert action_fingerprint(moment, text, undated=True) != action_fingerprint(moment, text)


# --- Writing to SQLite -----------------------------------------------------


def _local_actions_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((SQLITE_MIGRATIONS / "001_init.sql").read_text())
    # These tests hold actions without a parent bill.
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


actions = st.lists(
    st.builds(
        BillAction,
        occurred_at=moments,
        action_text=texts,
        undated=st.booleans(),
        source_url=urls,
    ),
    max_size=12,
)


@given(scraped=actions)
def test_writing_a_bill_twice_adds_nothing_and_loses_nothing(scraped) -> None:
    conn = _local_actions_table()
    first = bills_db._insert_actions(conn, "bill", scraped)
    second = bills_db._insert_actions(conn, "bill", scraped)
    stored = conn.execute("SELECT fingerprint FROM bill_actions").fetchall()
    distinct = {
        action_fingerprint(a.occurred_at, a.action_text, undated=a.undated) for a in scraped
    }

    assert second == 0
    assert first == len(stored) == len(distinct)
    assert {row["fingerprint"] for row in stored} == distinct


# --- The sync's plan -------------------------------------------------------


@given(local=local_rows, remote=stored_rows)
def test_a_repeat_sync_writes_nothing(local, remote) -> None:
    after_first = _apply(remote, supabase_sync._action_changes(local, remote))
    assert supabase_sync._action_changes(local, after_first) == []


@given(local=local_rows, remote=stored_rows)
def test_every_distinct_action_survives(local, remote) -> None:
    after = _apply(remote, supabase_sync._action_changes(local, remote))
    stored_events = {
        (supabase_sync._bill_key(r["bill_id"]), supabase_sync._instant(r["occurred_at"]), r["action_text"])
        for r in after
    }
    stored_texts = {(event[0], event[2]) for event in stored_events}
    for row in local:
        bill = supabase_sync._bill_key(row["bill_id"])
        if is_undated_fingerprint(row["fingerprint"]):
            assert (bill, row["action_text"]) in stored_texts
        else:
            assert (bill, supabase_sync._instant(row["occurred_at"]), row["action_text"]) in stored_events


@given(local=local_rows, remote=stored_rows)
def test_an_action_already_stored_gains_no_row(local, remote) -> None:
    held_events = {
        (supabase_sync._bill_key(r["bill_id"]), supabase_sync._instant(r["occurred_at"]), r["action_text"])
        for r in remote
    }
    held_texts = {(event[0], event[2]) for event in held_events}
    dated = {_action_key(row) for row in local if not is_undated_fingerprint(row["fingerprint"])}
    dated_texts = {(key[0], key[2]) for key in dated}
    undated = {_action_key(row) for row in local if is_undated_fingerprint(row["fingerprint"])}
    new = len(dated - held_events) + len(undated - held_texts - dated_texts)

    after = _apply(remote, supabase_sync._action_changes(local, remote))

    assert len(after) == len(remote) + new


@given(local=local_rows, remote=stored_rows)
def test_a_stored_row_keeps_its_identity(local, remote) -> None:
    after = _apply(remote, supabase_sync._action_changes(local, remote))
    for before, now in zip(remote, after):
        for column in ("id", "occurred_at", "action_text", "fingerprint", "ingested_at"):
            assert now[column] == before[column]


@given(local=local_rows, remote=stored_rows, data=st.data())
def test_row_order_changes_nothing(local, remote, data) -> None:
    shuffled = data.draw(st.permutations(remote))

    def key(write: dict) -> tuple:
        return write["bill_id"], write["fingerprint"]

    assert sorted(supabase_sync._action_changes(local, shuffled), key=key) == sorted(
        supabase_sync._action_changes(local, remote), key=key
    )


@given(local=local_rows, remote=stored_rows)
def test_no_upsert_hits_one_row_twice(local, remote) -> None:
    """Postgres refuses ON CONFLICT DO UPDATE on one row twice in a statement."""
    writes = supabase_sync._action_changes(local, remote)
    keys = [(supabase_sync._bill_key(w["bill_id"]), w["fingerprint"]) for w in writes]
    assert len(keys) == len(set(keys))


BILL = "11111111-1111-4111-8111-111111111111"


def _stored(moment: str, text: str = "Passed", fingerprint: str = "f" * 64,
            ingested_at: str = "2026-06-02T00:00:00+00:00", **columns) -> dict:
    return {
        "bill_id": BILL,
        "occurred_at": moment,
        "chamber": None,
        "action_text": text,
        "normalized_status": None,
        "source_url": None,
        "fingerprint": fingerprint,
        "ingested_at": ingested_at,
        **columns,
    }


def _scraped(moment: str, text: str = "Passed", *, undated: bool = False, **columns) -> dict:
    return {
        "bill_id": BILL,
        "occurred_at": moment,
        "chamber": None,
        "action_text": text,
        "normalized_status": None,
        "source_url": None,
        "fingerprint": action_fingerprint(datetime.fromisoformat(moment), text, undated=undated),
        **columns,
    }


def test_a_change_goes_to_the_latest_copy_of_an_old_action() -> None:
    remote = [
        _stored("2026-03-01T00:00:00+00:00", fingerprint="a" * 64,
                ingested_at="2026-06-02T00:00:00+00:00"),
        _stored("2026-03-01T00:00:00+00:00", fingerprint="b" * 64,
                ingested_at="2026-08-13T00:00:00+00:00"),
    ]
    writes = supabase_sync._action_changes(
        [_scraped("2026-03-01T00:00:00", source_url="https://example.test/new")], remote)
    assert [w["fingerprint"] for w in writes] == ["b" * 64]
    assert writes[0]["source_url"] == "https://example.test/new"
    assert "id" not in writes[0] and "ingested_at" not in writes[0]


def test_a_time_in_another_zone_finds_the_stored_row() -> None:
    remote = [_stored("2026-03-01T18:00:00.1+00:00")]
    scraped = _scraped("2026-03-01T13:00:00.100000-05:00")
    assert supabase_sync._action_changes([scraped], remote) == []


def test_an_undated_action_keeps_the_first_date_seen() -> None:
    remote = [
        _stored("2026-06-02T11:25:06.1+00:00", fingerprint="a" * 64),
        _stored("2026-08-13T10:15:09.03+00:00", fingerprint="b" * 64),
    ]
    scraped = _scraped("2026-11-06T09:00:00.5+00:00", undated=True, chamber="lower")
    writes = supabase_sync._action_changes([scraped], remote)
    assert [w["fingerprint"] for w in writes] == ["a" * 64]
    assert writes[0]["occurred_at"] == "2026-06-02T11:25:06.1+00:00"
    assert writes[0]["chamber"] == "lower"


def test_a_new_undated_action_gets_one_row_under_any_later_date() -> None:
    first = [_scraped("2026-06-02T11:25:06.1+00:00", undated=True)]
    remote = _apply([], supabase_sync._action_changes(first, []))
    assert len(remote) == 1
    later = [_scraped("2026-08-13T10:15:09.03+00:00", undated=True)]
    assert supabase_sync._action_changes(later, remote) == []


def test_a_real_date_speaks_for_an_undated_action_with_the_same_text() -> None:
    both = [
        _scraped("2026-03-01T00:00:00+00:00", chamber="lower"),
        _scraped("2026-08-13T10:15:09.03+00:00", undated=True, chamber="upper"),
    ]
    remote = _apply([], supabase_sync._action_changes(both, []))
    assert [row["occurred_at"] for row in remote] == ["2026-03-01T00:00:00+00:00"]
    assert remote[0]["chamber"] == "lower"
    assert supabase_sync._action_changes(both, remote) == []


def test_a_local_database_with_old_fingerprints_collapses() -> None:
    old = _scraped("2026-03-01T00:00:00+00:00", fingerprint="c" * 64)
    new = _scraped("2026-03-01T00:00:00+00:00")
    writes = supabase_sync._action_changes([old, new], [])
    assert [w["fingerprint"] for w in writes] == [new["fingerprint"]]


# --- The reads -------------------------------------------------------------


def test_the_sync_reads_a_few_bills_at_a_time_through_the_unique_index(tmp_path) -> None:
    seen: list[dict] = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> list:
            return []

    class _Client:
        def get(self, path, params, headers):
            seen.append(params)
            return _Resp()

        def post(self, *args, **kwargs):  # pragma: no cover - nothing to write here
            raise AssertionError("the local database holds no action to write")

    conn = sqlite3.connect(tmp_path / "local.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE bill_actions (bill_id TEXT, occurred_at TEXT, chamber TEXT,"
        " action_text TEXT, normalized_status TEXT, source_url TEXT, fingerprint TEXT)"
    )
    bill_ids = [f"{i:032x}" for i in range(45)]
    # An empty plan needs stored rows, so give the reads something that matches.
    stored = {}
    for bill_id in bill_ids:
        moment = "2026-03-01T00:00:00+00:00"
        fingerprint = action_fingerprint(datetime.fromisoformat(moment), "Passed")
        conn.execute(
            "INSERT INTO bill_actions VALUES (?, ?, NULL, 'Passed', NULL, NULL, ?)",
            (bill_id, moment, fingerprint),
        )
        stored[bill_id] = _stored(moment, bill_id=bill_id, fingerprint=fingerprint)

    class _FilledResp(_Resp):
        def __init__(self, rows):
            self._rows = rows

        def json(self):
            return self._rows

    class _FilledClient(_Client):
        def get(self, path, params, headers):
            seen.append(params)
            wanted = params["bill_id"].removeprefix("in.(").removesuffix(")").split(",")
            return _FilledResp([stored[bill_id] for bill_id in wanted])

    assert supabase_sync._sync_actions(_FilledClient(), conn, {}) == 0
    assert len(seen) == 3
    assert all(len(p["bill_id"].split(",")) <= 20 for p in seen)
    assert {p["order"] for p in seen} == {"bill_id.asc,fingerprint.asc"}
    assert "ingested_at" in seen[0]["select"]


# --- The scrapers ----------------------------------------------------------


def _fingerprints(bill: Bill) -> dict[str, str]:
    return {
        a.action_text: action_fingerprint(a.occurred_at, a.action_text, undated=a.undated)
        for a in bill.actions
    }


def test_maryland_actions_keep_their_identity_when_the_feed_moves() -> None:
    row = {**MARYLAND_ROW, "PassedByMGA": True}
    first = parse_maryland({**row, "StatusCurrentAsOf": "2026-02-04T17:45:08.947"},
                           "2026 Regular Session", 2026)
    later = parse_maryland({**row, "StatusCurrentAsOf": "2026-02-05T09:12:44.103"},
                           "2026 Regular Session", 2026)

    assert first is not None and later is not None
    assert first.actions[-1].occurred_at != later.actions[-1].occurred_at
    assert _fingerprints(first) == _fingerprints(later)


def test_maryland_dates_its_milestones_and_not_its_status() -> None:
    bill = parse_maryland({**MARYLAND_ROW, "PassedByMGA": True}, "2026 Regular Session", 2026)
    assert bill is not None
    undated = {a.action_text for a in bill.actions if a.undated}
    assert undated == {"Passed by the General Assembly", "In the House - Hearing 1/20 at 1:00 p.m."}
    assert {"First reading", "Hearing"} <= {a.action_text for a in bill.actions if not a.undated}


def test_delaware_flags_only_an_action_with_no_date() -> None:
    item = {
        "Title": "HB 1",
        "Link": "https://legis.delaware.gov/BillDetail?LegislationId=1",
        "Actions": [
            (NormalizedStatus.INTRODUCED, "Introduced", datetime(2026, 1, 5, tzinfo=EASTERN)),
            (NormalizedStatus.SIGNED, "Signed", None),
        ],
    }
    bill = parse_feed_item(item, "2025-2026")
    assert bill is not None
    assert [(a.action_text, a.undated) for a in bill.actions] == [("Introduced", False), ("Signed", True)]


def test_oregon_flags_a_location_with_no_modified_date() -> None:
    row = {"MeasurePrefix": "HB", "MeasureNumber": 1, "SessionKey": "2026R1",
           "CurrentLocation": "House Chamber"}
    dated = parse_measure({**row, "ModifiedDate": "2026-03-05T16:54:28"}, "2026", [], [], [])
    undated = parse_measure(row, "2026", [], [], [])
    assert dated is not None and undated is not None
    assert not dated.actions[-1].undated
    assert undated.actions[-1].undated


def test_massachusetts_flags_a_filing_with_no_date_at_all() -> None:
    session = Session(name="194th General Court", start_date=date(2025, 1, 1))
    no_start = Session(name="194th General Court")
    detail = {"BillNumber": "H1", "Title": "An Act"}
    dated = parse_massachusetts(detail, [], summary={}, session=session)
    undated = parse_massachusetts(detail, [], summary={}, session=no_start)
    assert dated is not None and undated is not None
    assert not dated.actions[0].undated
    assert undated.actions[0].undated


# --- Whole syncs, against a stand-in for PostgREST -------------------------


def _dashed(value):
    """Postgres spells a uuid with dashes, however it arrived."""
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value):
        return str(uuid.UUID(value))
    return value


@dataclass
class FakeRest:
    """Enough of PostgREST for sync(): in.() filters, Range pages, upserts.

    An upsert sets only the columns in its payload, and a new row takes the
    column defaults for the rest. test_bill_action_postgrest.py checks that
    against PostgREST itself.
    """

    tables: dict[str, list[dict]] = field(default_factory=dict)
    clock: datetime = datetime(2026, 11, 6, tzinfo=UTC)
    posts: dict[str, int] = field(default_factory=dict)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        rows = self.tables.setdefault(table, [])
        if request.method == "GET":
            return self._read(request, rows)
        if request.method == "POST":
            self.posts[table] = self.posts.get(table, 0) + 1
            self._upsert(request, table, rows)
            return httpx.Response(201)
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method}")

    def _read(self, request: httpx.Request, rows: list[dict]) -> httpx.Response:
        found = rows
        for column, value in request.url.params.multi_items():
            if value.startswith("in.("):
                wanted = {_dashed(v) for v in value[4:-1].split(",")}
                found = [row for row in found if row.get(column) in wanted]
        columns = request.url.params["order"].split(",")
        found = sorted(found, key=lambda row: [str(row.get(c.split(".")[0])) for c in columns])
        start, end = (int(part) for part in request.headers["range"].split("-"))
        page = found[start:end + 1]
        selected = request.url.params["select"].split(",")
        return httpx.Response(200, json=[{c: row.get(c) for c in selected} for row in page])

    def _upsert(self, request: httpx.Request, table: str, rows: list[dict]) -> None:
        conflict = request.url.params["on_conflict"].split(",")
        for raw in json.loads(request.content):
            incoming = {column: _dashed(value) for column, value in raw.items()}
            if table == "bill_actions":
                incoming["occurred_at"] = supabase_sync._instant(incoming["occurred_at"]).isoformat()
            match = next(
                (row for row in rows if all(row.get(c) == incoming.get(c) for c in conflict)),
                None,
            )
            if match is not None:
                match.update(incoming)
                continue
            self.clock += timedelta(seconds=1)
            rows.append({"id": str(uuid.uuid4()), "ingested_at": self.clock.isoformat(), **incoming})


@pytest.fixture
def rest(monkeypatch) -> FakeRest:
    fake = FakeRest()
    monkeypatch.setattr(
        supabase_sync,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(fake), base_url="http://rest.test/rest/v1"),
    )
    return fake


def _bill(actions: list[BillAction], number: str = "HB1") -> Bill:
    return Bill(
        jurisdiction="us-zz",
        session_name="2026",
        chamber=Chamber.LOWER,
        number=number,
        title=f"Title of {number}",
        source_url=f"https://example.test/{number}",
        actions=actions,
        versions=[],
        kind=BillKind.SUBSTANTIVE,
    )


def _ci_run(tmp_path: Path, bills_scraped: list[Bill], name: str) -> dict[str, int]:
    """One refresh as CI runs it: an empty SQLite, one scrape, one sync."""
    path = tmp_path / f"{name}.sqlite"
    conn = sqlite3.connect(path)
    for migration in ("001_init.sql", "004_encodings_and_citations.sql"):
        conn.executescript((SQLITE_MIGRATIONS / migration).read_text())
    conn.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us-zz', 'Test state', 'state', 'https://example.test')"
    )
    conn.commit()
    conn.close()
    bills_db.write(
        ScrapeResult(jurisdiction="us-zz", session=Session(name="2026"), bills=bills_scraped),
        db_path=str(path),
    )
    return supabase_sync.sync(str(path))


ACTIONS = [
    BillAction(occurred_at=datetime(2026, 1, 5), chamber=Chamber.LOWER, action_text="Introduced"),
    BillAction(occurred_at=datetime(2026, 1, 20, 13, tzinfo=EASTERN), chamber=Chamber.LOWER,
               action_text="Hearing"),
    BillAction(occurred_at=datetime(2026, 2, 1), action_text="Referred"),
    BillAction(occurred_at=datetime(2026, 2, 8), action_text="Referred"),
]


def _snapshot(rest: FakeRest) -> list[dict]:
    return sorted((dict(row) for row in rest.tables["bill_actions"]), key=lambda r: r["fingerprint"])


def test_a_repeat_ci_run_adds_and_writes_no_action(tmp_path, rest) -> None:
    assert _ci_run(tmp_path, [_bill(ACTIONS)], "first")["bill_actions"] == 4
    before = _snapshot(rest)
    posts_before = rest.posts["bill_actions"]

    counts = _ci_run(tmp_path, [_bill(ACTIONS)], "second")

    assert counts["bill_actions"] == 0
    assert rest.posts["bill_actions"] == posts_before
    assert _snapshot(rest) == before


def test_a_new_action_adds_only_itself(tmp_path, rest) -> None:
    _ci_run(tmp_path, [_bill(ACTIONS)], "first")
    before = _snapshot(rest)
    new = BillAction(occurred_at=datetime(2026, 3, 1), action_text="Passed")

    counts = _ci_run(tmp_path, [_bill([*ACTIONS, new])], "second")

    after = _snapshot(rest)
    assert counts["bill_actions"] == 1
    assert len(after) == len(before) + 1
    assert [row for row in after if row["action_text"] == "Passed"]
    assert [row for row in after if row["action_text"] != "Passed"] == before


def test_a_metadata_fix_updates_the_row_in_place(tmp_path, rest) -> None:
    _ci_run(tmp_path, [_bill(ACTIONS)], "first")
    before = {row["fingerprint"]: row for row in _snapshot(rest)}
    fixed = [ACTIONS[0].model_copy(update={"source_url": "https://example.test/fixed"}), *ACTIONS[1:]]

    counts = _ci_run(tmp_path, [_bill(fixed)], "second")

    after = _snapshot(rest)
    assert counts["bill_actions"] == 1
    assert len(after) == 4
    changed = [row for row in after if row["source_url"] == "https://example.test/fixed"]
    assert len(changed) == 1
    original = before[changed[0]["fingerprint"]]
    assert changed[0]["id"] == original["id"]
    assert changed[0]["ingested_at"] == original["ingested_at"]


def test_a_ci_run_adds_nothing_to_actions_held_in_old_copies(tmp_path, rest) -> None:
    _ci_run(tmp_path, [_bill(ACTIONS)], "first")
    # What 95 runs of the old sync left behind: every action under bare hashes.
    originals = _snapshot(rest)
    for run in range(95):
        for row in originals:
            rest.tables["bill_actions"].append({
                **row,
                "id": str(uuid.uuid4()),
                "fingerprint": uuid.uuid5(uuid.NAMESPACE_OID, f"{run}{row['fingerprint']}").hex * 2,
            })
    before = _snapshot(rest)

    counts = _ci_run(tmp_path, [_bill(ACTIONS)], "after-the-copies")

    assert counts["bill_actions"] == 0
    assert _snapshot(rest) == before


def test_maryland_adds_nothing_when_only_the_feed_time_moves(tmp_path, rest) -> None:
    row = {**MARYLAND_ROW, "PassedByMGA": True}

    def scrape(stamp: str) -> Bill:
        bill = parse_maryland({**row, "StatusCurrentAsOf": stamp}, "2026", 2026)
        assert bill is not None
        return bill.model_copy(update={"jurisdiction": "us-zz"})

    _ci_run(tmp_path, [scrape("2026-02-04T17:45:08.947")], "first")
    before = _snapshot(rest)

    counts = _ci_run(tmp_path, [scrape("2026-02-05T09:12:44.103")], "second")

    assert counts["bill_actions"] == 0
    assert _snapshot(rest) == before
    passed = [r for r in before if r["action_text"] == "Passed by the General Assembly"]
    assert len(passed) == 1
    assert datetime.fromisoformat(passed[0]["occurred_at"]) == datetime(
        2026, 2, 4, 17, 45, 8, 947000, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Tokyo"])
def test_a_maryland_action_keeps_its_identity_on_any_machine(zone, monkeypatch) -> None:
    def fingerprints() -> set[str]:
        bill = parse_maryland(MARYLAND_ROW, "2026", 2026)
        assert bill is not None
        return {
            action_fingerprint(a.occurred_at, a.action_text, undated=a.undated)
            for a in bill.actions
        }

    expected = {
        action_fingerprint(datetime(2026, 1, 14), "First reading"),
        action_fingerprint(datetime(2026, 1, 20, 13), "Hearing"),
    }
    try:
        with monkeypatch.context() as machine:
            machine.setenv("TZ", zone)
            time.tzset()
            found = fingerprints()
    finally:
        time.tzset()

    assert expected <= found


@settings(max_examples=25, deadline=None)
@given(texts_seen=st.lists(st.tuples(moments, texts), max_size=8, unique=True))
def test_two_runs_of_any_scrape_match_one_run(tmp_path_factory, texts_seen) -> None:
    tmp_path = tmp_path_factory.mktemp("runs")
    scraped = [BillAction(occurred_at=moment, action_text=text) for moment, text in texts_seen]
    fake = FakeRest()
    original = supabase_sync._client
    supabase_sync._client = lambda: httpx.Client(
        transport=httpx.MockTransport(fake), base_url="http://rest.test/rest/v1"
    )
    try:
        _ci_run(tmp_path, [_bill(scraped)], "first")
        before = _snapshot(fake) if scraped else []
        _ci_run(tmp_path, [_bill(scraped)], "second")
        after = _snapshot(fake) if scraped else []
    finally:
        supabase_sync._client = original

    distinct = {
        action_fingerprint(a.occurred_at, a.action_text) for a in scraped
    }
    assert after == before
    assert {row["fingerprint"] for row in after} == distinct
