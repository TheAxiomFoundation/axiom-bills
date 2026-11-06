"""Saved refresh state: in local SQLite, and on its way to and from Supabase.

Supabase is never contacted: a fake answers the way PostgREST does. The Postgres
side of the table lives in test_supabase_row_level_security.py.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from click.testing import CliRunner
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_bills import cli
from axiom_bills._common import supabase_sync
from axiom_bills._common.db import (
    read_refresh_state,
    refresh_states,
    write_refresh_state,
)
from axiom_bills._common.models import RefreshState
from axiom_bills._common.supabase_sync import (
    REFRESH_STATE_MIGRATION,
    hydrate_refresh_state,
    push_refresh_state,
)

from .new_york_fakes import MIGRATIONS, make_db

SUPABASE_MIGRATIONS = MIGRATIONS.parents[1] / "supabase" / "migrations"
PRINT_NUMBERS = st.lists(st.from_regex(r"[A-Z][0-9]{1,5}[A-Z]?", fullmatch=True), max_size=30)
STATES = st.builds(
    RefreshState,
    feed_cursor=st.from_regex(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", fullmatch=True),
    pending=PRINT_NUMBERS,
)
SESSIONS = st.sampled_from(["2023-2024 Regular Session", "2025-2026 Regular Session"])
JURISDICTIONS = st.sampled_from(["us-ny", "us-ca"])


@pytest.fixture(scope="module")
def template_db(tmp_path_factory) -> Path:
    """A migrated database. Hypothesis copies it, since building one takes time."""
    return Path(make_db(tmp_path_factory.mktemp("template")))


class _Copies:
    def __init__(self, template: Path, folder: Path) -> None:
        self.template = template
        self.folder = folder
        self.made = 0

    def __call__(self) -> str:
        self.made += 1
        path = self.folder / f"copy-{self.made}.sqlite"
        shutil.copy(self.template, path)
        return str(path)


@pytest.fixture(scope="module")
def fresh_db(template_db, tmp_path_factory) -> _Copies:
    return _Copies(template_db, tmp_path_factory.mktemp("copies"))


# --- Local SQLite -------------------------------------------------------------


def test_a_fresh_database_accepts_new_yorks_state_before_any_bill(fresh_db) -> None:
    # hydrate-refresh-state runs before the scrape on a fresh runner, with foreign
    # keys on, so the seeded jurisdiction row has to be enough.
    db = fresh_db()
    state = RefreshState(feed_cursor="2026-11-06T09:00:00", pending=["S1"])

    write_refresh_state("us-ny", "2025-2026 Regular Session", state, db)

    assert read_refresh_state("us-ny", "2025-2026 Regular Session", db) == state


def test_a_database_with_no_state_reads_none(fresh_db) -> None:
    db = fresh_db()

    assert read_refresh_state("us-ny", "2025-2026 Regular Session", db) is None
    assert refresh_states("us-ny", db) == {}


@settings(deadline=None, max_examples=100)
@given(state=STATES)
def test_state_reads_back_as_written(fresh_db, state) -> None:
    db = fresh_db()

    write_refresh_state("us-ny", "A session", state, db)

    assert read_refresh_state("us-ny", "A session", db) == state


@settings(deadline=None, max_examples=60)
@given(writes=st.lists(st.tuples(JURISDICTIONS, SESSIONS, STATES), max_size=12))
def test_the_last_write_for_a_jurisdiction_and_session_wins(fresh_db, writes) -> None:
    db = fresh_db()
    model: dict[str, dict[str, RefreshState]] = {"us-ny": {}, "us-ca": {}}

    for jurisdiction, session, state in writes:
        write_refresh_state(jurisdiction, session, state, db)
        model[jurisdiction][session] = state

    for jurisdiction, states in model.items():
        assert refresh_states(jurisdiction, db) == states


def test_the_new_york_relabel_moves_senate_prints_and_nothing_else(tmp_path) -> None:
    db = make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO sessions (id, jurisdiction, name) VALUES ('s', 'us-ny', 'S')")
    conn.execute("INSERT INTO sessions (id, jurisdiction, name) VALUES ('c', 'us-ca', 'C')")
    rows = [
        ("us-ny", "s", number, chamber)
        for number, chamber in [
            ("S1", "upper"), ("A1", "lower"), ("J1", "lower"), ("R1", "lower"), ("B1", "lower"),
            ("K1", "lower"), ("C1", "lower"), ("E1", "lower"), ("Junk", "lower"),
            # This one already sits in the Senate, so J2 in the Assembly can't move.
            ("J2", "lower"), ("J2", "upper"),
        ]
    ] + [("us-ca", "c", "J1", "lower")]
    for index, (jurisdiction, session, number, chamber) in enumerate(rows):
        conn.execute(
            "INSERT INTO bills (id, jurisdiction, session_id, chamber, number, source_url) "
            "VALUES (?, ?, ?, ?, ?, 'https://example.test/')",
            (f"b{index}", jurisdiction, session, chamber, number),
        )
    conn.commit()

    relabel = (MIGRATIONS / "063_refresh_state.sql").read_text()
    relabel = relabel[relabel.index("UPDATE OR IGNORE"):]
    conn.executescript(relabel)
    first = conn.execute(
        "SELECT id, jurisdiction, number, chamber FROM bills ORDER BY id"
    ).fetchall()
    conn.executescript(relabel)
    second = conn.execute(
        "SELECT id, jurisdiction, number, chamber FROM bills ORDER BY id"
    ).fetchall()
    conn.close()

    assert first == second
    assert sorted(
        (jurisdiction, number, chamber) for _, jurisdiction, number, chamber in first
    ) == sorted(
        [
            ("us-ny", "S1", "upper"), ("us-ny", "A1", "lower"), ("us-ny", "J1", "upper"),
            ("us-ny", "R1", "upper"), ("us-ny", "B1", "upper"), ("us-ny", "K1", "lower"),
            ("us-ny", "C1", "lower"), ("us-ny", "E1", "lower"), ("us-ny", "Junk", "lower"),
            ("us-ny", "J2", "lower"), ("us-ny", "J2", "upper"), ("us-ca", "J1", "lower"),
        ]
    )


# --- Supabase ----------------------------------------------------------------


class FakeRefreshStateTable:
    """bills.refresh_state, behind the two PostgREST calls the sync makes."""

    def __init__(self, rows: list[dict] | None = None, error: httpx.Response | None = None) -> None:
        self.rows = {(row["jurisdiction"], row["session_name"]): row for row in rows or []}
        self.error = error
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path.endswith("/refresh_state")
        if self.error is not None:
            return self.error
        if request.method == "POST":
            assert parse_qs(urlsplit(str(request.url)).query)["on_conflict"] == [
                "jurisdiction,session_name"
            ]
            for row in json.loads(request.content):
                self.rows[(row["jurisdiction"], row["session_name"])] = row
            return httpx.Response(201)
        assert request.method == "GET"
        wanted = request.url.params["jurisdiction"].removeprefix("eq.")
        columns = request.url.params["select"].split(",")
        start, end = (int(part) for part in request.headers["Range"].split("-"))
        matching = [row for key, row in sorted(self.rows.items()) if key[0] == wanted]
        return httpx.Response(
            200, json=[{c: row[c] for c in columns} for row in matching[start : end + 1]]
        )


def _serve(monkeypatch, table: FakeRefreshStateTable) -> None:
    monkeypatch.setattr(
        supabase_sync,
        "_client",
        lambda: httpx.Client(
            base_url="https://supabase.test/rest/v1", transport=httpx.MockTransport(table)
        ),
    )


def _row(jurisdiction: str = "us-ny", session: str = "2025-2026 Regular Session", **fields) -> dict:
    return {
        "jurisdiction": jurisdiction,
        "session_name": session,
        "feed_cursor": "2026-11-06T09:00:00",
        "pending": ["S1", "A2"],
        **fields,
    }


def test_hydrating_copies_one_jurisdictions_state_down(monkeypatch, fresh_db) -> None:
    db = fresh_db()
    table = FakeRefreshStateTable(
        [
            _row(),
            _row(session="2023-2024 Regular Session", pending=[]),
            _row(jurisdiction="us-ca", pending=["AB1"]),
        ]
    )
    _serve(monkeypatch, table)

    counts = hydrate_refresh_state(db, "us-ny")

    assert counts == {"sessions": 2}
    assert refresh_states("us-ny", db) == {
        "2025-2026 Regular Session": RefreshState(
            feed_cursor="2026-11-06T09:00:00", pending=["S1", "A2"]
        ),
        "2023-2024 Regular Session": RefreshState(feed_cursor="2026-11-06T09:00:00", pending=[]),
    }
    assert refresh_states("us-ca", db) == {}


def test_hydrating_nothing_leaves_a_first_run_to_load_the_session(monkeypatch, fresh_db) -> None:
    db = fresh_db()
    _serve(monkeypatch, FakeRefreshStateTable())

    assert hydrate_refresh_state(db, "us-ny") == {"sessions": 0}
    assert refresh_states("us-ny", db) == {}


@pytest.mark.parametrize(
    "body",
    [
        {"code": "PGRST205", "message": "Could not find the table 'bills.refresh_state'"},
        {"code": "42P01", "message": 'relation "bills.refresh_state" does not exist'},
    ],
)
def test_hydrating_without_the_table_stops_the_run_and_names_the_migration(
    monkeypatch, fresh_db, body
) -> None:
    # The same migration fixes the chamber labels. A run that carried on would
    # insert a second copy of 2,352 New York bills.
    _serve(monkeypatch, FakeRefreshStateTable(error=httpx.Response(404, json=body)))

    with pytest.raises(RuntimeError, match=REFRESH_STATE_MIGRATION):
        hydrate_refresh_state(fresh_db(), "us-ny")


def test_the_migration_a_failed_hydrate_names_exists() -> None:
    assert (SUPABASE_MIGRATIONS / REFRESH_STATE_MIGRATION).is_file()


def test_hydrating_passes_any_other_error_along(monkeypatch, fresh_db) -> None:
    error = httpx.Response(400, json={"code": "22P02", "message": "bad input"})
    _serve(monkeypatch, FakeRefreshStateTable(error=error))

    with pytest.raises(RuntimeError, match="22P02") as caught:
        hydrate_refresh_state(fresh_db(), "us-ny")

    assert REFRESH_STATE_MIGRATION not in str(caught.value)


def test_pushing_sends_every_session_of_one_jurisdiction(monkeypatch, fresh_db) -> None:
    db = fresh_db()
    state = RefreshState(feed_cursor="2026-11-06T09:00:00", pending=["S1"])
    write_refresh_state("us-ny", "2025-2026 Regular Session", state, db)
    write_refresh_state("us-ca", "2025-2026 Regular Session", state, db)
    table = FakeRefreshStateTable()
    _serve(monkeypatch, table)

    assert push_refresh_state(db, "us-ny") == {"sessions": 1}

    assert list(table.rows) == [("us-ny", "2025-2026 Regular Session")]
    row = table.rows[("us-ny", "2025-2026 Regular Session")]
    assert row["feed_cursor"] == "2026-11-06T09:00:00"
    # A JSON array, which PostgREST turns into text[].
    assert row["pending"] == ["S1"]
    assert row["updated_at"].endswith("+00:00")


def test_pushing_with_no_state_stops_rather_than_saving_nothing(monkeypatch, fresh_db) -> None:
    table = FakeRefreshStateTable()
    _serve(monkeypatch, table)

    with pytest.raises(RuntimeError, match="No local refresh state"):
        push_refresh_state(fresh_db(), "us-ny")

    assert table.requests == []


def test_a_failed_push_raises(monkeypatch, fresh_db) -> None:
    db = fresh_db()
    write_refresh_state("us-ny", "A session", RefreshState(feed_cursor="c"), db)
    _serve(monkeypatch, FakeRefreshStateTable(error=httpx.Response(403, json={"code": "42501"})))

    with pytest.raises(RuntimeError, match="42501"):
        push_refresh_state(db, "us-ny")


@settings(deadline=None, max_examples=60)
@given(states=st.dictionaries(SESSIONS, STATES, min_size=1))
def test_a_push_then_a_hydrate_gives_back_the_same_state(fresh_db, states) -> None:
    source = fresh_db()
    target = fresh_db()
    for session, state in states.items():
        write_refresh_state("us-ny", session, state, source)

    with pytest.MonkeyPatch.context() as mp:
        _serve(mp, FakeRefreshStateTable())
        push_refresh_state(source, "us-ny")
        hydrate_refresh_state(target, "us-ny")

    assert refresh_states("us-ny", target) == states


# --- The commands ------------------------------------------------------------


def test_the_commands_use_the_cli_database(monkeypatch, fresh_db) -> None:
    source = fresh_db()
    write_refresh_state(
        "us-ny", "A session", RefreshState(feed_cursor="c", pending=["S1"]), source
    )
    table = FakeRefreshStateTable()
    _serve(monkeypatch, table)

    monkeypatch.setattr(cli, "DEFAULT_DB", source)
    pushed = CliRunner().invoke(cli.main, ["push-refresh-state", "--jurisdiction", "us-ny"])
    assert pushed.exit_code == 0, pushed.output
    assert "sessions 1" in pushed.output

    target = fresh_db()
    monkeypatch.setattr(cli, "DEFAULT_DB", target)
    hydrated = CliRunner().invoke(cli.main, ["hydrate-refresh-state", "--jurisdiction", "us-ny"])
    assert hydrated.exit_code == 0, hydrated.output
    assert refresh_states("us-ny", target) == {
        "A session": RefreshState(feed_cursor="c", pending=["S1"])
    }


@pytest.mark.parametrize("command", ["hydrate-refresh-state", "push-refresh-state"])
def test_the_commands_fail_without_supabase_credentials(monkeypatch, fresh_db, command) -> None:
    db = fresh_db()
    write_refresh_state("us-ny", "A session", RefreshState(feed_cursor="c"), db)
    monkeypatch.setattr(cli, "DEFAULT_DB", db)
    monkeypatch.setattr(supabase_sync, "SUPABASE_URL", "")
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "")

    result = CliRunner().invoke(cli.main, [command, "--jurisdiction", "us-ny"])

    assert result.exit_code == 1
    assert "SUPABASE_URL" in str(result.exception)


def test_a_hydrate_command_that_finds_no_table_exits_1(monkeypatch, fresh_db) -> None:
    monkeypatch.setattr(cli, "DEFAULT_DB", fresh_db())
    missing = httpx.Response(404, json={"code": "PGRST205", "message": "Could not find the table"})
    _serve(monkeypatch, FakeRefreshStateTable(error=missing))

    result = CliRunner().invoke(cli.main, ["hydrate-refresh-state", "--jurisdiction", "us-ny"])

    assert result.exit_code == 1
    assert REFRESH_STATE_MIGRATION in str(result.exception)
