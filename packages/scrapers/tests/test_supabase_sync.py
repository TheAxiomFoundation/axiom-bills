from __future__ import annotations

import httpx
import pytest

from axiom_bills._common import supabase_sync


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_send_with_retry_retries_timeout_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(supabase_sync.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadTimeout("timed out")
        return _Resp(200)

    resp = supabase_sync._send_with_retry(send, what="write bills", base_delay=0)
    assert resp.status_code == 200
    assert calls["n"] == 3


def test_send_with_retry_retries_transient_5xx(monkeypatch) -> None:
    monkeypatch.setattr(supabase_sync.time, "sleep", lambda _s: None)
    codes = iter([503, 504, 200])

    resp = supabase_sync._send_with_retry(
        lambda: _Resp(next(codes)), what="write bills", base_delay=0
    )
    assert resp.status_code == 200


def test_send_with_retry_gives_up_and_raises(monkeypatch) -> None:
    monkeypatch.setattr(supabase_sync.time, "sleep", lambda _s: None)

    def send():
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(httpx.ReadTimeout):
        supabase_sync._send_with_retry(send, what="write bills", attempts=3, base_delay=0)


def test_send_with_retry_does_not_retry_4xx(monkeypatch) -> None:
    monkeypatch.setattr(supabase_sync.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return _Resp(400)

    resp = supabase_sync._send_with_retry(send, what="write bills", base_delay=0)
    assert resp.status_code == 400
    assert calls["n"] == 1  # 400 is a real error, fail fast


def test_remote_bill_ids_looks_up_by_jurisdiction_only(monkeypatch) -> None:
    # Must query by the indexed `jurisdiction` column, never the unindexed
    # `session_id` (which seq-scanned and timed out as the table grew).
    calls: list[str] = []

    def fake_remote_rows_by_in(client, table, *, select, column, values, chunk=100):
        calls.append(column)
        return [
            {
                "id": "remote-bill-id",
                "jurisdiction": "us-ok",
                "session_id": "remote-session-id",
                "chamber": "joint",
                "number": "HCR 1001",
            }
        ]

    monkeypatch.setattr(supabase_sync, "_remote_rows_by_in", fake_remote_rows_by_in)

    rows = [
        {
            "id": "local-bill-id",
            "jurisdiction": "us-ok",
            "session_id": "remote-session-id",
            "chamber": "joint",
            "number": "HCR 1001",
        }
    ]

    assert supabase_sync._remote_bill_ids(object(), rows) == {
        "local-bill-id": "remote-bill-id"
    }
    assert calls == ["jurisdiction"]  # single, indexed lookup


def test_remote_bill_ids_falls_back_on_session_rekey(monkeypatch) -> None:
    # Remote session_id differs from local — exact key misses, so fall back to
    # the unambiguous (jurisdiction, chamber, number) match.
    def fake_remote_rows_by_in(client, table, *, select, column, values, chunk=100):
        return [
            {
                "id": "remote-bill-id",
                "jurisdiction": "us-ok",
                "session_id": "remote-session-NEW",
                "chamber": "joint",
                "number": "HCR 1001",
            }
        ]

    monkeypatch.setattr(supabase_sync, "_remote_rows_by_in", fake_remote_rows_by_in)

    rows = [
        {
            "id": "local-bill-id",
            "jurisdiction": "us-ok",
            "session_id": "local-session-OLD",
            "chamber": "joint",
            "number": "HCR 1001",
        }
    ]

    assert supabase_sync._remote_bill_ids(object(), rows) == {
        "local-bill-id": "remote-bill-id"
    }


def test_remote_bill_ids_does_not_fall_back_to_ambiguous_bill_number(monkeypatch) -> None:
    def fake_remote_rows_by_in(client, table, *, select, column, values, chunk=100):
        if column == "session_id":
            return []
        return [
            {
                "id": "remote-bill-id-1",
                "jurisdiction": "us-ok",
                "session_id": "remote-session-id-1",
                "chamber": "joint",
                "number": "HCR 1001",
            },
            {
                "id": "remote-bill-id-2",
                "jurisdiction": "us-ok",
                "session_id": "remote-session-id-2",
                "chamber": "joint",
                "number": "HCR 1001",
            },
        ]

    monkeypatch.setattr(supabase_sync, "_remote_rows_by_in", fake_remote_rows_by_in)

    rows = [
        {
            "id": "local-bill-id",
            "jurisdiction": "us-ok",
            "session_id": "remote-session-id",
            "chamber": "joint",
            "number": "HCR 1001",
        }
    ]

    assert supabase_sync._remote_bill_ids(object(), rows) == {
        "local-bill-id": "local-bill-id"
    }
