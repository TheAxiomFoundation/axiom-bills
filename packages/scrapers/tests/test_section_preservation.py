"""A corpus miss must not overwrite a section an earlier run matched.

axiom-corpus stopped serving most of the US Code in July 2026 (serving
moved to RuleSpec-cited scopes), and `corpus_client` reports a failed
lookup the same way as an absent row. Either way a fresh CI run computes
"no corpus text" for a section whose stored diff holds real statutory
text. These tests pin the merge that keeps the stored section, and the
two places it runs: `hydrate-diffs` and the `sync-supabase` backstop.
Supabase is never contacted.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

from axiom_bills._common import supabase_sync
from axiom_bills._common.section_preservation import (
    has_corpus_miss,
    preserve_stored_sections,
    touch_flags,
)


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
SCHEMA_MIGRATIONS = [
    "001_init.sql",
    "004_encodings_and_citations.sql",
    "007_rule_variants.sql",             # 056 alters it
    "056_variant_source_tracking.sql",   # adds bills.diffs
    "057_bill_touch_flags.sql",          # adds bills.touches_rulespec
    "058_needs_new_encoding.sql",
]

OSHA = "29 USC 655(b)"
OP = {"kind": "strike-insert", "target": OSHA, "needle": "30 days",
      "payload": "60 days", "raw": "by striking “30 days” and "
                                   "inserting “60 days”"}


def _matched(citation: str = OSHA, **overrides) -> dict:
    """A section as an earlier run stored it: matched to corpus text."""
    section = {
        "citation": citation,
        "in_corpus": True,
        "exact_corpus_match": False,
        "sliced_subsection": True,
        "matched_corpus_path": "us/statute/29/655",
        "heading": "Standards",
        "citation_path": "us/statute/29/655",
        "current_text": "within 30 days after publication",
        "applied_text": "within 60 days after publication",
        "diff": [{"op": "replace"}],
        "applied_ops": [dict(OP)],
        "unapplied_ops": [],
        "parse_warnings": [],
        "block_raw": None,
        "has_rulespec": False,
        "encoding": None,
        "encoding_backlog": False,
        "axiom_url": "https://app.axiom-foundation.org/us/statute/29/655",
        "source_url": "https://uscode.house.gov/view.xhtml?req=29-655",
    }
    section.update(overrides)
    return section


def _missed(citation: str = OSHA, **overrides) -> dict:
    """The same section as a fresh run computes it on a corpus miss."""
    section = {
        "citation": citation,
        "in_corpus": False,
        "exact_corpus_match": False,
        "sliced_subsection": False,
        "matched_corpus_path": None,
        "heading": None,
        "citation_path": None,
        "current_text": None,
        "applied_text": None,
        "diff": [],
        "applied_ops": [],
        "unapplied_ops": [dict(OP)],
        "parse_warnings": [],
        "block_raw": None,
        "has_rulespec": False,
        "encoding": None,
        "encoding_backlog": False,
        "axiom_url": None,
        "source_url": None,
    }
    section.update(overrides)
    return section


def _payload(*sections: dict, sha: str | None = "sha-1") -> dict:
    return {"sections": list(sections), "source_text_sha256": sha,
            "statutory_effective_from": None}


# ---------------------------------------------------------------- pure merge


def test_keeps_stored_section_when_bill_text_is_unchanged():
    fresh, stored = _payload(_missed()), _payload(_matched())

    merged, kept = preserve_stored_sections(
        fresh, stored, stored_as_of="2026-07-02T13:58:48+00:00")

    assert kept == 1
    section = merged["sections"][0]
    assert section["in_corpus"] is True
    assert section["current_text"] == "within 30 days after publication"
    assert section["diff"] == [{"op": "replace"}]
    assert section["corpus_stale"] is True
    assert section["corpus_text_as_of"] == "2026-07-02T13:58:48+00:00"
    # The official source still stands; the Axiom page no longer exists.
    assert section["source_url"].startswith("https://uscode.house.gov/")
    assert section["axiom_url"] is None


def test_never_mutates_its_inputs():
    fresh, stored = _payload(_missed()), _payload(_matched())
    fresh_before, stored_before = copy.deepcopy(fresh), copy.deepcopy(stored)

    preserve_stored_sections(fresh, stored, stored_as_of="2026-07-02")

    assert fresh == fresh_before
    assert stored == stored_before


def test_fresh_match_always_wins():
    """A section the corpus answered is never replaced by an older one."""
    fresh_section = _matched(current_text="within 45 days after publication")
    fresh, stored = _payload(fresh_section), _payload(_matched())

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0
    assert merged is fresh
    assert "corpus_stale" not in merged["sections"][0]


def test_stale_section_clears_once_corpus_answers_again():
    stale = _matched(corpus_stale=True, corpus_text_as_of="2026-07-02")
    fresh, stored = _payload(_matched()), _payload(stale)

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0
    assert "corpus_stale" not in merged["sections"][0]


def test_stored_miss_is_not_preserved():
    """A section that never matched (new law, bad citation) stays a miss."""
    fresh, stored = _payload(_missed()), _payload(_missed())

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0
    assert merged["sections"][0]["in_corpus"] is False


def test_changed_bill_text_with_changed_instruction_is_not_preserved():
    """The stored diff answers a different instruction: showing it would
    present an amendment the bill no longer makes."""
    changed = _missed(unapplied_ops=[{**OP, "payload": "90 days",
                                      "raw": "by striking “30 days” "
                                             "and inserting “90 days”"}])
    fresh = _payload(changed, sha="sha-2")
    stored = _payload(_matched(), sha="sha-1")

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0
    assert merged["sections"][0]["in_corpus"] is False


def test_changed_bill_text_with_same_instruction_is_preserved():
    """A re-fetch that changed another part of the bill leaves this
    section's instruction, and so its diff, intact."""
    fresh = _payload(_missed(), sha="sha-2")
    stored = _payload(_matched(), sha="sha-1")

    _, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 1


def test_missing_sha_falls_back_to_the_instructions():
    fresh = _payload(_missed(), sha=None)
    stored = _payload(_matched(), sha=None)

    _, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 1


def test_changed_text_and_no_parsed_ops_is_not_preserved():
    """With nothing to compare, 'same instruction' cannot be shown."""
    fresh = _payload(_missed(unapplied_ops=[]), sha="sha-2")
    stored = _payload(_matched(applied_ops=[]), sha="sha-1")

    _, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0


def test_repeated_citation_matches_by_position():
    first = _matched(current_text="first block")
    second = _matched(current_text="second block")
    fresh = _payload(_missed(), _missed())
    stored = _payload(first, second)

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 2
    assert [s["current_text"] for s in merged["sections"]] == [
        "first block", "second block"]


def test_repeated_citation_with_different_counts_is_ambiguous():
    """A parser change that re-splits the blocks leaves no safe pairing."""
    fresh = _payload(_missed(), _missed())
    stored = _payload(_matched())

    _, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 0


def test_only_the_missed_sections_are_replaced():
    ctc = _matched("26 USC 24(h)", citation_path="us/statute/26/24/h",
                   current_text="fresh CTC text")
    fresh = _payload(ctc, _missed())
    stored = _payload(
        _matched("26 USC 24(h)", current_text="old CTC text"), _matched())

    merged, kept = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert kept == 1
    assert merged["sections"][0]["current_text"] == "fresh CTC text"
    assert merged["sections"][1]["corpus_stale"] is True


def test_encoding_fields_come_from_the_fresh_run():
    """They derive from the rulespec index, not from corpus text."""
    encoding = {"repo": "rulespec-us", "kind": "statute", "citation": OSHA,
                "file_path": "statutes/29/655/b.yaml", "github_url": "u"}
    fresh = _payload(_missed(encoding=encoding, has_rulespec=True))
    stored = _payload(_matched(encoding=None, has_rulespec=False))

    merged, _ = preserve_stored_sections(fresh, stored, stored_as_of="x")

    assert merged["sections"][0]["encoding"] == encoding
    assert merged["sections"][0]["has_rulespec"] is True


def test_original_as_of_date_survives_later_runs():
    already_stale = _matched(corpus_stale=True,
                             corpus_text_as_of="2026-07-02T13:58:48+00:00",
                             axiom_url=None)
    fresh, stored = _payload(_missed()), _payload(already_stale)

    merged, kept = preserve_stored_sections(
        fresh, stored, stored_as_of="2026-09-20T00:00:00+00:00")

    assert kept == 1
    assert (merged["sections"][0]["corpus_text_as_of"]
            == "2026-07-02T13:58:48+00:00")


def test_empty_inputs_pass_through():
    fresh = _payload(_missed())
    assert preserve_stored_sections(fresh, None) == (fresh, 0)
    assert preserve_stored_sections(None, _payload(_matched())) == (None, 0)
    assert preserve_stored_sections(fresh, {"sections": []}) == (fresh, 0)


def test_has_corpus_miss():
    assert has_corpus_miss(_payload(_matched(), _missed())) is True
    assert has_corpus_miss(_payload(_matched())) is False
    assert has_corpus_miss(None) is False
    assert has_corpus_miss({"sections": []}) is False


def test_touch_flags_see_a_preserved_section():
    missed = touch_flags([_missed()])
    merged, _ = preserve_stored_sections(
        _payload(_missed()), _payload(_matched()), stored_as_of="x")

    assert missed == (False, False, False)
    assert touch_flags(merged["sections"]) == (True, False, False)


# ------------------------------------------------------------- hydrate-diffs


def _make_db(tmp_path, diffs: dict, migrations=SCHEMA_MIGRATIONS) -> str:
    path = tmp_path / "bills.sqlite"
    conn = sqlite3.connect(path)
    for name in migrations:
        conn.executescript((MIGRATIONS / name).read_text())
    conn.execute(
        "INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url)"
        " VALUES ('us', 'US', 'federal', 'https://example.gov')"
    )
    conn.execute(
        "INSERT INTO sessions (id, jurisdiction, name) VALUES ('s1', 'us', '119')"
    )
    conn.execute(
        """
        INSERT INTO bills (id, jurisdiction, session_id, chamber, number,
                           source_url, diffs)
        VALUES ('b1', 'us', 's1', 'lower', 'HR1', 'https://example.gov/hr1', ?)
        """,
        (json.dumps(diffs),),
    )
    conn.commit()
    conn.close()
    return str(path)


class _FakeClientCM:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


def _patch_remote(monkeypatch, stored: dict[str, dict]) -> list:
    """Patch every remote lookup; returns the list of requested id sets."""
    requested: list = []
    monkeypatch.setattr(supabase_sync, "_client", lambda: _FakeClientCM())
    monkeypatch.setattr(
        supabase_sync, "_remote_session_ids",
        lambda client, rows: (
            {r["id"]: f"remote-{r['id']}" for r in rows},
            {f"remote-{r['id']}" for r in rows},
        ),
    )
    monkeypatch.setattr(
        supabase_sync, "_remote_bill_ids",
        lambda client, rows, known_remote_sessions: {
            r["id"]: f"remote-{r['id']}" for r in rows
        },
    )

    def fake_stored(client, remote_bill_ids):
        ids = sorted(remote_bill_ids)
        requested.append(ids)
        return {i: stored[i] for i in ids if i in stored}

    monkeypatch.setattr(supabase_sync, "_stored_diffs_by_bill", fake_stored)
    return requested


def _local_bill(db_path: str) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM bills WHERE id = 'b1'").fetchone()
    finally:
        conn.close()


def test_hydrate_writes_preserved_section_and_flags(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path, _payload(_missed()))
    _patch_remote(monkeypatch, {"remote-b1": {
        "id": "remote-b1", "diffs": _payload(_matched()),
        "last_scraped_at": "2026-07-02T13:58:48+00:00",
    }})

    counts = supabase_sync.hydrate_stored_sections(db_path)

    assert counts == {"candidates": 1, "bills_hydrated": 1,
                      "sections_preserved": 1}
    bill = _local_bill(db_path)
    section = json.loads(bill["diffs"])["sections"][0]
    assert section["corpus_stale"] is True
    assert section["current_text"] == "within 30 days after publication"
    assert bill["touches_corpus"] == 1


def test_hydrate_skips_the_network_when_nothing_missed(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path, _payload(_matched()))
    requested = _patch_remote(monkeypatch, {})

    counts = supabase_sync.hydrate_stored_sections(db_path)

    assert counts == {"candidates": 0, "bills_hydrated": 0,
                      "sections_preserved": 0}
    assert requested == []


def test_hydrate_leaves_a_new_bill_alone(tmp_path, monkeypatch):
    """No remote row: the miss is all anyone knows about this section."""
    db_path = _make_db(tmp_path, _payload(_missed()))
    _patch_remote(monkeypatch, {})

    counts = supabase_sync.hydrate_stored_sections(db_path)

    assert counts["sections_preserved"] == 0
    section = json.loads(_local_bill(db_path)["diffs"])["sections"][0]
    assert section["in_corpus"] is False


def test_hydrate_tolerates_a_db_without_diffs(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript((MIGRATIONS / "001_init.sql").read_text())
    conn.close()
    _patch_remote(monkeypatch, {})

    assert supabase_sync.hydrate_stored_sections(str(path)) == {
        "candidates": 0, "bills_hydrated": 0, "sections_preserved": 0}


# ------------------------------------------------------ sync-supabase backstop


def test_sync_backstop_restores_section_and_flags(monkeypatch):
    monkeypatch.setattr(
        supabase_sync, "_stored_diffs_by_bill",
        lambda client, ids: {"remote-b1": {
            "id": "remote-b1", "diffs": _payload(_matched()),
            "last_scraped_at": "2026-07-02T13:58:48+00:00"}},
    )
    rows = [{"id": "remote-b1", "diffs": _payload(_missed()),
             "touches_corpus": False, "touches_rulespec": False,
             "needs_new_encoding": False}]

    kept = supabase_sync._preserve_into_rows(object(), rows)

    assert kept == 1
    assert rows[0]["diffs"]["sections"][0]["corpus_stale"] is True
    assert rows[0]["touches_corpus"] is True


def test_sync_backstop_does_not_add_flag_columns_it_was_not_given(monkeypatch):
    """A pre-057 local DB syncs without touch flags; keep it that way."""
    monkeypatch.setattr(
        supabase_sync, "_stored_diffs_by_bill",
        lambda client, ids: {"remote-b1": {
            "id": "remote-b1", "diffs": _payload(_matched()),
            "last_scraped_at": None}},
    )
    rows = [{"id": "remote-b1", "diffs": _payload(_missed())}]

    supabase_sync._preserve_into_rows(object(), rows)

    assert set(rows[0]) == {"id", "diffs"}


def test_sync_backstop_is_a_noop_after_hydration(monkeypatch):
    def fail(client, ids):
        raise AssertionError("no remote read expected")

    monkeypatch.setattr(supabase_sync, "_stored_diffs_by_bill", fail)
    rows = [{"id": "remote-b1", "diffs": _payload(_matched())},
            {"id": "remote-b2", "diffs": None}]

    assert supabase_sync._preserve_into_rows(object(), rows) == 0


def test_stored_diffs_fetch_is_chunked_and_skips_null_diffs(monkeypatch):
    calls: list[dict] = []

    def fake_select_all(client, table, params):
        calls.append(params)
        ids = params["id"][4:-1].split(",")
        return [{"id": i, "diffs": None if i == "b00" else {"sections": []},
                 "last_scraped_at": "t"} for i in ids]

    monkeypatch.setattr(supabase_sync, "_select_all", fake_select_all)
    ids = [f"b{n:02d}" for n in range(45)]

    stored = supabase_sync._stored_diffs_by_bill(object(), ids + ids[:3] + [""])

    assert len(calls) == 3                      # 45 unique ids, 20 per request
    assert all(c["select"] == "id,diffs,last_scraped_at" for c in calls)
    assert "b00" not in stored and len(stored) == 44
