"""The read endpoint must not ask the assembler to persist derived series."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import BackgroundTasks

from uw_scan.api.routers import volatility as router_mod


class _Repo:
    """Fresh history, no persisted backfill row → status 'ready', no background task."""

    def count_realized_vol_history(self, _t, days):
        return days

    def get_volatility_backfill_status(self, _t):
        return None


def test_get_volatility_series_passes_persist_derived_false():
    captured: dict = {}

    def fake_assemble(**kwargs):
        captured.update(kwargs)
        return "sentinel"

    with patch.object(router_mod, "assemble_volatility_series", fake_assemble):
        result = router_mod.get_volatility_series(
            ticker="aapl", background_tasks=BackgroundTasks(), repo=_Repo()
        )
    assert result == "sentinel"
    assert captured["ticker"] == "AAPL"
    assert captured["backfill_status"] == "ready"
    assert captured["persist_derived"] is False
