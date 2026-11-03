"""Every bills table and view keeps row-level security through later migrations.

The bills schema's default privileges grant anon SELECT on each new table, so a
new table without these statements serves the Data API with no row-level check.

The first group of tests reads the migration files. The second replays them on a
real Postgres and needs a superuser connection on PostgreSQL 15 or later, where
security_invoker views arrived:

    AXIOM_BILLS_TEST_POSTGRES_URL=postgresql://postgres@localhost/postgres pytest

Invariants the second group checks, for each role, table and view:

- anon and authenticated read exactly what they read before the migration;
- neither role can write, even after a stray write grant;
- the service role keeps every read and write;
- each view applies its caller's row-level security, not its owner's.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RLS_MIGRATION = "20261102120000_bills_row_level_security.sql"
ADMIN_URL = os.environ.get("AXIOM_BILLS_TEST_POSTGRES_URL")

CREATE_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?bills\.(\w+)", re.I)
ENABLE_RLS = re.compile(r"alter\s+table\s+bills\.(\w+)\s+enable\s+row\s+level\s+security", re.I)
READ_POLICY = re.compile(
    r"create\s+policy\s+\"[^\"]+\"\s+on\s+bills\.(\w+)\s+for\s+select\s+to\s+anon,\s*authenticated",
    re.I,
)
WRITE_POLICY = re.compile(
    r"create\s+policy\s+\"[^\"]+\"\s+on\s+bills\.\w+\s+(?:for\s+(?:all|insert|update|delete)\b"
    r"|using\b|with\s+check\b|to\b)",
    re.I,
)
CREATE_VIEW = re.compile(r"create\s+(?:or\s+replace\s+)?view\s+bills\.(\w+)(\s+with\s*\([^)]*\))?", re.I)
ALTER_VIEW_INVOKER = re.compile(
    r"alter\s+view\s+bills\.(\w+)\s+set\s*\(\s*security_invoker\s*=\s*(?:true|on)\s*\)",
    re.I,
)
DROP_VIEW = re.compile(r"drop\s+view\s+(?:if\s+exists\s+)?bills\.(\w+)", re.I)
INVOKER_OPTION = re.compile(r"security_invoker\s*=\s*(?:true|on)", re.I)


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _migrations() -> list[tuple[str, str]]:
    return [
        (path.name, _strip_comments(path.read_text(encoding="utf-8")))
        for path in sorted(MIGRATIONS.glob("*.sql"))
    ]


def _view_states(migrations: list[tuple[str, str]]) -> dict[str, bool]:
    """Replay the migrations in order: does each view end up with its caller's rights?"""
    events = re.compile(
        "|".join(f"(?P<{name}>{rx.pattern})" for name, rx in {
            "create": CREATE_VIEW,
            "alter": ALTER_VIEW_INVOKER,
            "drop": DROP_VIEW,
        }.items()).replace("(\\w+)", "(?:\\w+)"),
        re.I,
    )
    states: dict[str, bool] = {}
    for _, sql in migrations:
        for match in events.finditer(sql):
            text = match.group(0)
            if match.lastgroup == "create":
                states[CREATE_VIEW.match(text).group(1)] = bool(INVOKER_OPTION.search(text))
            elif match.lastgroup == "alter":
                states[ALTER_VIEW_INVOKER.match(text).group(1)] = True
            else:
                states.pop(DROP_VIEW.match(text).group(1), None)
    return states


def test_rls_migration_is_present():
    assert RLS_MIGRATION in {name for name, _ in _migrations()}


def test_every_table_has_row_level_security_and_a_read_policy():
    migrations = _migrations()
    created = {table for _, sql in migrations for table in CREATE_TABLE.findall(sql)}
    assert "bills" in created
    enabled = {table for _, sql in migrations for table in ENABLE_RLS.findall(sql)}
    read = {table for _, sql in migrations for table in READ_POLICY.findall(sql)}
    assert created - enabled == set()
    assert created - read == set()


def test_no_migration_adds_a_policy_that_can_write():
    for name, sql in _migrations():
        assert WRITE_POLICY.findall(sql) == [], name


def test_every_view_ends_up_running_with_its_callers_rights():
    states = _view_states(_migrations())
    assert {"jurisdiction_summary", "bill_list_summary", "current_rule_patches"} <= set(states)
    assert [view for view, invoker in states.items() if not invoker] == []


def test_replaying_a_later_replacement_loses_the_setting():
    """A later CREATE OR REPLACE VIEW without the option counts as a regression."""
    migrations = [
        *_migrations(),
        ("zzz.sql", "create or replace view bills.bill_list_summary as select 1;"),
    ]
    assert _view_states(migrations)["bill_list_summary"] is False
    migrations.append(
        ("zzzz.sql", "create or replace view bills.bill_list_summary with (security_invoker = true) as select 1;")
    )
    assert _view_states(migrations)["bill_list_summary"] is True


requires_postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="AXIOM_BILLS_TEST_POSTGRES_URL is not set"
)

READ_ROLES = ("anon", "authenticated")
TABLES = (
    "jurisdictions",
    "sessions",
    "bills",
    "bill_actions",
    "bill_versions",
    "bill_texts",
    "bill_citations",
    "axiom_encodings",
    "encoded_rules",
    "encoded_rule_atoms",
    "rule_variants",
    "encoding_graphs",
    "bill_reconciliations",
    "encode_queue",
)
# Each view, and a table whose rows decide whether the view returns a row.
VIEW_BASES = {
    "jurisdiction_summary": "jurisdictions",
    "bill_list_summary": "bills",
    "current_rule_patches": "rule_variants",
}
RELATIONS = (*TABLES, *VIEW_BASES)

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
REMOVE_SEED_ROWS = f"""
delete from bills.encoding_graphs where repo = 'rulespec-zz';
delete from bills.axiom_encodings where id = '{ENCODING_ID}';
delete from bills.sessions where id = '{SESSION_ID}';
delete from bills.bills where id = '{BILL_ID}';
delete from bills.jurisdictions where code = 'zz';
"""


class PsqlError(RuntimeError):
    """psql exited non-zero. The message carries the SQLSTATE."""


@dataclass(frozen=True)
class Database:
    url: str

    def run(self, sql: str) -> str:
        done = subprocess.run(
            ["psql", self.url, "-X", "-q", "-At"]
            + ["-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose"],
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise PsqlError(done.stderr)
        return done.stdout.strip()

    def as_role(self, role: str, sql: str, setup: str = "") -> str:
        """Run the statements as a role, then roll everything back."""
        return self.run(f"begin;\n{setup};\nset local role {role};\n{sql};\nrollback;")

    def read_everything(self, role: str) -> dict[str, list]:
        return {
            relation: json.loads(
                self.as_role(
                    role,
                    "select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text), '[]') "
                    f"from bills.{relation} as t",
                )
            )
            for relation in RELATIONS
        }

    def column_one(self, table: str) -> str:
        return self.run(
            "select attname from pg_attribute "
            f"where attrelid = 'bills.{table}'::regclass and attnum = 1"
        )


@dataclass(frozen=True)
class Replay:
    database: Database
    reads_before: dict[str, dict[str, list]]


def _count_changed(statement: str) -> str:
    return f"with changed as ({statement} returning 1) select count(*) from changed"


@pytest.fixture(scope="module")
def replay() -> Iterator[Replay]:
    assert ADMIN_URL
    admin = Database(ADMIN_URL)
    created_roles = [
        role
        for role, options in {
            "anon": "nologin noinherit",
            "authenticated": "nologin noinherit",
            "service_role": "nologin noinherit bypassrls",
        }.items()
        if admin.run(f"select count(*) from pg_roles where rolname = '{role}'") == "0"
        and admin.run(f"create role {role} {options}") == ""
    ]
    name = f"axiom_bills_rls_{uuid.uuid4().hex[:12]}"
    admin.run(f"create database {name}")
    try:
        # Studio's editor resolved the coverage migrations' unqualified names.
        admin.run(f"alter database {name} set search_path = bills, public")
        database = Database(urlunsplit(urlsplit(ADMIN_URL)._replace(path=f"/{name}")))
        migrations = sorted(MIGRATIONS.glob("*.sql"))
        for path in migrations:
            if path.name < RLS_MIGRATION:
                database.run(path.read_text(encoding="utf-8"))
        database.run(SEED_ROWS)
        reads_before = {role: database.read_everything(role) for role in READ_ROLES}
        tables_with_rls = database.run(
            "select count(*) from pg_class "
            "where relnamespace = 'bills'::regnamespace and relrowsecurity"
        )
        # Without this, the checks below could pass on a schema that was already closed.
        assert tables_with_rls == "0"
        assert all(rows for reads in reads_before.values() for rows in reads.values())
        for path in migrations:
            if path.name >= RLS_MIGRATION:
                database.run(path.read_text(encoding="utf-8"))
        yield Replay(database, reads_before)
    finally:
        admin.run(f"drop database if exists {name} with (force)")
        for role in created_roles:
            admin.run(f"drop role if exists {role}")


@requires_postgres
def test_the_lists_above_cover_every_table_and_view(replay):
    database = replay.database
    tables = database.run(
        "select relname from pg_class "
        "where relnamespace = 'bills'::regnamespace and relkind in ('r', 'p')"
    ).split()
    views = database.run(
        "select relname from pg_class "
        "where relnamespace = 'bills'::regnamespace and relkind in ('v', 'm')"
    ).split()
    assert set(tables) == set(TABLES)
    assert set(views) == set(VIEW_BASES)


def test_the_file_parsers_find_the_listed_tables_and_views():
    migrations = _migrations()
    assert {table for _, sql in migrations for table in CREATE_TABLE.findall(sql)} == set(TABLES)
    assert set(_view_states(migrations)) == set(VIEW_BASES)


@requires_postgres
@pytest.mark.parametrize("role", READ_ROLES)
def test_each_role_reads_what_it_read_before(replay, role):
    assert replay.database.read_everything(role) == replay.reads_before[role]


@requires_postgres
def test_each_table_has_row_level_security_and_one_read_policy(replay):
    database = replay.database
    assert database.run(
        "select count(*) from pg_class where relnamespace = 'bills'::regnamespace "
        "and relkind in ('r', 'p') and not relrowsecurity"
    ) == "0"
    policies = json.loads(
        database.run(
            "select jsonb_agg(jsonb_build_object('table', tablename, 'name', policyname, "
            "'kind', permissive, 'roles', roles, 'cmd', cmd, 'using', qual, 'check', with_check)) "
            "from pg_policies where schemaname = 'bills'"
        )
    )
    assert {policy["table"] for policy in policies} == set(TABLES)
    assert len(policies) == len(TABLES)
    for policy in policies:
        assert policy["name"] == "Public read"
        assert policy["kind"] == "PERMISSIVE"
        assert sorted(policy["roles"]) == sorted(READ_ROLES)
        assert policy["cmd"] == "SELECT"
        assert policy["using"] == "true"
        assert policy["check"] is None


@requires_postgres
@pytest.mark.parametrize(("view", "base"), VIEW_BASES.items())
def test_a_view_applies_its_callers_row_level_security(replay, view, base):
    database = replay.database
    options = database.run(f"select reloptions from pg_class where oid = 'bills.{view}'::regclass")
    assert "security_invoker=true" in options
    count = f"select count(*) from bills.{view}"
    assert int(database.as_role("anon", count)) > 0
    assert (
        database.as_role(
            "anon", count, setup=f'drop policy "Public read" on bills.{base}'
        )
        == "0"
    )


@requires_postgres
@pytest.mark.parametrize("role", READ_ROLES)
@pytest.mark.parametrize("table", TABLES)
def test_a_role_has_no_write_grant(replay, role, table):
    database = replay.database
    column = database.column_one(table)
    for statement in (
        f"insert into bills.{table} default values",
        f"update bills.{table} set {column} = {column}",
        f"delete from bills.{table}",
    ):
        with pytest.raises(PsqlError, match="42501: permission denied"):
            database.as_role(role, statement)


@requires_postgres
@pytest.mark.parametrize("role", READ_ROLES)
@pytest.mark.parametrize("view", VIEW_BASES)
def test_a_role_cannot_write_through_a_view(replay, role, view):
    # 42501 means no grant; 55000 means the view can't take that write at all.
    with pytest.raises(PsqlError, match="(42501|55000):"):
        replay.database.as_role(role, f"delete from bills.{view}")


@requires_postgres
@pytest.mark.parametrize("role", READ_ROLES)
@pytest.mark.parametrize("table", TABLES)
def test_a_stray_write_grant_still_changes_nothing(replay, role, table):
    database = replay.database
    column = database.column_one(table)
    stray_grant = f"grant insert, update, delete on bills.{table} to {role}"
    for statement in (
        f"update bills.{table} set {column} = {column}",
        f"delete from bills.{table}",
    ):
        assert database.as_role(role, _count_changed(statement), setup=stray_grant) == "0"
    # Postgres checks row-level security before constraints, so this reports the
    # policy even though the row breaks NOT NULL too.
    with pytest.raises(PsqlError, match="42501: new row violates row-level security"):
        database.as_role(role, f"insert into bills.{table} default values", setup=stray_grant)


@requires_postgres
@pytest.mark.parametrize("table", TABLES)
def test_the_service_role_updates_each_table(replay, table):
    database = replay.database
    column = database.column_one(table)
    changed = database.as_role(
        "service_role", _count_changed(f"update bills.{table} set {column} = {column}")
    )
    assert int(changed) > 0


@requires_postgres
def test_the_service_role_deletes_and_writes_each_table(replay):
    counts = " union all ".join(
        f"select '{table}', count(*) from bills.{table}" for table in TABLES
    )
    before = replay.database.as_role("service_role", counts)
    # Deleting the seed rows must empty these tables of them, or the inserts collide.
    after = replay.database.as_role("service_role", f"{REMOVE_SEED_ROWS}{SEED_ROWS}{counts}")
    assert after == before


@requires_postgres
def test_the_service_role_upserts_as_the_sync_does(replay):
    renamed = replay.database.as_role(
        "service_role",
        "insert into bills.jurisdictions (code, name, level, source_url) "
        "values ('zz', 'Renamed', 'state', 'https://example.test/') "
        "on conflict (code) do update set name = excluded.name returning name",
    )
    assert renamed == "Renamed"


@requires_postgres
def test_the_table_owner_keeps_access(replay):
    database = replay.database
    assert database.run(
        "select count(*) from pg_class where relnamespace = 'bills'::regnamespace "
        "and relforcerowsecurity"
    ) == "0"
    assert database.run("select count(*) from bills.bills where jurisdiction = 'zz'") == "1"


@requires_postgres
def test_the_migration_can_run_again(replay):
    database = replay.database
    database.run((MIGRATIONS / RLS_MIGRATION).read_text(encoding="utf-8"))
    assert database.run("select count(*) from pg_policies where schemaname = 'bills'") == str(
        len(TABLES)
    )
    for role in READ_ROLES:
        assert database.read_everything(role) == replay.reads_before[role]
