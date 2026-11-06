#!/usr/bin/env python3
"""Run bill_action_cleanup.sql against a database, one step at a time.

Each command does one step and prints where things stand. A stop at any point
loses nothing: rerun the same command to carry on. bill_action_cleanup.sql
explains the steps and how to reverse them.

Before you start:
- Confirm no refresh is running, and hold off starting one until the swap:
    gh run list --repo TheAxiomFoundation/axiom-bills --status in_progress
- Note the disk: Studio's Compute and Disk page, or the Management API's
  /config/disk/util. prepare frees 17 GB of it.

On production, through the Management API (SUPABASE_ACCESS_TOKEN in the
environment):

    bill_action_cleanup.py --ref <project ref> install
    bill_action_cleanup.py --ref <project ref> prepare
    bill_action_cleanup.py --ref <project ref> copy --pause 1
    bill_action_cleanup.py --ref <project ref> build
    bill_action_cleanup.py --ref <project ref> verify --pause 1
    bill_action_cleanup.py --ref <project ref> problems
    bill_action_cleanup.py --ref <project ref> swap
    # Look at some bill pages. About a week later:
    bill_action_cleanup.py --ref <project ref> finish

Against any other Postgres, use --url <connection string> in place of --ref, with
psql on PATH.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

SQL_FILE = Path(__file__).with_name("bill_action_cleanup.sql")

REBUILD_UNIQUE_INDEX = """\
-- Run these over a direct connection, one at a time, before any sync writes. On the
-- full table they take hours, and the sort can cross the disk's 90% line.
set statement_timeout = 0;
create unique index concurrently bill_actions_bill_id_fingerprint_key
  on bills.bill_actions (bill_id, fingerprint);
alter table bills.bill_actions add constraint bill_actions_bill_id_fingerprint_key
  unique using index bill_actions_bill_id_fingerprint_key;
-- Then, unless you mean to try the cleanup again, remove its schemas:
--   drop schema bill_action_cleanup cascade;
--   drop schema bill_action_cleanup_old;
"""


class Database:
    def run(self, sql: str) -> str:
        """Run SQL and return the first column of the first row, as text."""
        raise NotImplementedError

    def call(self, sql: str) -> dict:
        return json.loads(self.run(sql))


class ManagementApi(Database):
    def __init__(self, ref: str, token: str) -> None:
        self.url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
        self.token = token

    def run(self, sql: str) -> str:
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"query": sql}).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "axiom-bills-action-cleanup",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                rows = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{error.code}: {error.read().decode()[:2000]}") from error
        except http.client.HTTPException as error:
            raise RuntimeError(f"the reply broke off: {error}") from error
        if not rows:
            return ""
        value = next(iter(rows[0].values()))
        if value is None:
            return ""
        return value if isinstance(value, str) else json.dumps(value)


class Psql(Database):
    def __init__(self, url: str) -> None:
        self.url = url

    def run(self, sql: str) -> str:
        done = subprocess.run(
            ["psql", self.url, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise RuntimeError(done.stderr)
        return done.stdout.strip()


def _walk(
    database: Database,
    *,
    function: str,
    through: str,
    pages: int,
    pause: float,
    max_batches: int | None,
    retries: int,
    say: Callable[[str], None],
) -> dict:
    """Call a batch function page range by page range until the last page.

    The ledger says where to go next, so a lost reply can't skip a batch or run
    one twice: the function refuses a range out of order, and each retry starts
    from what the database says.
    """
    started = time.monotonic()
    batches = 0
    failures = 0
    status = database.call("select bill_action_cleanup.status()")
    if not status["prepared"]:
        raise RuntimeError("run prepare first")
    if function == "verify_batch" and not status["built"]:
        raise RuntimeError("run build first")
    first_seen = status[through]
    while status[through] < status["heap_pages"]:
        if max_batches is not None and batches >= max_batches:
            break
        first = status[through]
        try:
            status = database.call(f"select bill_action_cleanup.{function}({first}, {first + pages})")
        except (RuntimeError, OSError) as error:
            failures += 1
            say(f"{function}({first}) failed ({failures}/{retries}): {error}")
            if failures >= retries:
                raise
            time.sleep(30 * failures)
            status = database.call("select bill_action_cleanup.status()")
            continue
        failures = 0
        batches += 1
        if batches % 50 == 0 or status[through] >= status["heap_pages"]:
            done = status[through] - first_seen
            rate = done / max(time.monotonic() - started, 0.001)
            left = (status["heap_pages"] - status[through]) / rate if rate else 0
            say(f"{function}: page {status[through]:,} of {status['heap_pages']:,}, "
                f"{rate:,.0f} pages/s, about {left / 60:,.0f} min left, "
                f"{status['rows_kept']:,} rows kept of {status['rows_read']:,} read, "
                f"{status['rows_verified']:,} verified, {status['rows_missing']:,} missing")
        if pause:
            time.sleep(pause)
    return status


def run_step(
    database: Database,
    step: str,
    *,
    pages: int = 1000,
    pause: float = 0,
    max_batches: int | None = None,
    retries: int = 5,
    say: Callable[[str], None] = print,
) -> dict | list:
    if step == "install":
        database.run(SQL_FILE.read_text(encoding="utf-8"))
        return database.call("select bill_action_cleanup.status()")
    if step == "status":
        return database.call("select bill_action_cleanup.status()")
    if step == "prepare":
        return database.call("select bill_action_cleanup.prepare()")
    if step == "copy":
        return _walk(database, function="copy_batch", through="copied_through", pages=pages,
                     pause=pause, max_batches=max_batches, retries=retries, say=say)
    if step == "build":
        while piece := database.run("select bill_action_cleanup.build_next()"):
            say(f"built {piece}")
        return database.call("select bill_action_cleanup.status()")
    if step == "verify":
        return _walk(database, function="verify_batch", through="verified_through", pages=pages,
                     pause=pause, max_batches=max_batches, retries=retries, say=say)
    if step == "problems":
        return database.call("select to_jsonb(bill_action_cleanup.problems())")
    if step == "swap":
        return database.call("select bill_action_cleanup.swap()")
    if step == "swap-back":
        status = database.call("select bill_action_cleanup.swap_back()")
        say("The old table refuses writes until you run abort, which drops the new table.")
        return status
    if step == "abort":
        status = database.call("select bill_action_cleanup.abort()")
        say(REBUILD_UNIQUE_INDEX)
        return status
    if step == "finish":
        result = database.call("select bill_action_cleanup.finish()")
        database.run("drop schema bill_action_cleanup cascade")
        return result
    raise ValueError(f"unknown step {step}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ref", help="Supabase project ref, for the Management API")
    target.add_argument("--url", help="Postgres connection string, for psql")
    parser.add_argument("step", choices=["install", "status", "prepare", "copy", "build", "verify",
                                         "problems", "swap", "swap-back", "abort", "finish"])
    parser.add_argument("--pages", type=int, default=1000, help="heap pages per batch")
    parser.add_argument("--pause", type=float, default=0, help="seconds to wait between batches")
    parser.add_argument("--max-batches", type=int, help="stop after this many batches")
    args = parser.parse_args()
    if args.ref:
        token = os.environ.get("SUPABASE_ACCESS_TOKEN")
        if not token:
            sys.exit("Set SUPABASE_ACCESS_TOKEN")
        database: Database = ManagementApi(args.ref, token)
    else:
        database = Psql(args.url)
    result = run_step(database, args.step, pages=args.pages, pause=args.pause, max_batches=args.max_batches)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
