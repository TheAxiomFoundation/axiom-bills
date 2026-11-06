"""refresh-state-bills.yml: which steps run, in what order, and how the job ends.

These tests run the step's own script in bash, as GitHub runs it, with a stub in
place of `uv` that records each command and exits with the status a test picks.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from axiom_bills import cli
from axiom_bills.jurisdictions.us_ny.bill.scrape import REQUEST_TIMEOUT

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "refresh-state-bills.yml"
DOWNSTREAM = ["reclassify", "reclassify-kinds", "extract-citations", "sync-supabase"]
STUB = """#!/usr/bin/env bash
for word in "$@"; do
  case "$word" in
    hydrate-refresh-state|scrape|reclassify|reclassify-kinds|extract-citations|sync-supabase|push-refresh-state)
      echo "$*" >> "$UV_LOG"
      variable="STATUS_$(echo "$word" | tr 'a-z-' 'A-Z_')"
      exit "${!variable:-0}"
      ;;
  esac
done
echo "unexpected uv call: $*" >> "$UV_LOG"
exit 99
"""


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _refresh_step() -> dict:
    steps = _workflow()["jobs"]["refresh"]["steps"]
    return next(step for step in steps if step.get("name", "").startswith("Refresh "))


@dataclass
class Run:
    exit_code: int
    output: str
    calls: list[str]

    @property
    def commands(self) -> list[str]:
        return [_command_of(call) for call in self.calls]


def _command_of(call: str) -> str:
    return call.split("axiom-bills ", 1)[1].split()[0]


@pytest.fixture
def run_step(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "uv"
    stub.write_text(STUB)
    stub.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(_refresh_step()["run"])
    log = tmp_path / "uv.log"

    def run(
        *,
        state: str = "us-ny",
        requested: str = "",
        key: str = "a-key",
        **statuses: int,
    ) -> Run:
        log.write_text("")
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STATE": state,
            "REQUESTED_STATE": requested,
            "NYSENATE_API_KEY": key,
            "INDIANA_API_KEY": "a-key",
            "UV_LOG": str(log),
            **{f"STATUS_{name.upper()}": str(status) for name, status in statuses.items()},
        }
        # What GitHub runs for `shell: bash`.
        done = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        return Run(done.returncode, done.stdout + done.stderr, log.read_text().splitlines())

    return run


# --- New York ----------------------------------------------------------------


def test_a_clean_new_york_run_saves_its_place_after_the_sync(run_step) -> None:
    run = run_step()

    assert run.exit_code == 0, run.output
    assert run.commands == ["hydrate-refresh-state", "scrape", *DOWNSTREAM, "push-refresh-state"]
    assert "::error::" not in run.output
    assert "::warning::" not in run.output


def test_new_york_scrapes_on_a_budget_and_names_its_jurisdiction(run_step) -> None:
    run = run_step()

    [hydrate, scrape, *_, push] = run.calls
    assert "--jurisdiction us-ny" in hydrate
    assert "--jurisdiction us-ny" in scrape
    assert "--time-budget-minutes" in scrape
    assert "--jurisdiction us-ny" in push


def test_an_out_of_time_run_syncs_saves_its_place_and_stays_green(run_step) -> None:
    run = run_step(scrape=cli.EXIT_OUT_OF_TIME)

    assert run.exit_code == 0, run.output
    assert run.commands == ["hydrate-refresh-state", "scrape", *DOWNSTREAM, "push-refresh-state"]
    assert "::warning::us-ny: the time budget ran out" in run.output
    assert "::error::" not in run.output


def test_a_run_with_failed_bills_syncs_saves_its_place_and_fails_the_job(run_step) -> None:
    run = run_step(scrape=cli.EXIT_BILLS_FAILED)

    assert run.exit_code == cli.EXIT_BILLS_FAILED, run.output
    assert run.commands == ["hydrate-refresh-state", "scrape", *DOWNSTREAM, "push-refresh-state"]
    assert "::error::us-ny: some bills failed" in run.output


@pytest.mark.parametrize("status", [1, 2, 5, 137])
def test_any_other_scrape_failure_syncs_nothing_and_saves_no_place(run_step, status) -> None:
    run = run_step(scrape=status)

    assert run.exit_code == status, run.output
    assert run.commands == ["hydrate-refresh-state", "scrape"]
    assert f"::error::us-ny: the scrape failed with exit {status}" in run.output


def test_a_failed_hydrate_stops_before_the_scrape(run_step) -> None:
    # With no saved place the scrape would start a full load, and the missing table
    # means the chamber relabel hasn't run either.
    run = run_step(hydrate_refresh_state=1)

    assert run.exit_code == 1, run.output
    assert run.commands == ["hydrate-refresh-state"]


@pytest.mark.parametrize("scrape_status", [0, cli.EXIT_BILLS_FAILED, cli.EXIT_OUT_OF_TIME])
def test_a_failed_sync_never_saves_a_place(run_step, scrape_status) -> None:
    # The saved place says the bills reached Supabase, and these didn't.
    run = run_step(scrape=scrape_status, sync_supabase=1)

    assert run.exit_code == 1, run.output
    assert run.commands == ["hydrate-refresh-state", "scrape", *DOWNSTREAM]


@pytest.mark.parametrize("failing", ["reclassify", "reclassify_kinds", "extract_citations"])
def test_a_failure_before_the_sync_stops_the_job(run_step, failing) -> None:
    run = run_step(**{failing: 1})

    assert run.exit_code == 1, run.output
    assert "sync-supabase" not in run.commands
    assert "push-refresh-state" not in run.commands


@pytest.mark.parametrize("scrape_status", [0, cli.EXIT_BILLS_FAILED, cli.EXIT_OUT_OF_TIME])
def test_a_failed_push_fails_the_job(run_step, scrape_status) -> None:
    run = run_step(scrape=scrape_status, push_refresh_state=1)

    assert run.exit_code == 1, run.output
    assert run.commands[-1] == "push-refresh-state"


def test_no_step_prints_the_key(run_step) -> None:
    for status in (0, 1, cli.EXIT_BILLS_FAILED, cli.EXIT_OUT_OF_TIME):
        run = run_step(key="SENTINEL-KEY-VALUE", scrape=status)
        assert "SENTINEL-KEY-VALUE" not in run.output
        assert all("SENTINEL-KEY-VALUE" not in call for call in run.calls)


# --- A missing key -----------------------------------------------------------


def test_a_missing_key_warns_and_skips_new_york_in_the_full_matrix(run_step) -> None:
    run = run_step(key="")

    assert run.exit_code == 0, run.output
    assert run.calls == []
    assert "::warning::Skipping us-ny" in run.output


def test_a_missing_key_fails_a_run_that_asked_for_new_york(run_step) -> None:
    run = run_step(key="", requested="us-ny")

    assert run.exit_code == 1, run.output
    assert run.calls == []
    assert "::error::Can't refresh us-ny" in run.output


# --- Other states ------------------------------------------------------------


def test_another_state_runs_as_it_did_with_no_state_steps(run_step) -> None:
    run = run_step(state="us-ca", key="")

    assert run.exit_code == 0, run.output
    assert run.commands == ["scrape", *DOWNSTREAM]
    assert "--time-budget-minutes" not in run.calls[0]


@pytest.mark.parametrize("status", [1, 2, cli.EXIT_BILLS_FAILED, cli.EXIT_OUT_OF_TIME])
def test_another_states_failed_scrape_stops_the_job_whatever_its_status(run_step, status) -> None:
    run = run_step(state="us-ca", scrape=status)

    assert run.exit_code == status, run.output
    assert run.commands == ["scrape"]


def test_a_state_nobody_asked_for_skips_quietly(run_step) -> None:
    run = run_step(state="us-ca", requested="us-ny")

    assert run.exit_code == 0, run.output
    assert run.calls == []


# --- The job itself ----------------------------------------------------------


def test_the_workflow_stays_manual() -> None:
    # PyYAML reads a bare `on` as True.
    assert list(_workflow()[True]) == ["workflow_dispatch"]


def test_the_job_keeps_its_60_minute_cap() -> None:
    assert _workflow()["jobs"]["refresh"]["timeout-minutes"] == 60


def test_the_step_runs_in_bash() -> None:
    assert _refresh_step()["shell"] == "bash"


def test_the_budget_leaves_room_for_everything_else_inside_the_cap() -> None:
    match = re.search(r"--time-budget-minutes (\d+(?:\.\d+)?)", _refresh_step()["run"])
    assert match is not None
    budget = float(match.group(1))
    cap = _workflow()["jobs"]["refresh"]["timeout-minutes"]
    # Measured on the workflow's successful New York jobs in June 2026: under a
    # minute before the refresh step, and at most 28 minutes for the steps after a
    # scrape of 25,309 bills. A budgeted run holds fewer bills than that.
    before_the_scrape = 1
    after_the_scrape = 28
    request_in_flight = (REQUEST_TIMEOUT.connect + REQUEST_TIMEOUT.read) / 60

    assert before_the_scrape + budget + request_in_flight + after_the_scrape <= cap
