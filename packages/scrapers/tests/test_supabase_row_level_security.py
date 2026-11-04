"""Row-level security on the bills schema, checked in the files and on Postgres.

The bills schema's default privileges grant anon SELECT on every new table, so
a new table without row-level security serves the Data API with no row check.

The file checks read the migration files with regular expressions. They run
everywhere and catch the usual mistakes early, but they make a smoke test: SQL
they can't parse passes them. Hypothesis tests their parsers, and checks them
against Postgres itself when a server is available.

The Postgres checks replay the migrations on a real server and test what each
role can do. They need psql on PATH and a superuser connection to PostgreSQL 15
or later, where security_invoker views arrived:

    AXIOM_BILLS_TEST_POSTGRES_URL=postgresql://postgres@localhost/postgres pytest

Without the URL they skip, except under CI, where they fail. For every table,
view and role, they check that:

- immediately after this migration, anon and authenticated read exactly what
  they read immediately before it, and once every later migration has run,
  exactly what the table owner reads;
- each table has row-level security and one policy, a permissive SELECT for
  anon and authenticated using (true), and no table forces it on its owner;
- neither role holds any privilege but SELECT, and a stray insert, update or
  delete grant still changes no row;
- the service role bypasses row-level security, reads every view, and inserts,
  updates and deletes in every table;
- each view applies its caller's row-level security, not its owner's;
- the migration runs in one transaction under a lock timeout, takes its steps
  in a fixed order, hides no row from anon even run one statement at a time,
  doesn't deadlock with the bill page, and changes nothing when it runs again;
- a bill list filtered to one rare kind reads the new index.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RLS_MIGRATION = "20261102120000_bills_row_level_security.sql"
ADMIN_URL = os.environ.get("AXIOM_BILLS_TEST_POSTGRES_URL")
IN_CI = bool(os.environ.get("CI"))

READ_ROLES = ("anon", "authenticated")
# The order in which this migration reaches the tables. PostgREST turns each
# embed into a LEFT JOIN LATERAL in the order the select names it, and Postgres
# locks the tables in that order: the bill page locks bills, then sessions,
# jurisdictions, bill_actions, bill_versions, bill_texts and bill_citations, and
# the variant list locks rule_variants, then axiom_encodings. Taking the tables
# in the same order keeps the migration from deadlocking with those reads.
TABLE_ORDER = (
    "bills",
    "sessions",
    "jurisdictions",
    "bill_actions",
    "bill_versions",
    "bill_texts",
    "bill_citations",
    "rule_variants",
    "axiom_encodings",
    "encoded_rules",
    "encoded_rule_atoms",
    "encoding_graphs",
    "bill_reconciliations",
    "encode_queue",
)
VIEW_ORDER = ("jurisdiction_summary", "bill_list_summary", "current_rule_patches")
INDEX = "idx_bills_jurisdiction_status_at"
INDEX_DEFINITION = (
    f"CREATE INDEX {INDEX} ON bills.bills USING btree "
    "(jurisdiction, current_status_at DESC NULLS LAST, id)"
)


# --- Reading the migration files ---------------------------------------------

DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _identifier_char(char: str) -> bool:
    return bool(char) and (char.isalnum() or char in "_$")


def _statements(sql: str) -> list[str]:
    """Split SQL at top-level semicolons and drop its comments.

    Semicolons inside strings, quoted identifiers, dollar quotes and comments
    don't split, so a DO block stays one statement.
    """
    statements: list[str] = []
    current: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        char, before = sql[i], sql[i - 1] if i else ""
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end
        elif sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            current.append(" ")
        elif char in "'\"":
            # E'...' strings take backslash escapes; the others double the quote.
            backslash = char == "'" and before in ("e", "E") and not _identifier_char(
                sql[i - 2] if i >= 2 else ""
            )
            end = i + 1
            while end < n:
                if backslash and sql[end] == "\\":
                    end += 2
                elif sql[end] != char:
                    end += 1
                elif sql.startswith(char * 2, end):
                    end += 2
                else:
                    break
            current.append(sql[i : end + 1])
            i = end + 1
        elif char == "$" and not _identifier_char(before) and (tag := DOLLAR_QUOTE.match(sql, i)):
            close = sql.find(tag.group(), tag.end())
            end = n if close < 0 else close + len(tag.group())
            current.append(sql[i:end])
            i = end
        elif char == ";":
            statements.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    statements.append("".join(current).strip())
    return [statement for statement in statements if statement]


def _strip_comments(sql: str) -> str:
    return ";\n".join(_statements(sql))


def _migrations() -> list[tuple[str, str]]:
    return [
        (path.name, _strip_comments(path.read_text(encoding="utf-8")))
        for path in sorted(MIGRATIONS.glob("*.sql"))
    ]


def _identifier(token: str) -> str:
    """The name Postgres stores for an identifier as written."""
    return token[1:-1].replace('""', '"') if token.startswith('"') else token.lower()


IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)'
QUALIFIED = rf"(?:{IDENT}\s*\.\s*)?{IDENT}"
# An unqualified name counts as bills, the first schema on the replay's
# search_path.
NAME = rf"(?:(?P<schema>{IDENT})\s*\.\s*)?(?P<name>{IDENT})"
NAME_PARTS = re.compile(NAME)

CREATE_TABLE = re.compile(
    rf"\bcreate\s+(?:unlogged\s+)?table\s+(?P<if_not_exists>if\s+not\s+exists\s+)?{NAME}", re.I
)
DROP_TABLE = re.compile(
    rf"\bdrop\s+table\s+(?:if\s+exists\s+)?(?P<names>{QUALIFIED}(?:\s*,\s*{QUALIFIED})*)", re.I
)
ROW_SECURITY = re.compile(
    rf"\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{NAME}"
    r"\s+(?P<action>enable|disable)\s+row\s+level\s+security\b",
    re.I,
)
CREATE_POLICY = re.compile(
    rf"\bcreate\s+policy\s+(?P<policy>{IDENT})\s+on\s+{NAME}"
    r"(?:\s+as\s+(?P<kind>permissive|restrictive))?"
    r"(?:\s+for\s+(?P<command>all|select|insert|update|delete))?"
    rf"(?:\s+to\s+(?P<roles>{IDENT}(?:\s*,\s*{IDENT})*))?",
    re.I,
)
DROP_POLICY = re.compile(
    rf"\bdrop\s+policy\s+(?:if\s+exists\s+)?(?P<policy>{IDENT})\s+on\s+{NAME}", re.I
)
CREATE_VIEW = re.compile(
    rf"\bcreate\s+(?:or\s+replace\s+)?(?:(?:temp|temporary)\s+)?(?:recursive\s+)?view\s+{NAME}"
    r"(?:\s*\([^)]*\))?(?:\s+with\s*\((?P<options>[^)]*)\))?\s+as\b",
    re.I,
)
ALTER_VIEW = re.compile(
    rf"\balter\s+(?:view|table)\s+(?:if\s+exists\s+)?{NAME}"
    r"\s+(?P<action>set|reset)\s*\((?P<options>[^)]*)\)",
    re.I,
)
DROP_VIEW = re.compile(
    rf"\bdrop\s+view\s+(?:if\s+exists\s+)?(?P<names>{QUALIFIED}(?:\s*,\s*{QUALIFIED})*)", re.I
)


def _in_bills(match: re.Match[str]) -> bool:
    return match["schema"] is None or _identifier(match["schema"]) == "bills"


def _names_in_bills(text: str) -> list[str]:
    return [
        _identifier(part["name"])
        for part in NAME_PARTS.finditer(text)
        if _in_bills(part)
    ]


def _pg_bool(text: str) -> bool | None:
    """Parse a boolean as PostgreSQL's parse_bool does; None when it would refuse."""
    word = text.lower()
    if not word:
        return None
    for full, value in (("true", True), ("false", False), ("yes", True), ("no", False)):
        if full.startswith(word):
            return value
    return {"on": True, "of": False, "off": False, "1": True, "0": False}.get(word)


def _options(text: str | None) -> dict[str, str | None]:
    """Options as written: each name, with its value or None for a bare name."""
    options: dict[str, str | None] = {}
    for item in (text or "").split(","):
        name, equals, value = item.partition("=")
        if name.strip():
            options[_identifier(name.strip())] = value.strip().strip("'\"") if equals else None
    return options


def _invoker(options: dict[str, str | None]) -> bool:
    if "security_invoker" not in options:
        return False
    value = options["security_invoker"]
    return value is None or _pg_bool(value) is True


@dataclass(frozen=True)
class Policy:
    table: str
    in_bills: bool
    kind: str  # permissive or restrictive
    command: str  # all when the statement names no command
    roles: frozenset[str]  # public when the statement names no role

    @property
    def reads_for_anon_and_authenticated(self) -> bool:
        return (
            self.command == "select"
            and self.kind == "permissive"
            and set(READ_ROLES) <= self.roles
        )


def _policy(match: re.Match[str]) -> Policy:
    roles = match["roles"]
    return Policy(
        table=_identifier(match["name"]),
        in_bills=_in_bills(match),
        kind=(match["kind"] or "permissive").lower(),
        command=(match["command"] or "all").lower(),
        roles=frozenset(_identifier(role.strip()) for role in roles.split(","))
        if roles
        else frozenset({"public"}),
    )


def _policies(sql: str) -> list[Policy]:
    return [_policy(match) for match in CREATE_POLICY.finditer(_strip_comments(sql))]


@dataclass
class FileState:
    tables: dict[str, bool] = field(default_factory=dict)  # row-level security on?
    read_policies: dict[str, set[str]] = field(default_factory=dict)
    views: dict[str, bool] = field(default_factory=dict)  # security_invoker on?


EVENTS = {
    "create table": CREATE_TABLE,
    "drop table": DROP_TABLE,
    "row security": ROW_SECURITY,
    "create policy": CREATE_POLICY,
    "drop policy": DROP_POLICY,
    "create view": CREATE_VIEW,
    "alter view": ALTER_VIEW,
    "drop view": DROP_VIEW,
}


def _replay(migrations: list[tuple[str, str]]) -> FileState:
    """Replay the files' statements in order, as far as the patterns above read them."""
    state = FileState()
    for _, sql in migrations:
        sql = _strip_comments(sql)
        events = sorted(
            ((match.start(), event, match) for event, pattern in EVENTS.items()
             for match in pattern.finditer(sql)),
            key=lambda item: item[0],
        )
        for _, event, match in events:
            if event in ("drop table", "drop view"):
                for name in _names_in_bills(match["names"]):
                    (state.views if event == "drop view" else state.tables).pop(name, None)
                    if event == "drop table":
                        state.read_policies.pop(name, None)
                continue
            if not _in_bills(match):
                continue
            name = _identifier(match["name"])
            if event == "create table":
                if not (match["if_not_exists"] and name in state.tables):
                    state.tables[name] = False
                    state.read_policies[name] = set()
            elif event == "row security" and name in state.tables:
                state.tables[name] = match["action"].lower() == "enable"
            elif event == "create policy" and _policy(match).reads_for_anon_and_authenticated:
                state.read_policies.setdefault(name, set()).add(_identifier(match["policy"]))
            elif event == "drop policy":
                state.read_policies.get(name, set()).discard(_identifier(match["policy"]))
            elif event == "create view":
                state.views[name] = _invoker(_options(match["options"]))
            elif event == "alter view" and name in state.views:
                options = _options(match["options"])
                if "security_invoker" in options:
                    state.views[name] = match["action"].lower() == "set" and _invoker(options)
    return state


def test_file_the_rls_migration_is_present():
    assert RLS_MIGRATION in {name for name, _ in _migrations()}


def test_file_the_lists_match_the_migrations():
    state = _replay([(name, sql) for name, sql in _migrations() if name < RLS_MIGRATION])
    assert len(set(TABLE_ORDER)) == len(TABLE_ORDER)
    assert set(state.tables) == set(TABLE_ORDER)
    assert set(state.views) == set(VIEW_ORDER)


def test_file_every_table_has_row_level_security_and_a_read_policy():
    state = _replay(_migrations())
    assert "bills" in state.tables
    assert [table for table, on in state.tables.items() if not on] == []
    assert [table for table in state.tables if not state.read_policies.get(table)] == []


def test_file_no_migration_adds_a_policy_that_can_write():
    for name, sql in _migrations():
        assert [policy for policy in _policies(sql) if policy.command != "select"] == [], name


def test_file_every_view_ends_up_running_with_its_callers_rights():
    views = _replay(_migrations()).views
    assert set(views) >= set(VIEW_ORDER)
    assert [view for view, invoker in views.items() if not invoker] == []


def test_file_every_view_statement_sets_its_callers_rights():
    """Rerunning an older migration then can't take the setting away."""
    for name, sql in _migrations():
        for match in CREATE_VIEW.finditer(sql):
            assert _invoker(_options(match["options"])), (name, match["name"])


def test_file_a_later_replacement_without_the_option_fails_the_check():
    migrations = [
        *_migrations(),
        ("zzz.sql", "create or replace view bills.bill_list_summary as select 1"),
    ]
    assert _replay(migrations).views["bill_list_summary"] is False
    migrations.append(
        (
            "zzzz.sql",
            "create or replace view bills.bill_list_summary with (security_invoker = on) as select 1",
        )
    )
    assert _replay(migrations).views["bill_list_summary"] is True


# --- Hypothesis: the file parsers against a model and against Postgres ------

CASE = st.sampled_from((str.lower, str.upper, str.title))
GAP = st.sampled_from((" ", "  ", "\n", "\t", "\n    "))


@st.composite
def spelled(draw: st.DrawFn, phrase: str) -> str:
    """SQL keywords in a random case, with random spacing between them."""
    words = [draw(CASE)(word) for word in phrase.split()]
    return "".join(word if i == 0 else draw(GAP) + word for i, word in enumerate(words))


QUOTED_NAME = st.text(alphabet='ab ;"-', min_size=1, max_size=10).map(
    lambda text: '"' + text.replace('"', '""') + '"'
)
POLICY_NAME = st.one_of(st.from_regex(r"p_[a-z0-9_]{0,8}", fullmatch=True), QUOTED_NAME)
PROBE_TABLE = st.sampled_from(
    (
        "bills.policy_probe",
        '"bills"."policy_probe"',
        "BILLS.POLICY_PROBE",
        "bills . policy_probe",
        'bills."policy_probe"',
        "policy_probe",
    )
)
ROLE_LIST = st.sampled_from(
    (
        (),
        ("anon",),
        ("authenticated",),
        ("anon", "authenticated"),
        ("authenticated", "anon"),
        ("public",),
        ('"anon"', "AUTHENTICATED"),
    )
)


@st.composite
def policy_statements(draw: st.DrawFn) -> tuple[str, Policy]:
    """A valid CREATE POLICY in a random spelling, and what it means."""
    command = draw(st.sampled_from((None, "all", "select", "insert", "update", "delete")))
    kind = draw(st.sampled_from((None, "permissive", "restrictive")))
    roles = draw(ROLE_LIST)
    effective = command or "all"
    using = effective != "insert" and draw(st.booleans())
    check = effective in ("all", "insert", "update") and draw(st.booleans())
    parts = [draw(spelled("create policy")), draw(POLICY_NAME), draw(spelled("on")), draw(PROBE_TABLE)]
    if kind:
        parts.append(draw(spelled(f"as {kind}")))
    if command:
        parts.append(draw(spelled(f"for {command}")))
    if roles:
        parts.append(draw(spelled("to")) + " " + ", ".join(roles))
    if using:
        parts.append(draw(spelled("using")) + " (true)")
    if check:
        parts.append(draw(spelled("with check")) + " (true)")
    statement = "".join(part if i == 0 else draw(GAP) + part for i, part in enumerate(parts))
    meaning = Policy(
        table="policy_probe",
        in_bills=True,
        kind=kind or "permissive",
        command=effective,
        roles=frozenset(_identifier(role) for role in roles) or frozenset({"public"}),
    )
    return statement, meaning


TRUE_SPELLINGS = ("t", "tr", "tru", "true", "y", "ye", "yes", "on", "1")
FALSE_SPELLINGS = ("f", "fa", "fal", "fals", "false", "n", "no", "of", "off", "0")


@st.composite
def boolean_values(draw: st.DrawFn) -> tuple[str, bool]:
    value = draw(st.booleans())
    word = draw(CASE)(draw(st.sampled_from(TRUE_SPELLINGS if value else FALSE_SPELLINGS)))
    return (f"'{word}'" if draw(st.booleans()) else word), value


@st.composite
def view_options(draw: st.DrawFn) -> tuple[str, bool]:
    """A view option list that sets security_invoker, and the value it sets."""
    name = draw(CASE)("security_invoker")
    if draw(st.booleans()):
        option, value = name, True
    else:
        spelling, value = draw(boolean_values())
        option = f"{name}{draw(GAP)}={draw(GAP)}{spelling}"
    options = [option]
    if draw(st.booleans()):
        barrier, _ = draw(boolean_values())
        options.insert(draw(st.integers(0, 1)), f"security_barrier = {barrier}")
    return ", ".join(options), value


ALTER_HEADS = ("alter view", "alter view if exists", "alter table")
DROP_HEADS = ("drop view", "drop view if exists")


@st.composite
def view_scripts(draw: st.DrawFn) -> tuple[str, dict[str, bool]]:
    """Statements that create, alter and drop one view, and its final setting."""
    statements: list[str] = []
    exists, invoker = False, False
    for _ in range(draw(st.integers(1, 6))):
        action = draw(st.sampled_from(("create", "set", "reset", "drop") if exists else ("create",)))
        view = "bills.view_probe"
        if action == "create":
            replace = exists or draw(st.booleans())
            head = draw(spelled("create or replace view" if replace else "create view"))
            options, invoker = draw(view_options()) if draw(st.booleans()) else ("", False)
            with_clause = f" {draw(spelled('with'))} ({options})" if options else ""
            statements.append(f"{head} {view}{with_clause} {draw(spelled('as select 1 as one'))}")
            exists = True
        elif action == "set":
            options, invoker = draw(view_options())
            alter = draw(spelled(draw(st.sampled_from(ALTER_HEADS))))
            statements.append(f"{alter} {view} {draw(spelled('set'))} ({options})")
        elif action == "reset":
            names = draw(st.sampled_from(("security_invoker", "security_barrier, security_invoker")))
            statements.append(f"{draw(spelled('alter view'))} {view} {draw(spelled('reset'))} ({names})")
            invoker = False
        else:
            statements.append(f"{draw(spelled(draw(st.sampled_from(DROP_HEADS))))} {view}")
            exists, invoker = False, False
    return ";\n".join(statements) + ";\n", ({"view_probe": invoker} if exists else {})


FRAGMENT = st.one_of(
    st.from_regex(r"[a-z_]{1,8}", fullmatch=True),
    st.text(alphabet="ab;'$\" -", max_size=8).map(lambda text: "'" + text.replace("'", "''") + "'"),
    st.text(alphabet="ab;'$\" -", min_size=1, max_size=8).map(
        lambda text: '"' + text.replace('"', '""') + '"'
    ),
    st.text(alphabet="ab;'\" -", max_size=8).map(lambda text: f"$${text}$$"),
    st.text(alphabet="ab;'\" -", max_size=8).map(lambda text: f"$body${text}$body$"),
    st.text(alphabet="ab;'\" -", max_size=8).map(lambda text: "E'" + text.replace("'", "\\'") + "'"),
)
COMMENT = st.sampled_from(("", "-- a; 'b\n", "/* a; 'b */", "/* a /* b; */ c; */"))


@settings(deadline=None)
@given(
    statements=st.lists(
        st.lists(FRAGMENT, min_size=1, max_size=5).map(" ".join), min_size=1, max_size=5
    ),
    data=st.data(),
)
def test_file_parser_splits_only_at_top_level_semicolons(statements, data):
    script = "".join(f"{statement};{data.draw(COMMENT)}\n" for statement in statements)
    assert _statements(script) == [statement.strip() for statement in statements]


@settings(deadline=None)
@given(case=policy_statements())
def test_file_parser_reads_every_policy_spelling(case):
    statement, meaning = case
    assert _policies(statement) == [meaning]


@settings(deadline=None)
@given(case=view_scripts())
def test_file_parser_replays_view_options_like_the_model(case):
    script, final = case
    assert _replay([("probe.sql", script)]).views == final


# --- Running SQL on Postgres ------------------------------------------------


class PsqlError(RuntimeError):
    """psql exited non-zero. The message carries the SQLSTATE."""


PSQL_FLAGS = ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose"]


@dataclass(frozen=True)
class Database:
    url: str
    name: str = ""

    def run(self, sql: str, timeout: float = 300) -> str:
        done = subprocess.run(
            ["psql", self.url, "-At", *PSQL_FLAGS],
            input=sql,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if done.returncode != 0:
            raise PsqlError(done.stderr)
        return done.stdout.strip()

    def run_file(self, path: Path, timeout: float = 300) -> str:
        return self.run(path.read_text(encoding="utf-8"), timeout=timeout)

    def as_role(self, role: str, sql: str, setup: str = "") -> str:
        """Run the statements as a role, then roll everything back."""
        return self.run(f"begin;\n{setup};\nset local role {role};\n{sql};\nrollback;")

    def names(self, kinds: str) -> list[str]:
        relkinds = ", ".join(f"'{kind}'" for kind in kinds)
        return self.run(
            "select relname from pg_class where relnamespace = 'bills'::regnamespace "
            f"and relkind in ({relkinds}) order by relname"
        ).split()

    def tables(self) -> list[str]:
        return self.names("rp")

    def views(self) -> list[str]:
        return self.names("vm")

    def read_everything(self, role: str | None = None) -> dict[str, list]:
        """Every row of every table and view, as a role or else as the owner."""
        reads = " union all ".join(
            f"select '{relation}', (select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text), "
            f"'[]') from bills.{relation} as t)"
            for relation in self.names("rpvmf")
        )
        sql = f"select jsonb_object_agg(relation, rows) from ({reads}) as reads(relation, rows)"
        return json.loads(self.as_role(role, sql) if role else self.run(sql))

    def column_to_update(self, table: str) -> str:
        return self.run(
            "select attname from pg_attribute "
            f"where attrelid = 'bills.{table}'::regclass and attnum > 0 and not attisdropped "
            "and attidentity = '' and attgenerated = '' order by attnum limit 1"
        )


def _database_url(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@dataclass
class Server:
    admin: Database
    version: int
    version_text: str
    databases: list[str] = field(default_factory=list)

    def create_database(self, template: Database | None = None) -> Database:
        name = f"axiom_bills_rls_{uuid.uuid4().hex[:12]}"
        self.databases.append(name)
        self.admin.run(f"create database {name}" + (f" template {template.name}" if template else ""))
        # Studio's editor resolved the coverage migrations' unqualified names.
        self.admin.run(f"alter database {name} set search_path = bills, public")
        return Database(_database_url(self.admin.url, name), name)

    def drop_database(self, database: Database) -> None:
        self.admin.run(f"drop database if exists {database.name} with (force)")
        self.databases.remove(database.name)


ROLES = {
    "anon": "nologin noinherit",
    "authenticated": "nologin noinherit",
    "service_role": "nologin noinherit bypassrls",
}


@pytest.fixture(scope="session")
def server() -> Iterator[Server]:
    if not ADMIN_URL:
        if IN_CI:
            pytest.fail(
                "CI is set, but AXIOM_BILLS_TEST_POSTGRES_URL isn't, so the Postgres checks can't run"
            )
        pytest.skip("AXIOM_BILLS_TEST_POSTGRES_URL is not set")
    if shutil.which("psql") is None:
        pytest.fail("The Postgres checks need psql on PATH")
    admin = Database(ADMIN_URL)
    server = Server(admin, int(admin.run("show server_version_num")), admin.run("show server_version"))
    created_roles: list[str] = []
    try:
        for role, options in ROLES.items():
            if admin.run(f"select count(*) from pg_roles where rolname = '{role}'") == "0":
                admin.run(f"create role {role} {options}")
                created_roles.append(role)
        yield server
    finally:
        for name in reversed(server.databases):
            admin.run(f"drop database if exists {name} with (force)")
        for role in reversed(created_roles):
            admin.run(f"drop role if exists {role}")


@pytest.fixture(scope="session")
def replayable(server: Server) -> Server:
    if server.version < 150000:
        pytest.fail(
            "The migrations need PostgreSQL 15 or later, where security_invoker views "
            f"arrived; this server runs {server.version_text}"
        )
    return server


@pytest.fixture
def copy_of(replayable: Server) -> Iterator[Callable[[Database], Database]]:
    """Make throwaway copies of a database; each goes when the test ends."""
    made: list[Database] = []

    def make(template: Database) -> Database:
        made.append(replayable.create_database(template=template))
        return made[-1]

    yield make
    for database in made:
        replayable.drop_database(database)


SESSION_ID = "00000000-0000-4000-8000-000000000001"
BILL_ID = "00000000-0000-4000-8000-000000000002"
ENCODING_ID = "00000000-0000-4000-8000-000000000003"
RULE_ID = "00000000-0000-4000-8000-000000000004"
SEED_ROWS = f"""
insert into bills.jurisdictions (code, name, level, source_url)
  values ('zz', 'Test state', 'state', 'https://example.test/');
insert into bills.sessions (id, jurisdiction, name)
  values ('{SESSION_ID}', 'zz', 'Test session');
insert into bills.bills (id, jurisdiction, session_id, chamber, number, source_url, title)
  values ('{BILL_ID}', 'zz', '{SESSION_ID}', 'lower', 'HB 1', 'https://example.test/hb1', 'Test bill');
insert into bills.bill_actions (bill_id, occurred_at, action_text, fingerprint)
  values ('{BILL_ID}', '2026-01-01T00:00:00Z', 'Introduced', 'action');
insert into bills.bill_versions (bill_id, label, source_url, format)
  values ('{BILL_ID}', 'Introduced', 'https://example.test/hb1.html', 'html');
insert into bills.bill_texts (bill_id, version_label, source_url, format, text, text_sha256)
  values ('{BILL_ID}', 'Introduced', 'https://example.test/hb1.html', 'html', 'Text', 'sha');
insert into bills.bill_citations (bill_id, raw, citation, source)
  values ('{BILL_ID}', '26 USC 1', '26 USC 1', 'text');
insert into bills.axiom_encodings (id, jurisdiction, repo, kind, citation, file_path)
  values ('{ENCODING_ID}', 'zz', 'rulespec-zz', 'statute', '26 USC 1', 'rules/one.yaml');
insert into bills.encoded_rules (id, encoding_id, rule_name, rule_source)
  values ('{RULE_ID}', '{ENCODING_ID}', 'rule', 'source');
insert into bills.encoded_rule_atoms (rule_id, text) values ('{RULE_ID}', 'atom');
insert into bills.rule_variants (bill_id, encoding_id, file_path, tier, patched_yaml)
  values ('{BILL_ID}', '{ENCODING_ID}', 'rules/one.yaml', 'substitution', 'patched: true');
insert into bills.encoding_graphs (repo, graph) values ('rulespec-zz', '{{}}');
insert into bills.bill_reconciliations (bill_id, section_citation, payload, fingerprint)
  values ('{BILL_ID}', '26 USC 1', '{{}}', 'reconciliation');
insert into bills.encode_queue (bill_id, citation, reason)
  values ('{BILL_ID}', '26 USC 1', 'needs_new_encoding');
"""
# One row for each table a migration after this one creates. The replay seeds
# them after the last migration, and test_each_role_reads_what_the_owner_reads
# fails while any table or view has no row.
LATER_SEED_ROWS = ""


def _files(before_rls: bool) -> list[Path]:
    return [
        path
        for path in sorted(MIGRATIONS.glob("*.sql"))
        if (path.name < RLS_MIGRATION) == before_rls and path.name != RLS_MIGRATION
    ]


@pytest.fixture(scope="session")
def pre(replayable: Server) -> Database:
    """The bills schema just before this migration, with a row in every table."""
    database = replayable.create_database()
    for path in _files(before_rls=True):
        database.run_file(path)
    # Databases that ran the view migrations before those set security_invoker
    # hold the views without it, so start there: this migration must set it.
    database.run(
        "\n".join(f"alter view bills.{view} reset (security_invoker);" for view in database.views())
    )
    database.run(SEED_ROWS)
    return database


@dataclass(frozen=True)
class Replay:
    database: Database
    reads_before: dict[str, dict[str, list]]
    reads_after: dict[str, dict[str, list]]


@pytest.fixture(scope="session")
def replay(replayable: Server, pre: Database) -> Replay:
    """This migration and every later one, with reads just before and after this one."""
    database = replayable.create_database(template=pre)
    reads_before = {role: database.read_everything(role) for role in READ_ROLES}
    database.run_file(MIGRATIONS / RLS_MIGRATION)
    reads_after = {role: database.read_everything(role) for role in READ_ROLES}
    for path in _files(before_rls=False):
        database.run_file(path)
    if LATER_SEED_ROWS.strip():
        database.run(LATER_SEED_ROWS)
    return Replay(database, reads_before, reads_after)


def test_the_catalog_matches_the_file_parsers(replay, pre):
    state = _replay(_migrations())
    assert set(replay.database.tables()) == set(state.tables)
    assert set(replay.database.views()) == set(state.views)
    assert set(pre.tables()) == set(TABLE_ORDER)
    assert set(pre.views()) == set(VIEW_ORDER)


@pytest.mark.parametrize("role", READ_ROLES)
def test_each_role_reads_what_it_read_before(replay, role):
    before = replay.reads_before[role]
    assert set(before) == set(TABLE_ORDER) | set(VIEW_ORDER)
    # Without a row in every relation, the comparison below could pass on an
    # empty read.
    assert [relation for relation, rows in before.items() if not rows] == []
    assert replay.reads_after[role] == before


@pytest.mark.parametrize("role", READ_ROLES)
def test_each_role_reads_what_the_owner_reads(replay, role):
    owner = replay.database.read_everything()
    assert [relation for relation, rows in owner.items() if not rows] == [], (
        "every table and view needs a row; add one to LATER_SEED_ROWS"
    )
    assert replay.database.read_everything(role) == owner


@pytest.mark.parametrize("role", READ_ROLES)
def test_a_read_after_each_statement_matches_the_read_before(copy_of, pre, role):
    """Even run one statement at a time, the migration hides no row from anon."""
    database = copy_of(pre)
    before = database.read_everything(role)
    assert [relation for relation, rows in before.items() if not rows] == []
    statements = [
        statement
        for statement in _statements((MIGRATIONS / RLS_MIGRATION).read_text(encoding="utf-8"))
        if not re.match(r"(begin|commit|set\s+local)\b", statement, re.I)
    ]
    assert len(statements) > len(TABLE_ORDER) * 2
    for statement in statements:
        database.run(statement)
        assert database.read_everything(role) == before, statement
    assert database.run(
        "select count(*) from pg_class where relnamespace = 'bills'::regnamespace "
        "and relkind in ('r', 'p') and not relrowsecurity"
    ) == "0"


def test_each_table_has_row_level_security_and_one_read_policy(replay):
    database = replay.database
    tables = json.loads(
        database.run(
            "select jsonb_object_agg(relname, jsonb_build_object("
            "'rls', relrowsecurity, 'force', relforcerowsecurity)) "
            "from pg_class where relnamespace = 'bills'::regnamespace and relkind in ('r', 'p')"
        )
    )
    assert sorted(tables) == sorted(set(TABLE_ORDER) | set(_replay(_migrations()).tables))
    assert [table for table, flags in tables.items() if not flags["rls"]] == []
    # The owner keeps full access: no table forces row-level security on it.
    assert [table for table, flags in tables.items() if flags["force"]] == []
    policies = json.loads(
        database.run(
            "select jsonb_agg(jsonb_build_object('table', tablename, 'name', policyname, "
            "'kind', permissive, 'roles', roles, 'cmd', cmd, 'using', qual, 'check', with_check)) "
            "from pg_policies where schemaname = 'bills'"
        )
    )
    assert sorted(policy["table"] for policy in policies) == sorted(tables)
    for policy in policies:
        assert policy["name"] == "Public read"
        assert policy["kind"] == "PERMISSIVE"
        assert sorted(policy["roles"]) == sorted(READ_ROLES)
        assert policy["cmd"] == "SELECT"
        assert policy["using"] == "true"
        assert policy["check"] is None


def test_only_the_service_role_bypasses_row_level_security(replay):
    roles = replay.database.run(
        "select rolname, rolbypassrls or rolsuper from pg_roles "
        "where rolname in ('anon', 'authenticated', 'service_role') order by rolname"
    )
    assert roles.splitlines() == ["anon|f", "authenticated|f", "service_role|t"]


TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")


def _sql_array(words) -> str:
    return "array[" + ", ".join(f"'{word}'" for word in words) + "]"


@pytest.mark.parametrize("role", READ_ROLES)
def test_a_role_holds_no_privilege_but_select(replay, role):
    """Row-level security doesn't cover TRUNCATE, REFERENCES or TRIGGER, so no grant may."""
    database = replay.database
    privileges = list(TABLE_PRIVILEGES)
    if int(database.run("show server_version_num")) >= 170000:
        privileges.append("MAINTAIN")
    kinds = dict(
        line.split("|")
        for line in database.run(
            "select relname, relkind from pg_class where relnamespace = 'bills'::regnamespace "
            "and relkind in ('r', 'p', 'v', 'm', 'f', 'S')"
        ).splitlines()
    )
    assert set(kinds) >= set(TABLE_ORDER) | set(VIEW_ORDER)
    held = [
        line.split("|")
        for line in database.run(
            "select c.relname, c.relkind, p.privilege, case when c.relkind = 'S' "
            f"then has_sequence_privilege('{role}', c.oid, p.privilege) "
            f"else has_table_privilege('{role}', c.oid, p.privilege) end "
            "from pg_class c cross join lateral unnest(case when c.relkind = 'S' "
            f"then {_sql_array(SEQUENCE_PRIVILEGES)} else {_sql_array(privileges)} end) as p(privilege) "
            "where c.relnamespace = 'bills'::regnamespace "
            "and c.relkind in ('r', 'p', 'v', 'm', 'f', 'S')"
        ).splitlines()
    ]
    # Every relation, every privilege type.
    assert sorted((relation, privilege) for relation, _, privilege, _ in held) == sorted(
        (relation, privilege)
        for relation, kind in kinds.items()
        for privilege in (SEQUENCE_PRIVILEGES if kind == "S" else privileges)
    )
    allowed = [
        (relation, privilege)
        for relation, kind, privilege, has in held
        if has != ("t" if privilege == "SELECT" and kind != "S" else "f")
    ]
    assert allowed == []
    columns = database.run(
        "select c.relname, a.attname, p.privilege from pg_class c "
        "join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped "
        "cross join unnest(array['INSERT', 'UPDATE', 'REFERENCES']) as p(privilege) "
        "where c.relnamespace = 'bills'::regnamespace and c.relkind in ('r', 'p', 'v', 'm', 'f') "
        f"and has_column_privilege('{role}', c.oid, a.attnum, p.privilege)"
    )
    assert columns == ""


def _count_changed(statement: str) -> str:
    return f"with changed as ({statement} returning 1) select count(*) from changed"


@pytest.mark.parametrize("role", READ_ROLES)
def test_a_stray_write_grant_still_changes_nothing(replay, role):
    database = replay.database
    tables = database.tables()
    assert tables
    for table in tables:
        column = database.column_to_update(table)
        stray_grant = f"grant insert, update, delete on bills.{table} to {role}"
        changed = database.as_role(
            role,
            f"{_count_changed(f'update bills.{table} set {column} = {column}')};\n"
            f"{_count_changed(f'delete from bills.{table}')}",
            setup=stray_grant,
        )
        assert changed.splitlines() == ["0", "0"], table
        # Postgres checks row-level security before constraints, so this reports
        # the policy even though the row breaks NOT NULL too.
        with pytest.raises(PsqlError, match="42501: new row violates row-level security"):
            database.as_role(role, f"insert into bills.{table} default values", setup=stray_grant)


def test_the_service_role_updates_every_table(replay):
    database = replay.database
    tables = database.tables()
    script = ";\n".join(
        _count_changed(f"update bills.{table} set {column} = {column}")
        for table in tables
        for column in [database.column_to_update(table)]
    )
    counts = database.as_role("service_role", script).splitlines()
    assert len(counts) == len(tables)
    assert [table for table, count in zip(tables, counts) if int(count) == 0] == []


def _children_first(database: Database) -> list[str]:
    """Every table, each after every table whose foreign keys point at it."""
    referenced_by: dict[str, set[str]] = {table: set() for table in database.tables()}
    for line in database.run(
        "select child.relname, parent.relname from pg_constraint k "
        "join pg_class child on child.oid = k.conrelid "
        "join pg_class parent on parent.oid = k.confrelid "
        "where k.contype = 'f' and k.connamespace = 'bills'::regnamespace"
    ).splitlines():
        child, parent = line.split("|")
        if child != parent:
            referenced_by[parent].add(child)
    order: list[str] = []
    remaining = set(referenced_by)
    while remaining:
        ready = sorted(table for table in remaining if not referenced_by[table] & remaining)
        assert ready, f"foreign keys form a cycle among {sorted(remaining)}"
        order += ready
        remaining -= set(ready)
    return order


def test_the_service_role_reads_every_view_and_empties_and_refills_every_table(replay):
    database = replay.database
    views, tables = database.views(), _children_first(database)
    script = "\n".join(
        [f"select 'read', '{view}', count(*) from bills.{view};" for view in views]
        + [
            f"select 'had', '{table}', count(*) from bills.{table};\n"
            f"with gone as (delete from bills.{table} returning 1) "
            f"select 'deleted', '{table}', count(*) from gone;\n"
            f"select 'left', '{table}', count(*) from bills.{table};"
            for table in tables
        ]
        + [SEED_ROWS, LATER_SEED_ROWS]
        + [f"select 'refilled', '{table}', count(*) from bills.{table};" for table in tables]
    )
    counts: dict[str, dict[str, int]] = {}
    for line in database.as_role("service_role", script).splitlines():
        step, relation, count = line.split("|")
        counts.setdefault(step, {})[relation] = int(count)
    assert sorted(counts["read"]) == sorted(views)
    assert [view for view, count in counts["read"].items() if count == 0] == []
    for table in tables:
        # Children go first, so no cascade empties a table before its own delete.
        assert counts["deleted"][table] == counts["had"][table] > 0, table
        assert counts["left"][table] == 0, table
        assert counts["refilled"][table] > 0, table


def test_the_service_role_upserts_as_the_sync_does(replay):
    renamed = replay.database.as_role(
        "service_role",
        "insert into bills.jurisdictions (code, name, level, source_url) "
        "values ('zz', 'Renamed', 'state', 'https://example.test/') "
        "on conflict (code) do update set name = excluded.name returning name",
    )
    assert renamed == "Renamed"


DROP_EVERY_POLICY = """
do $$ declare policy record; begin
  for policy in select tablename, policyname from pg_policies where schemaname = 'bills' loop
    execute format('drop policy %I on bills.%I', policy.policyname, policy.tablename);
  end loop;
end $$
"""


@pytest.mark.parametrize("role", READ_ROLES)
def test_each_view_applies_its_callers_row_level_security(replay, role):
    database = replay.database
    views = database.views()
    assert set(views) == set(VIEW_ORDER) | set(_replay(_migrations()).views)
    settings_ = database.run(
        "select relname, coalesce((select option_value::boolean from pg_options_to_table(reloptions) "
        "where option_name = 'security_invoker'), false) from pg_class "
        "where relnamespace = 'bills'::regnamespace and relkind in ('v', 'm') order by relname"
    )
    assert settings_.splitlines() == [f"{view}|t" for view in views]
    for view in views:
        count = f"select count(*) from bills.{view}"
        assert int(database.as_role(role, count)) > 0, view
        # With no policy left, the caller's row-level security hides every row;
        # an owner's-rights view would still return them.
        assert database.as_role(role, count, setup=DROP_EVERY_POLICY) == "0", view


def test_the_new_index_exists(replay):
    database = replay.database
    definition = database.run(
        f"set search_path = pg_catalog; select pg_get_indexdef('bills.{INDEX}'::regclass)"
    )
    assert definition == INDEX_DEFINITION
    assert database.run(
        f"select indisvalid and indisready from pg_index where indexrelid = 'bills.{INDEX}'::regclass"
    ) == "t"


# Two jurisdictions of 12,000 bills each. ANALYZE reads every row of a table
# this small, so the planner sees the same statistics on every run.
LISTING_ROWS = """
insert into bills.jurisdictions (code, name, level, source_url)
  values ('zz1', 'One', 'state', 'https://example.test/'),
         ('zz2', 'Two', 'state', 'https://example.test/');
insert into bills.sessions (id, jurisdiction, name)
  values ('00000000-0000-4000-8000-0000000000a1', 'zz1', 'Session'),
         ('00000000-0000-4000-8000-0000000000a2', 'zz2', 'Session');
insert into bills.bills (jurisdiction, session_id, chamber, number, source_url, kind, current_status_at)
select case when g % 2 = 0 then 'zz1' else 'zz2' end,
       case when g % 2 = 0 then '00000000-0000-4000-8000-0000000000a1'::uuid
            else '00000000-0000-4000-8000-0000000000a2'::uuid end,
       'lower', 'HB ' || g, 'https://example.test/' || g,
       (case when g % 50 = 0 then 'ceremonial' when g % 97 = 0 then 'appropriations'
             else 'substantive' end)::bills.bill_kind,
       timestamptz '2026-01-01' + ((g * 7919) % 24000) * interval '1 minute'
from generate_series(1, 24000) as g;
"""
# The web app's bill list, filtered to a kind no bill has.
SINGLE_KIND_LIST = """
select b.id, s.name from bills.bills b
left join bills.sessions s on s.id = b.session_id
where b.jurisdiction = 'zz1' and b.kind = any('{placeholder}'::bills.bill_kind[])
order by b.current_status_at desc nulls last, b.id
limit 500
"""


def _index_names(plan: object) -> set[str]:
    if isinstance(plan, dict):
        found = {plan["Index Name"]} if "Index Name" in plan else set()
        return found.union(*(_index_names(value) for value in plan.values()))
    if isinstance(plan, list):
        return set().union(*(_index_names(item) for item in plan))
    return set()


def test_a_single_kind_list_reads_the_new_index(copy_of, pre):
    database = copy_of(pre)
    database.run(LISTING_ROWS)
    database.run_file(MIGRATIONS / RLS_MIGRATION)
    database.run("analyze")
    explain = f"explain (format json, costs off) {SINGLE_KIND_LIST}"
    indexes = _index_names(json.loads(database.as_role("anon", explain)))
    assert INDEX in indexes and "idx_bills_status_at" not in indexes
    # Without the new index, anon's plan walks idx_bills_status_at across both
    # jurisdictions. Under row-level security, the planner compares a value with
    # kind's most common values only through a leakproof operator, and enum
    # equality isn't leakproof, so it treats every kind as equally common.
    drop = f"drop index bills.{INDEX}"
    without = json.loads(database.as_role("anon", explain, setup=drop))
    assert "idx_bills_status_at" in _index_names(without)
    # Row-level security doesn't apply to the owner, so its plan uses kind's
    # most common values and idx_bills_kind.
    owner = database.run(f"begin; {drop}; {explain}; rollback;")
    assert "idx_bills_kind" in _index_names(json.loads(owner))


LOG_DDL = """
create table public.ddl_log (
  n serial primary key, tag text, identity text, xact text, lock_timeout text, statement_timeout text
);
create function public.log_ddl() returns event_trigger language plpgsql as $$
declare command record;
begin
  for command in select * from pg_event_trigger_ddl_commands() loop
    insert into public.ddl_log (tag, identity, xact, lock_timeout, statement_timeout)
    values (command.command_tag, command.object_identity, pg_current_xact_id()::text,
            (select setting from pg_settings where name = 'lock_timeout'),
            (select setting from pg_settings where name = 'statement_timeout'));
  end loop;
end $$;
create event trigger log_ddl on ddl_command_end execute function public.log_ddl();
"""


def _ddl_log(database: Database) -> list[list[str]]:
    rows = database.run(
        "select tag, identity, xact, lock_timeout, statement_timeout from public.ddl_log order by n"
    )
    return [line.split("|") for line in rows.splitlines()]


def test_the_migration_takes_its_steps_in_one_transaction_in_order(copy_of, pre):
    database = copy_of(pre)
    database.run(LOG_DDL)
    database.run_file(MIGRATIONS / RLS_MIGRATION)
    log = _ddl_log(database)
    assert len({xact for _, _, xact, _, _ in log}) == 1
    # Every step runs under a 2 s lock timeout and a 60 s statement timeout.
    assert {(lock, statement) for _, _, _, lock, statement in log} == {("2000", "60000")}
    # The index first, while no reader waits on it; the views before their
    # tables; then each table's policy before its row-level security.
    expected = [("CREATE INDEX", f"bills.{INDEX}")]
    expected += [("ALTER VIEW", f"bills.{view}") for view in VIEW_ORDER]
    for table in TABLE_ORDER:
        expected += [
            ("CREATE POLICY", f'"Public read" on bills.{table}'),
            ("ALTER TABLE", f"bills.{table}"),
        ]
    assert [(tag, identity) for tag, identity, *_ in log] == expected


CATALOG = """
select jsonb_build_object(
  'policies', (
    select jsonb_agg(jsonb_build_object(
      'oid', p.oid, 'table', c.relname, 'name', p.polname, 'command', p.polcmd,
      'permissive', p.polpermissive, 'roles', p.polroles::regrole[]::text,
      'using', pg_get_expr(p.polqual, p.polrelid),
      'check', pg_get_expr(p.polwithcheck, p.polrelid)) order by c.relname, p.polname)
    from pg_policy p join pg_class c on c.oid = p.polrelid
    where c.relnamespace = 'bills'::regnamespace),
  'relations', (
    select jsonb_agg(jsonb_build_object(
      'oid', oid, 'name', relname, 'kind', relkind, 'rls', relrowsecurity,
      'force', relforcerowsecurity, 'options', reloptions, 'acl', relacl::text) order by relname)
    from pg_class where relnamespace = 'bills'::regnamespace),
  'indexes', (
    select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid)
    from pg_index i join pg_class c on c.oid = i.indrelid
    where c.relnamespace = 'bills'::regnamespace))
"""


def test_the_migration_changes_nothing_when_it_runs_again(copy_of, replay):
    database = copy_of(replay.database)
    catalog, reads = database.run(CATALOG), database.read_everything()
    database.run(LOG_DDL)
    database.run_file(MIGRATIONS / RLS_MIGRATION)
    assert database.run(CATALOG) == catalog
    assert database.read_everything() == reads
    # A second run creates no policy and no index.
    assert {tag for tag, *_ in _ddl_log(database)} <= {"ALTER VIEW", "ALTER TABLE"}


def test_rerunning_an_older_view_migration_keeps_its_callers_rights(copy_of, replay):
    database = copy_of(replay.database)
    files = [
        path
        for path in _files(before_rls=True)
        if CREATE_VIEW.search(_strip_comments(path.read_text(encoding="utf-8")))
    ]
    assert files
    check = (
        "select relname from pg_class where relnamespace = 'bills'::regnamespace and relkind = 'v' "
        "and not coalesce((select option_value::boolean from pg_options_to_table(reloptions) "
        "where option_name = 'security_invoker'), false)"
    )
    for path in files:
        database.run_file(path)
        assert database.run(check) == "", path.name


def _read_line(stream, timeout: float) -> str:
    line: list[str] = []
    reader = threading.Thread(target=lambda: line.append(stream.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    return line[0].strip() if line else ""


@contextmanager
def _open_session(database: Database, script: str) -> Iterator[subprocess.Popen]:
    """Run a script in a psql session and keep its transaction open until the block ends."""
    session = subprocess.Popen(
        ["psql", database.url, *PSQL_FLAGS],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        session.stdin.write(f"{script}\n\\echo ready\n")
        session.stdin.flush()
        assert _read_line(session.stdout, 30) == "ready"
        yield session
    finally:
        if session.poll() is None:
            try:
                session.stdin.write("rollback;\n")
                session.stdin.close()
            except BrokenPipeError:
                pass
            try:
                session.wait(timeout=30)
            except subprocess.TimeoutExpired:
                session.kill()
                session.wait()


def _start(database: Database, sql: str, application: str) -> subprocess.Popen:
    session = subprocess.Popen(
        ["psql", database.url, *PSQL_FLAGS],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PGAPPNAME": application},
    )
    session.stdin.write(sql)
    session.stdin.close()
    return session


def _wait_for_lock_wait(database: Database, application: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waiting = database.run(
            "select count(*) from pg_stat_activity where datname = current_database() "
            f"and application_name = '{application}' and wait_event_type = 'Lock'"
        )
        if waiting != "0":
            return
        time.sleep(0.05)
    raise AssertionError(f"{application} never waited on a lock")


def test_a_lock_wait_aborts_the_whole_file_and_a_retry_starts_clean(copy_of, pre):
    database = copy_of(pre)
    catalog = database.run(CATALOG)
    last = TABLE_ORDER[-1]
    # A reader holds the last table, so the file waits there after every
    # earlier step has run.
    with _open_session(database, f"begin;\nlock table bills.{last} in access share mode;"):
        with pytest.raises(PsqlError, match="55P03"):
            database.run_file(MIGRATIONS / RLS_MIGRATION, timeout=60)
        assert database.run(CATALOG) == catalog
    database.run_file(MIGRATIONS / RLS_MIGRATION)
    assert database.run(
        "select count(*) from pg_class where relnamespace = 'bills'::regnamespace "
        "and relkind in ('r', 'p') and not relrowsecurity"
    ) == "0"


def test_the_index_build_blocks_writers_but_no_reader(copy_of, pre):
    database = copy_of(pre)
    index = next(
        statement
        for statement in _statements((MIGRATIONS / RLS_MIGRATION).read_text(encoding="utf-8"))
        if re.match(r"create\s+index\b", statement, re.I)
    )
    with _open_session(database, f"begin;\n{index};"):
        read = "set local lock_timeout = '2s'; select count(*) from bills.bills"
        assert int(database.as_role("anon", read)) > 0
        write = "set local lock_timeout = '200ms'; update bills.bills set title = title"
        with pytest.raises(PsqlError, match="55P03"):
            database.as_role("service_role", write)


# The bill page's read as PostgREST builds it: one LEFT JOIN LATERAL per embed,
# in the order api.ts names them.
BILL_PAGE = f"""
select b.*, s.name, j.name, a.rows, v.rows, t.rows, c.rows
from bills.bills b
left join lateral (select name from bills.sessions where id = b.session_id) s on true
left join lateral (select name from bills.jurisdictions where code = b.jurisdiction) j on true
left join lateral (select json_agg(x) as rows from
  (select occurred_at from bills.bill_actions where bill_id = b.id) x) a on true
left join lateral (select json_agg(x) as rows from
  (select label from bills.bill_versions where bill_id = b.id) x) v on true
left join lateral (select json_agg(x) as rows from
  (select version_label from bills.bill_texts where bill_id = b.id) x) t on true
left join lateral (select json_agg(x) as rows from
  (select citation from bills.bill_citations where bill_id = b.id) x) c on true
where b.id = '{BILL_ID}';
"""


def test_the_bill_page_and_the_migration_do_not_deadlock(copy_of, pre):
    """A bill page read that waits mid-way doesn't deadlock with the migration.

    A third session holds sessions, so the read stops there holding bills.
    The migration then starts and waits for the read at bills. Once the third
    session lets go, the read finishes and the migration goes on.
    """
    suffix = uuid.uuid4().hex[:8]
    reader_name, migration_name = f"bill_page_{suffix}", f"rls_migration_{suffix}"
    outcomes = []
    for _ in range(3):
        database = copy_of(pre)
        with _open_session(database, "begin;\nlock table bills.sessions in access exclusive mode;"):
            reader = _start(database, f"set role anon;\n{BILL_PAGE}", reader_name)
            _wait_for_lock_wait(database, reader_name)
            migration = _start(
                database, (MIGRATIONS / RLS_MIGRATION).read_text(encoding="utf-8"), migration_name
            )
            _wait_for_lock_wait(database, migration_name)
        reader_error = reader.communicate(timeout=60)[1]
        migration_error = migration.communicate(timeout=60)[1]
        outcomes.append((reader.returncode, reader_error, migration.returncode, migration_error))
        # A lock timeout here means a slow machine, not a deadlock: try again.
        if "55P03" not in reader_error + migration_error:
            break
    assert not any("40P01" in reader + migration for _, reader, _, migration in outcomes)
    assert outcomes[-1][0] == 0 and outcomes[-1][2] == 0, outcomes[-1]


# --- Hypothesis: the file parsers against Postgres ---------------------------


@pytest.fixture(scope="session")
def probe(server: Server) -> Database:
    """A database with one table for policy and view probes."""
    database = server.create_database()
    database.run("create schema bills; create table bills.policy_probe (id int);")
    return database


@settings(max_examples=40, deadline=None)
@given(case=policy_statements())
def test_file_parser_reads_policies_as_postgres_does(probe, case):
    statement, _ = case
    stored = probe.run(
        f"begin; set local search_path = bills;\n{statement};\n"
        "select lower(cmd), lower(permissive), array_to_string(roles, ',') from pg_policies "
        "where tablename = 'policy_probe';\nrollback;"
    )
    command, kind, roles = stored.split("|")
    assert _policies(statement) == [
        Policy("policy_probe", True, kind, command, frozenset(roles.split(",")))
    ]


@settings(max_examples=40, deadline=None)
@given(case=view_scripts())
def test_file_parser_reads_view_options_as_postgres_does(replayable, probe, case):
    script, _ = case
    stored = probe.run(
        f"begin; set local search_path = bills;\n{script}"
        "select relname, coalesce((select option_value::boolean from pg_options_to_table(reloptions) "
        "where option_name = 'security_invoker'), false) from pg_class "
        "where relnamespace = 'bills'::regnamespace and relkind = 'v';\nrollback;"
    )
    views = {name: flag == "t" for name, flag in (line.split("|") for line in stored.splitlines())}
    assert _replay([("probe.sql", script)]).views == views


@settings(max_examples=40, deadline=None)
@given(
    words=st.lists(
        st.text(alphabet="trueTRUEfalsFALSyYnNoO01x", min_size=1, max_size=6),
        min_size=1,
        max_size=20,
    )
)
def test_file_boolean_parser_matches_postgres(probe, words):
    values = ", ".join(f"('{word}')" for word in words)
    parsed = probe.run(
        "begin;\n"
        "create function pg_temp.parse_bool(value text) returns text language plpgsql as $$\n"
        "begin return value::boolean::text; exception when invalid_text_representation then "
        "return 'invalid'; end $$;\n"
        f"select pg_temp.parse_bool(word) from (values {values}) as words(word);\nrollback;"
    ).splitlines()
    expected = [{True: "true", False: "false", None: "invalid"}[_pg_bool(word)] for word in words]
    assert parsed == expected
