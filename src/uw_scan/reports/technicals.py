"""Assemble the Technicals tab response from the warm store (read-only)."""

from __future__ import annotations

from uw_scan.models import (
    ForwardReturnBandRow,
    TechnicalsHeader,
    TechnicalsResponse,
    TechnicalsSeriesRow,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.technicals_repository import TechnicalsRepository

# Metric keys the series row accepts (guards against a stray JSONB key breaking
# TechnicalsSeriesRow construction).
_METRIC_FIELDS = frozenset(
    {
        "rv20",
        "rv20_z",
        "vol_of_vol",
        "skew60",
        "kurt60",
        "jerk20",
        "rsi_z",
        "rsi_slope5",
        "macd_slope3",
        "kin_slope20",
        "kin_slope50",
        "kin_slope200",
        "alignment",
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
    }
)


def assemble_technicals(
    ticker: str, repo: Repository, *, schema: str = "uw_scan"
) -> TechnicalsResponse:
    t = ticker.upper()
    trepo = TechnicalsRepository(repo.conn, schema=schema)
    latest = trepo.fetch_latest(t)
    if latest is None:
        return TechnicalsResponse(ticker=t, backfill_status="empty")
    detail = latest.get("detail") or {}
    series = [
        TechnicalsSeriesRow(
            as_of=r["as_of"],
            close=r["close"],
            sma20=r["sma20"],
            sma50=r["sma50"],
            sma200=r["sma200"],
            z=r["z_vs_200dma"],
            rsi14=r["rsi14"],
            macd_hist_atr=r["macd_hist_atr"],
            rs_ratio=r["rs_ratio"],
            **{
                k: v for k, v in (r.get("metrics") or {}).items() if k in _METRIC_FIELDS
            },
        )
        for r in trepo.fetch_series(t)
    ]
    header = TechnicalsHeader(
        price=latest["close"],
        sma200=latest["sma200"],
        dist_pct=detail.get("dist_pct"),
        z=latest["z_vs_200dma"],
        z_band=latest["z_band"],
        slope_ann=latest["sma200_slope_ann"],
        slope_regime=latest["slope_regime"],
        composite=detail.get("composite"),
    )
    pctile = _macd_watchlist_pctile(trepo, t, latest["macd_hist_atr"])
    return TechnicalsResponse(
        ticker=t,
        backfill_status="ready",
        as_of=latest["as_of"],
        bars_n=latest.get("bars_n"),
        header=header,
        series=series,
        detail=detail or None,
        macd_watchlist_pctile=pctile,
        forward_returns=[
            ForwardReturnBandRow(**row) for row in (latest.get("forward_returns") or [])
        ],
    )


def _macd_watchlist_pctile(
    trepo: TechnicalsRepository, ticker: str, value: float | None
) -> float | None:
    """Cross-sectional percentile of this ticker's ATR-normalized MACD
    histogram among all tickers' latest rows (read-time, cheap)."""
    if value is None:
        return None
    peers = [
        r["macd_hist_atr"]
        for r in trepo.fetch_latest_macd_all()
        if r["macd_hist_atr"] is not None
    ]
    if len(peers) < 2:
        return None
    below = sum(1 for v in peers if v <= value)
    return below / len(peers)
