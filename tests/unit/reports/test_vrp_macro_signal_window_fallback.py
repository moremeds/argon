"""The bounded signal load must fall back to full history when the window is
too thin (stale or holey vol_index_daily); otherwise the bound would raise or
silently zero the size weight where the full load produced a signal."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from uw_scan.reports import vrp_macro_signal as mod


def _fake_loader(n_in_window: int, n_full: int):
    calls: list = []

    def load(repo, name, *, lake_root=None, since=None, **_kw):
        calls.append(since)
        n = n_in_window if since is not None else n_full
        rows = [{"market_date": date(2020, 1, 1) + timedelta(days=i)} for i in range(n)]
        return SimpleNamespace(rows=rows, adj=[], pidx={}, events=[])

    return load, calls


def test_thin_window_falls_back_to_full_history(monkeypatch):
    load, calls = _fake_loader(n_in_window=0, n_full=5000)
    monkeypatch.setattr(mod, "load_index_vol", load)
    loaded = mod._load_signal_window(None, "SPX", as_of=None, lake_root=None)
    assert len(loaded.rows) == 5000
    assert calls[0] is not None and calls[1] is None  # bounded first, then full


def test_sufficient_window_is_not_reloaded(monkeypatch):
    load, calls = _fake_loader(n_in_window=mod._MIN_WINDOW_ROWS, n_full=5000)
    monkeypatch.setattr(mod, "load_index_vol", load)
    loaded = mod._load_signal_window(
        None, "SPX", as_of=date(2026, 9, 18), lake_root=None
    )
    assert len(loaded.rows) == mod._MIN_WINDOW_ROWS
    assert calls == [date(2026, 9, 18) - timedelta(days=mod.SIGNAL_LOOKBACK_DAYS)]
