"""Tests for corpus outage handling.

A corpus service error must never read as "not in corpus": recomputing
diffs with every section marked not-in-corpus and syncing that up would
erase good data. Errors raise CorpusUnavailable; only an empty result
is a miss.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from axiom_bills._common import corpus_client
from axiom_bills._common.corpus_client import CorpusUnavailable, fetch


MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(path)
    for name in ("001_init.sql", "005_corpus_provisions.sql"):
        conn.executescript((MIGRATIONS / name).read_text())
    conn.close()
    return path


@pytest.fixture(autouse=True)
def clear_miss_cache():
    corpus_client._MISS_CACHE.clear()
    yield
    corpus_client._MISS_CACHE.clear()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(corpus_client.time, "sleep", lambda s: None)


def test_network_error_raises_not_miss(monkeypatch, db_path):
    def boom(*a, **k):
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(corpus_client.httpx, "get", boom)
    with pytest.raises(CorpusUnavailable):
        fetch("26 USC 32", db_path=db_path)


def test_server_error_raises_after_retries(monkeypatch, db_path):
    calls = []
    def flaky(*a, **k):
        calls.append(1)
        return httpx.Response(503, text="upstream sad",
                              request=httpx.Request("GET", "http://x"))
    monkeypatch.setattr(corpus_client.httpx, "get", flaky)
    with pytest.raises(CorpusUnavailable):
        fetch("26 USC 32", db_path=db_path)
    assert len(calls) == 3  # retried before giving up


def test_transient_error_recovers(monkeypatch, db_path):
    responses = [
        httpx.Response(503, text="blip", request=httpx.Request("GET", "http://x")),
        httpx.Response(200, json=[{
            "citation_path": "us/statute/26/32", "jurisdiction": "us",
            "doc_type": "statute", "heading": "EITC", "body": "text",
            "effective_date": None, "source_url": None, "has_rulespec": True,
        }], request=httpx.Request("GET", "http://x")),
    ]
    monkeypatch.setattr(corpus_client.httpx, "get",
                        lambda *a, **k: responses.pop(0))
    prov = fetch("26 USC 32", db_path=db_path)
    assert prov is not None and prov.body == "text"


def test_empty_result_is_a_cached_miss(monkeypatch, db_path):
    calls = []
    def empty(*a, **k):
        calls.append(1)
        return httpx.Response(200, json=[],
                              request=httpx.Request("GET", "http://x"))
    monkeypatch.setattr(corpus_client.httpx, "get", empty)
    assert fetch("26 USC 32", db_path=db_path) is None
    n = len(calls)
    assert fetch("26 USC 32", db_path=db_path) is None
    assert len(calls) == n  # second lookup served from the miss cache
