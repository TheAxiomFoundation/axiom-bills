"""A diff section says when its current-law text came from the corpus.

`hydrate-diffs` dates kept text with that time. It has to be the corpus
fetch, not the run: a local SQLite caches corpus rows, so a later run can
reuse text it never re-checked.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from axiom_bills._common import corpus_client
from axiom_bills._common.corpus_client import CorpusProvision, _iso_utc, fetch
from axiom_bills._common.diff_precompute import _op_dict, _section_payload

MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"


def _db(tmp_path) -> str:
    path = tmp_path / "bills.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript((MIGRATIONS / "005_corpus_provisions.sql").read_text())
    conn.commit()
    conn.close()
    return str(path)


def _provision(**overrides) -> CorpusProvision:
    fields = dict(
        citation_path="us/statute/29/655", citation="", jurisdiction="us",
        doc_type="statute", heading="Standards", body="within 30 days",
        effective_date=None, source_url="https://example.gov", has_rulespec=False)
    fields.update(overrides)
    return CorpusProvision(**fields)


def test_iso_utc():
    assert _iso_utc("2026-07-02 13:58:48") == "2026-07-02T13:58:48+00:00"
    assert _iso_utc("2026-07-02T13:58:48+00:00") == "2026-07-02T13:58:48+00:00"
    assert _iso_utc(None) is None


def test_cache_hit_keeps_the_original_fetch_time(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO corpus_provisions (citation_path, citation, jurisdiction,"
        " doc_type, heading, body, effective_date, source_url, has_rulespec,"
        " fetched_at) VALUES ('us/statute/29/655', '29 USC 655', 'us',"
        " 'statute', 'Standards', 'within 30 days', NULL, 'u', 0,"
        " '2026-07-02 13:58:48')")
    conn.commit()
    conn.close()

    def no_network(path):
        raise AssertionError("a cache hit must not contact the corpus")

    monkeypatch.setattr(corpus_client, "_fetch_supabase", no_network)
    monkeypatch.setattr(corpus_client, "_MISS_CACHE", set())

    prov = fetch("29 USC 655", db_path=db_path)

    assert prov.fetched_at == "2026-07-02T13:58:48+00:00"


def test_live_fetch_is_stamped_now(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(corpus_client, "_fetch_supabase",
                        lambda path: _provision(citation_path=path))
    monkeypatch.setattr(corpus_client, "_MISS_CACHE", set())
    before = datetime.now(timezone.utc).replace(microsecond=0)

    prov = fetch("29 USC 655", db_path=db_path)

    assert datetime.fromisoformat(prov.fetched_at) >= before


def test_section_payload_carries_the_fetch_time():
    prov = _provision(fetched_at="2026-07-02T13:58:48+00:00")

    section = _section_payload(
        "29 USC 655", None, prov, before="a", after="a", applied=[],
        unapplied=[], block_warnings=[], block_raw="", sliced=False)

    assert section["corpus_fetched_at"] == "2026-07-02T13:58:48+00:00"


def test_op_dict_serializes_at_end():
    op = SimpleNamespace(kind="strike-insert", target="29 USC 655",
                         needle="x", payload="y", anchor="",
                         redesignate_to="", at_end=True, raw="r")

    assert _op_dict(op)["at_end"] is True
    assert _op_dict(SimpleNamespace(kind="strike"))["at_end"] is False
