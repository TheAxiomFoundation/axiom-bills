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


def test_tolerate_missing_table_skips_undefined_remote_relation(capsys) -> None:
    # The newer tables ship as manually-pasted supabase migrations; a
    # project that hasn't applied them yet must get a warning naming the
    # migration file, not a failed nightly sync.
    def step():
        raise RuntimeError(
            "Supabase write to encoding_graphs failed (404): "
            '{"code":"PGRST205","message":"Could not find the table '
            "'bills.encoding_graphs' in the schema cache\"}"
        )

    written = supabase_sync._tolerate_missing_table(
        step,
        table="encoding_graphs",
        migration="20260721000000_encoding_graphs.sql",
    )
    assert written == 0
    err = capsys.readouterr().err
    assert "encoding_graphs" in err
    assert "supabase/migrations/20260721000000_encoding_graphs.sql" in err


def test_tolerate_missing_table_reraises_other_errors() -> None:
    def step():
        raise RuntimeError("Supabase write to encode_queue failed (500): boom")

    with pytest.raises(RuntimeError, match="boom"):
        supabase_sync._tolerate_missing_table(
            step,
            table="encode_queue",
            migration="20260721130000_encode_queue.sql",
        )


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


def test_remote_rows_by_in_orders_by_filter_column_not_id(monkeypatch) -> None:
    # Regression: ordering child lookups by id.asc let Postgres walk the id PK
    # index filtering `bill_id in (...)` row-by-row, which grew into a 57014
    # statement timeout on bill_actions. The query must lead its order with the
    # filter column so the planner uses the index that already covers it,
    # falling back to id only as a stable-pagination tiebreak.
    seen: list[dict] = []

    class _FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return []  # empty page short-circuits pagination

    class _FakeClient:
        def get(self, path, params, headers):
            seen.append(params)
            return _FakeResp()

    supabase_sync._remote_rows_by_in(
        _FakeClient(),
        "bill_actions",
        select="id,bill_id,fingerprint",
        column="bill_id",
        values=["b1", "b2", "b3"],
    )

    assert seen, "expected at least one query"
    assert seen[0]["order"] == "bill_id.asc,id.asc"
