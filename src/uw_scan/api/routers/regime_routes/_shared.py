"""Private helpers shared by the /regime sub-routers."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vol_index_repository import VolIndexRepository

# Every regime sub-router logs under the pre-split module name.
logger = logging.getLogger("uw_scan.api.routers.regime")

# Tickers whose spot history is sourced from the parquet lake. UW
# /ohlc/1d is tier-blocked for indices; massive doesn't quote indices.
_SPOT_FROM_LAKE = {"SPX"}


def _is_market_open_now() -> bool:
    """Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _assemble_history(repo: Repository, ticker: str, days: int = 90) -> list[dict]:
    """Join greek_exposure_daily × (vol_index_daily | daily_ohlc) × gex_snapshots.

    The per-day gex_snapshots lookup carries flip + iv_30d + vol_pc + bias
    in one round-trip via ``fetch_metrics_history``. Days without a
    snapshot still surface (net_gex / net_dex / spot from the upstream
    tables); the snapshot-derived columns just come through as None so
    the table renders ``"---"`` per cell instead of dropping the row.

    Returned list is ASC by date — the SVG chart in HistoryChart.tsx
    consumes this directly with ``xScale(i)``, so flipping the order
    here would draw time right-to-left. The history table sorts
    client-side and defaults to date DESC.
    """
    g = GreekExposureDailyRepository(repo.conn, schema=repo.schema)
    gex_rows = g.fetch_history(ticker, days=days)
    if not gex_rows:
        return []

    if ticker in _SPOT_FROM_LAKE:
        v = VolIndexRepository(repo.conn, schema=repo.schema)
        spot_rows = v.fetch_history(ticker, days=days)
        spot_by_date = {r["trade_date"]: r["close"] for r in spot_rows}
    else:
        ohlc = repo.list_daily_ohlc(ticker, limit=days)
        spot_by_date = {r.date: float(r.close) for r in ohlc}

    metrics_by_date = repo.fetch_metrics_history(ticker=ticker, limit=days)

    return [
        {
            "date": row["trade_date"].isoformat(),
            "net_gex": row["net_gex"],
            "net_dex": row["net_dex"],
            "gex_flip": (metrics_by_date.get(row["trade_date"]) or {}).get("flip"),
            "spot": spot_by_date.get(row["trade_date"]),
            "atm_iv": (metrics_by_date.get(row["trade_date"]) or {}).get("iv_30d"),
            "vol_pc": (metrics_by_date.get(row["trade_date"]) or {}).get("vol_pc"),
            "bias": (metrics_by_date.get(row["trade_date"]) or {}).get("bias"),
        }
        for row in gex_rows
    ]


def _active_ws_source(repo: Repository) -> str | None:
    state = repo.get_ws_consumer_state()
    return state.active_source if state is not None else None


def _f(v: object) -> float | None:
    return float(v) if v is not None else None  # type: ignore[arg-type]
