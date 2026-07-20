"""Assemble the Technicals tab response from the warm store (read-only)."""

from __future__ import annotations

from uw_scan.cards.technicals import anchored_vwap
from uw_scan.models import (
    ForwardReturnBandRow,
    TechnicalsHeader,
    TechnicalsResponse,
    TechnicalsSeriesRow,
    TechnicalsVwapAnchor,
    VwapPoint,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.technical_vwap_anchor_repository import (
    TechnicalVwapAnchorRepository,
)
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
        "fast_macd_line_atr",
        "fast_macd_signal_atr",
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
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
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
    vwap_anchor = _load_vwap_anchor(t, repo, schema=schema, series=series)
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
        vwap_anchor=vwap_anchor,
    )


def _load_vwap_anchor(
    ticker: str,
    repo: Repository,
    *,
    schema: str,
    series: list[TechnicalsSeriesRow],
) -> TechnicalsVwapAnchor | None:
    row = TechnicalVwapAnchorRepository(repo.conn, schema=schema).get(ticker)
    if row is None:
        return None
    anchor = row["anchor_date"]
    # Recompute over the live series when OHLCV is present so the line extends
    # to the newest bar; fall back to the stored snapshot otherwise.
    rows = [
        {
            "as_of": r.as_of,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for r in series
    ]
    points = anchored_vwap(rows, anchor)
    if points:
        return TechnicalsVwapAnchor(
            anchor_date=anchor,
            series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in points],
        )
    snap = row["vwap_snapshot"] or []
    return TechnicalsVwapAnchor(
        anchor_date=anchor,
        series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in snap],
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
