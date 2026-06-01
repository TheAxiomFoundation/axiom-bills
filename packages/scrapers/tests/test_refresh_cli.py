from __future__ import annotations

from click.testing import CliRunner

from axiom_bills import cli
from axiom_bills._common import citation_writer, diff_precompute, supabase_sync


def test_refresh_defaults_to_production_jurisdictions(monkeypatch) -> None:
    scraped: list[tuple[str, int | None]] = []
    diffed: list[str | None] = []

    def fake_scrape(jurisdiction: str, limit: int | None, *args, **kwargs):
        scraped.append((jurisdiction, limit))
        return {"bills_seen": 1, "bills_new": 0, "actions_new": 0}

    def fake_precompute(*, jurisdiction: str | None = None):
        diffed.append(jurisdiction)
        return {"bills": 1, "with_sections": 1, "with_ops": 1}

    monkeypatch.setattr(cli, "_scrape_counts", fake_scrape)
    monkeypatch.setattr(diff_precompute, "precompute_all", fake_precompute)
    monkeypatch.setattr(
        citation_writer,
        "extract_for_jurisdiction",
        lambda *args, **kwargs: {
            "bills": 1,
            "summary_hits": 0,
            "text_hits": 0,
            "rows_written": 0,
        },
    )

    result = CliRunner().invoke(
        cli.main,
        [
            "refresh",
            "--limit", "7",
            "--skip-texts",
            "--skip-corpus",
            "--skip-variants",
            "--skip-llm",
        ],
    )

    assert result.exit_code == 0, result.output
    assert scraped == [("us", 7), ("us-ny", 7), ("us-co", 7), ("us-mn", 7)]
    assert diffed == ["us", "us-ny", "us-co", "us-mn"]
    assert "Refreshing jurisdictions: us, us-ny, us-co, us-mn" in result.output


def test_refresh_syncs_when_requested(monkeypatch) -> None:
    synced: list[str] = []

    monkeypatch.setattr(
        cli,
        "_scrape_counts",
        lambda *args, **kwargs: {
            "bills_seen": 1,
            "bills_new": 0,
            "actions_new": 0,
        },
    )
    monkeypatch.setattr(
        diff_precompute,
        "precompute_all",
        lambda *, jurisdiction=None: {
            "bills": 1,
            "with_sections": 0,
            "with_ops": 0,
        },
    )
    monkeypatch.setattr(
        citation_writer,
        "extract_for_jurisdiction",
        lambda *args, **kwargs: {
            "bills": 1,
            "summary_hits": 0,
            "text_hits": 0,
            "rows_written": 0,
        },
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync",
        lambda db_path: synced.append(db_path) or {"bills": 1},
    )

    result = CliRunner().invoke(
        cli.main,
        [
            "refresh",
            "-j", "us",
            "--skip-texts",
            "--skip-corpus",
            "--skip-variants",
            "--skip-llm",
            "--sync",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(synced) == 1
    assert "== sync supabase ==" in result.output
    assert "bills=1" in result.output
