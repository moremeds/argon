"""Lake syncs are heal adapters, not manual scripts (E5)."""

from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget


def test_vol_index_adapter_calls_the_production_sync(
    seeded_db_empty_cards, monkeypatch
) -> None:
    called: dict = {}

    def _fake_vol(conn, *, root):
        called["vol_root"] = str(root)
        return {"symbols": 3, "rows": 7, "gaps_filled": 7}

    def _fake_credit(conn, *, root, symbols):
        called["credit_root"] = str(root)
        called["symbols"] = list(symbols)
        return {"symbols": 3, "rows": 0, "gaps_filled": 0}

    monkeypatch.setattr(
        "uw_scan.worker.jobs.vol_index_lake_sync.run_vol_index_lake_sync", _fake_vol
    )
    monkeypatch.setattr(
        "uw_scan.worker.jobs.credit_etf_lake_sync.run_credit_etf_lake_sync",
        _fake_credit,
    )
    settings = Settings.from_env()
    ctx = HealContext(
        repo=seeded_db_empty_cards,
        gap=None,
        schema=seeded_db_empty_cards._schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )
    assert HEAL_SPECS["vol_index_lake"].run(ctx, 7) == 7
    # The two asset-class roots differ; the whole-lake root would be a bug.
    assert called["vol_root"] != called["credit_root"]
    assert called["symbols"] == list(settings.credit_etf_symbols)


def test_index_ohlc_adapter_widens_the_hardcoded_window(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """daily_spy_ohlc_refresh was pinned to today-2d, so it healed a same-day
    miss and nothing older."""
    seen: dict = {}
    monkeypatch.setattr(
        "uw_scan.worker.volatility_jobs.daily_spy_ohlc_refresh",
        lambda **kw: seen.update(kw),
    )
    settings = Settings.from_env().model_copy(update={"massive_api_key": None})
    ctx = HealContext(
        repo=seeded_db_empty_cards,
        gap=None,
        schema=seeded_db_empty_cards._schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )
    # No key -> loud RuntimeError, not a silent no-op recorded as a heal.
    try:
        HEAL_SPECS["index_ohlc"].run(ctx, 9)
    except RuntimeError as exc:
        assert "MASSIVE_API_KEY" in str(exc)
    else:  # pragma: no cover - only when a key IS configured locally
        assert seen["lookback_days"] == 9
