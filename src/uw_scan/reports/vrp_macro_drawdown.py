"""Decisive drawdown test — does the macro short-vol edge survive a selloff?

The 11-month `vrp_daily` sweep flattered the bullish bull-put-spread because the
window was a rising market. This re-runs the structures on ~20 years of **SPX + VIX**
(VIX/100 = SPX 30-day implied vol; an index → no corp actions, no earnings), so
2008, 2018-Q4, 2020 and 2022 are in-sample. Trades are entry-spaced and bucketed by
year so a stress year that blows the strategy up is visible, not averaged away.

IV-term-structure caveat: VIX is a constant-maturity 30d IV; we apply it across all
horizons, so **hold ≈ 20d is the cleanest read** (5d/45d are rougher proxies).
"""

from __future__ import annotations

import math
import os
import pathlib
from collections import defaultdict
from datetime import date as _date
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_macro_harvest import _backtest, _Loaded, _summarize
from uw_scan.reports.vrp_structure import CostModel

# Calendar years that contained a material equity drawdown / vol spike.
STRESS_YEARS = {2008, 2009, 2011, 2015, 2018, 2020, 2022}

# Per-index: implied-vol proxy + spot source. SPX/VIX live in vol_index_daily;
# QQQ/IWM spot come from the lake equity bars, paired with VXN/RVX (start 2009).
INDEX_SPECS: dict[str, dict] = {
    "SPX": {
        "vol": "VIX",
        "spot_source": "vol_index",
        "spot_symbol": "SPX",
        "start": _date(2006, 1, 1),
    },
    "QQQ": {
        "vol": "VXN",
        "spot_source": "lake",
        "spot_symbol": "QQQ",
        "start": _date(2009, 1, 1),
    },
    "IWM": {
        "vol": "RVX",
        "spot_source": "lake",
        "spot_symbol": "IWM",
        "start": _date(2009, 1, 1),
    },
    # RUT (the actual Russell 2000 index) lives in the lake's volatility dir, not
    # the equity dir and not vol_index_daily. Paired with RVX (from 2009-09).
    "RUT": {
        "vol": "RVX",
        "spot_source": "volatility_lake",
        "spot_symbol": "RUT",
        "start": _date(2009, 1, 1),
    },
    "SPY": {
        "vol": "VIX",
        "spot_source": "lake",
        "spot_symbol": "SPY",
        "start": _date(2006, 1, 1),
    },
}


def _default_lake_root() -> pathlib.Path:
    # Path defaults live in config.py so there is exactly one home-dir fallback
    # in the codebase (enforced by scripts/check_runtime_assets.py). Read the
    # FIELD DEFAULT, not Settings.from_env(): from_env() requires
    # UW_SCAN_API_KEY and raises without it (config.py), which would turn a
    # path lookup into a hard dependency on a credential this function has no
    # business needing — and would fail outright in the unit CI job.
    from uw_scan.config import Settings  # noqa: PLC0415

    env = os.environ.get("MARKET_WAREHOUSE_LAKE", "").strip()
    if env:
        return pathlib.Path(env)
    return pathlib.Path(Settings.model_fields["market_warehouse_lake_root"].default)


def _vol_index_close(repo, symbol: str, start: _date) -> dict[_date, float]:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, close::float8 FROM uw_scan.vol_index_daily "
            "WHERE symbol = %s AND trade_date >= %s ORDER BY trade_date",
            (symbol, start),
        )
        return {td: c for td, c in cur.fetchall()}


def _lake_spot(
    symbol: str, lake_root: pathlib.Path, start: _date
) -> dict[_date, float]:
    """Reads the explicit 1d.parquet — pointing pyarrow at the symbol
    directory instead picks up sibling files (1d.parquet.lock, 30m/5m
    parquet + their .lock markers) and breaks on the zero-byte lock file
    (same class of bug as _volatility_lake_close below)."""
    import pyarrow.parquet as pq

    path = (
        lake_root / "bronze" / "asset_class=equity" / f"symbol={symbol}" / "1d.parquet"
    )
    table = pq.read_table(str(path), columns=["trade_date", "close"])
    dts = table.column("trade_date").to_pylist()
    cls = table.column("close").to_pylist()
    # SPY's lake parquet carries ~73% null-trade_date rows (an alternate-schema
    # partition mixed in); the non-null rows are the clean daily series. Guard
    # `d is not None` so those junk rows are skipped — a no-op for symbols whose
    # lake data has no null dates (QQQ/IWM).
    return {
        d: float(c)
        for d, c in zip(dts, cls, strict=False)
        if c is not None and d is not None and d >= start
    }


def _volatility_lake_close(
    symbol: str, lake_root: pathlib.Path, start: _date
) -> dict[_date, float]:
    """Close series from the lake's volatility dir (RUT/RVX/SPX index levels).
    Reads the explicit 1d.parquet — the dir carries a .meta.json sidecar that
    breaks pyarrow's directory-dataset reader."""
    import pyarrow.parquet as pq

    path = (
        lake_root
        / "bronze"
        / "asset_class=volatility"
        / f"symbol={symbol}"
        / "1d.parquet"
    )
    table = pq.read_table(str(path), columns=["trade_date", "close"])
    dts = table.column("trade_date").to_pylist()
    cls = table.column("close").to_pylist()
    return {
        d: float(c)
        for d, c in zip(dts, cls, strict=False)
        if c is not None and d is not None and d >= start
    }


def _build_loaded(
    spot: dict[_date, float],
    vol: dict[_date, float],
    *,
    rv_window: int,
    z_window: int,
) -> _Loaded:
    """spot close = underlying, vol close / 100 = IV; realized vol from trailing spot
    log-returns; VRP = IV − RV z-scored over a trailing window."""
    dates = sorted(set(spot) & set(vol))
    adj = [(d, spot[d]) for d in dates]
    pidx = {d: k for k, d in enumerate(dates)}
    logret = [
        math.log(spot[dates[i]] / spot[dates[i - 1]]) for i in range(1, len(dates))
    ]
    rows: list[dict[str, Any]] = []
    vrp_hist: list[float] = []
    for i, d in enumerate(dates):
        iv = vol[d] / 100.0
        rv = None
        if i >= rv_window:
            window = logret[i - rv_window : i]  # rv_window returns ending at day i
            rv = pstdev(window) * math.sqrt(252) if len(window) > 1 else None
        vrp = (iv - rv) if rv is not None else None
        z = None
        if vrp is not None:
            vrp_hist.append(vrp)
            if len(vrp_hist) >= z_window:
                w = vrp_hist[-z_window:]
                sd = pstdev(w)
                z = (vrp - fmean(w)) / sd if sd > 0 else None
        rows.append({"market_date": d, "iv": iv, "rv": rv, "vrp": vrp, "vrp_z_20": z})
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def load_index_vol(
    repo,
    name: str,
    *,
    lake_root: pathlib.Path | None = None,
    rv_window: int = 20,
    z_window: int = 252,
) -> _Loaded:
    """Build a `_Loaded` for an index from its IV proxy + spot source (INDEX_SPECS)."""
    spec = INDEX_SPECS[name]
    start = spec["start"]
    vol = _vol_index_close(repo, spec["vol"], start)
    if spec["spot_source"] == "vol_index":
        spot = _vol_index_close(repo, spec["spot_symbol"], start)
    elif spec["spot_source"] == "volatility_lake":
        spot = _volatility_lake_close(
            spec["spot_symbol"], lake_root or _default_lake_root(), start
        )
    else:
        spot = _lake_spot(spec["spot_symbol"], lake_root or _default_lake_root(), start)
    return _build_loaded(spot, vol, rv_window=rv_window, z_window=z_window)


def load_spx_vix(
    repo, *, rv_window: int = 20, z_window: int = 252, start: _date = _date(2006, 1, 1)
) -> _Loaded:
    """Back-compat SPX+VIX loader (vol_index_daily)."""
    vol = _vol_index_close(repo, "VIX", start)
    spot = _vol_index_close(repo, "SPX", start)
    return _build_loaded(spot, vol, rv_window=rv_window, z_window=z_window)


def run_index_drawdown(
    *,
    repo,
    settings,
    name: str = "SPX",
    structure: str = "bull_put_spread",
    short_delta: float = 0.25,
    hold_days: int = 20,
    gate: float | None = None,  # None = always-on
    profit_take: float
    | None = None,  # None = hold to expiry; e.g. 0.5 = close at 50% credit
    lake_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Run one config over an index's full history; return overall + per-year P&L,
    max-drawdown of the cumulative return-on-risk curve, and the trade list."""
    loaded = load_index_vol(repo, name, lake_root=lake_root)
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    trades = _backtest(
        loaded,
        name,
        kind=structure,
        min_z=gate,
        short_delta=short_delta,
        hold_days=hold_days,
        r=settings.vrp_risk_free_rate,
        cost=cost,
        profit_take=profit_take,
    )
    by_year: dict[int, list] = defaultdict(list)
    for t in trades:
        by_year[t.entry_date.year].append(t)

    def _year_row(yr: int, ts: list) -> dict[str, Any]:
        n = len(ts)
        wins = sum(1 for t in ts if t.net_pnl > 0)
        return {
            "year": yr,
            "stress": yr in STRESS_YEARS,
            "n": n,
            "win_rate": wins / n if n else None,
            "total_ror": sum(t.return_on_risk for t in ts),  # scale-invariant P&L
            "mean_ror": sum(t.return_on_risk for t in ts) / n if n else None,
            "breach_rate": sum(1 for t in ts if t.breached) / n if n else None,
            "worst_ror": min((t.return_on_risk for t in ts), default=None),
        }

    years = [_year_row(y, by_year[y]) for y in sorted(by_year)]
    # max drawdown of the cumulative return-on-risk curve (chronological)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.expiry_date):
        cum += t.return_on_risk
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return {
        "name": name,
        "structure": structure,
        "short_delta": short_delta,
        "hold_days": hold_days,
        "gate": "always_on" if gate is None else f"z>={gate}",
        "profit_take": profit_take,
        "overall": _summarize(trades, scope="full"),
        "holdout": _summarize(trades, scope="holdout"),
        "years": years,
        "stress_total_ror": sum(r["total_ror"] for r in years if r["stress"]),
        "calm_total_ror": sum(r["total_ror"] for r in years if not r["stress"]),
        "max_drawdown_ror": max_dd,
        "trades": trades,
        "span": (loaded.adj[0][0].isoformat(), loaded.adj[-1][0].isoformat()),
    }


def run_spx_vix_drawdown(**kwargs) -> dict[str, Any]:
    """Back-compat wrapper — SPX+VIX drawdown (see run_index_drawdown)."""
    kwargs.pop("name", None)
    return run_index_drawdown(name="SPX", **kwargs)
