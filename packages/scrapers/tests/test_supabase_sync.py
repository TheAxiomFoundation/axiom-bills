from __future__ import annotations

from axiom_bills._common import supabase_sync


def test_remote_bill_ids_falls_back_to_unique_jurisdiction_match(monkeypatch) -> None:
    calls: list[str] = []

    def fake_remote_rows_by_in(client, table, *, select, column, values, chunk=100):
        calls.append(column)
        if column == "session_id":
            return []
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
    assert calls == ["session_id", "jurisdiction"]


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
