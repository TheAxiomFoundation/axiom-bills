from __future__ import annotations

from axiom_bills.cli import _parse_since_cursor


def test_parse_since_cursor_normalizes_aware_timestamp_to_local_naive() -> None:
    parsed = _parse_since_cursor("2026-05-18T20:32:53+00:00")

    assert parsed.isoformat() == "2026-05-18T16:32:53"
    assert parsed.tzinfo is None


def test_parse_since_cursor_accepts_naive_timestamp() -> None:
    parsed = _parse_since_cursor("2026-05-18T16:32:53")

    assert parsed.isoformat() == "2026-05-18T16:32:53"
    assert parsed.tzinfo is None
