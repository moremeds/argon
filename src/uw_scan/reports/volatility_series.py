"""Orchestrator for /api/stock/{ticker}/volatility/series (spec 2026-05-13).

Reads raw IV/RV/skew/term/SPY data from repo, calls deriver functions, upserts
derived rows, and assembles a VolatilitySeriesResponse. Also exposes the
backfill routine that pulls UW source data on first request.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from typing import Any

import pandas as pd

from uw_scan.api.client import UwClient
from uw_scan.cards import vol_series
from uw_scan.models import (
    DivergencePoint,
    IvHistogramBin,
    IvHvPoint,
    IvOfIvPoint,
    IvPercentileDistribution,
    RegimeQuadrantBlock,
    RegimeQuadrantLatest,
    RegimeQuadrantPoint,
    RvCorrPoint,
    SmileExpiryCurve,
    SmilePoint,
    TermStructureExpiryRow,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VrpDailyPoint,
)
from uw_scan.reports.iv_smile_builder import build_iv_smile_snapshot_rows
from uw_scan.sources.uw import (
    fetch_greeks,
    fetch_realized_volatility,
    fetch_skew,
)
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


# ----------------------------- helpers --------------------------------------


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or not (-1e30 < v < 1e30)):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _build_header(repo: Repository, ticker: str) -> VolHeaderBlock:
    from uw_scan.reports.single_stock import build_volatility_profile, build_vrp

    run_id = repo.latest_run_id(ticker)
    vol = build_volatility_profile(repo, run_id, ticker)
    vrp_block = build_vrp(vol)
    return VolHeaderBlock(
        iv=vol.iv,
        rv=vol.rv,
        iv_rank=vol.iv_rank,
        iv_rank_1y=vol.iv_rank_1y,
        iv_low_52w=vol.iv_low_52w,
        iv_high_52w=vol.iv_high_52w,
        rv_low_52w=vol.rv_low_52w,
        rv_high_52w=vol.rv_high_52w,
        iv_percentile_30d=vol.iv_percentile_30d,
        implied_move_30d_perc=vol.implied_move_30d_perc,
        skew_25d=vol.skew_25d,
        vrp=vrp_block.vrp,
        vrp_signal=vrp_block.signal,
        vrp_note=vrp_block.note,
    )


def _build_iv_percentile_distribution(
    rv_history: list[dict], current_iv: Decimal | None
) -> IvPercentileDistribution:
    ivs = [
        float(r["implied_volatility"])
        for r in rv_history
        if r["implied_volatility"] is not None
    ]
    if not ivs:
        return IvPercentileDistribution()
    lo, hi = min(ivs), max(ivs)
    if lo == hi:
        return IvPercentileDistribution(
            bins=[IvHistogramBin(lo=_dec(lo), hi=_dec(hi), count=len(ivs))],
            current_iv=current_iv,
            current_pctile=Decimal("50"),
        )
    n_bins = 20
    step = (hi - lo) / n_bins
    bins: list[IvHistogramBin] = []
    for i in range(n_bins):
        b_lo = lo + step * i
        b_hi = lo + step * (i + 1)
        count = sum(
            1 for v in ivs if b_lo <= v < b_hi or (i == n_bins - 1 and v == b_hi)
        )
        bins.append(IvHistogramBin(lo=_dec(b_lo), hi=_dec(b_hi), count=count))
    pctile = None
    if current_iv is not None:
        cv = float(current_iv)
        rank = sum(1 for v in ivs if v < cv)
        pctile = Decimal(str(round(100 * rank / len(ivs), 1)))
    return IvPercentileDistribution(
        bins=bins, current_iv=current_iv, current_pctile=pctile
    )


def persist_vrp_daily(repo: Repository, ticker: str, df: pd.DataFrame) -> None:
    rows = [
        {
            "ticker": ticker,
            "market_date": r.market_date,
            "iv": _dec(r.iv),
            "rv": _dec(r.rv),
            "vrp": _dec(r.vrp),
            "vrp_z_20": _dec(r.vrp_z_20),
        }
        for r in df.itertuples()
        if not pd.isna(r.vrp)
    ]
    if rows:
        repo.upsert_vrp_daily_rows(rows)


def persist_stock_analytics(
    repo: Repository,
    ticker: str,
    iv_of_iv_df: pd.DataFrame,
    rvol_df: pd.DataFrame,
    corr_df: pd.DataFrame,
) -> None:
    by_date: dict[_date, dict] = {}
    for r in iv_of_iv_df.itertuples():
        by_date.setdefault(r.market_date, {})["iv_of_iv_20"] = _dec(r.iv_of_iv_20)
    for r in rvol_df.itertuples():
        d = by_date.setdefault(r.market_date, {})
        d["rvol_21"] = _dec(r.rvol_21)
        d["rvol_pctile"] = _dec(r.rvol_pctile)
    for r in corr_df.itertuples():
        by_date.setdefault(r.market_date, {})["spy_corr_21"] = _dec(r.spy_corr_21)
    rows = [
        {"ticker": ticker, "market_date": d, **vals}
        for d, vals in by_date.items()
        if any(v is not None for v in vals.values())
    ]
    if rows:
        repo.upsert_stock_analytics_rows(rows)


def _build_regime_quadrant(
    rvol_df: pd.DataFrame, corr_df: pd.DataFrame
) -> RegimeQuadrantBlock:
    if rvol_df.empty or corr_df.empty:
        return RegimeQuadrantBlock()
    merged = rvol_df.merge(corr_df, on="market_date", how="inner").dropna(
        subset=["rvol_pctile", "spy_corr_21"]
    )
    if merged.empty:
        return RegimeQuadrantBlock()
    points = [
        RegimeQuadrantPoint(
            date=r.market_date,
            rvol_pctile=_dec(r.rvol_pctile),
            spy_corr_21=_dec(r.spy_corr_21),
        )
        for r in merged.tail(20).itertuples()
    ]
    last = merged.iloc[-1]
    valid_corr = merged["spy_corr_21"].dropna()
    median = float(valid_corr.tail(252).median()) if len(valid_corr) >= 252 else None
    state = vol_series.classify_regime_state(
        rvol_pctile=float(last["rvol_pctile"]),
        spy_corr_21=float(last["spy_corr_21"]),
        median_corr=median,
    )
    return RegimeQuadrantBlock(
        points=points,
        latest=RegimeQuadrantLatest(
            date=last["market_date"],
            rvol_pctile=_dec(last["rvol_pctile"]),
            spy_corr_21=_dec(last["spy_corr_21"]),
            state=state,
        ),
    )


def _vrp_spread_headline(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    tail = df.tail(2)
    if len(tail) < 2:
        return ""
    curr = tail["vrp"].iloc[-1]
    prev = tail["vrp"].iloc[-2]
    if pd.isna(curr) or pd.isna(prev):
        return ""
    delta = curr - prev
    direction = "compressing" if abs(curr) < abs(prev) else "widening"
    return f"{curr:+.2f} pts | {direction} {delta:+.2f} pts"


def _divergence_headline(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    iv_z = df["iv_z"].iloc[-1]
    rv_z = df["rv_z"].iloc[-1]
    if pd.isna(iv_z) or pd.isna(rv_z):
        return ""
    return f"{(iv_z - rv_z):+.2f}σ"


def _build_term_structure(
    repo: Repository, ticker: str
) -> list[TermStructureExpiryRow]:
    smile_rows = repo.fetch_iv_smile_latest(ticker)
    if not smile_rows:
        return []
    rv_latest = repo.fetch_realized_vol_latest(ticker) or {}
    spot_val = _dec(rv_latest.get("price"))
    if spot_val is None:
        all_strikes = sorted({_dec(r["strike"]) for r in smile_rows if r.get("strike")})
        if not all_strikes:
            return []
        spot_val = all_strikes[len(all_strikes) // 2]

    by_expiry: dict[_date, list[dict]] = {}
    for r in smile_rows:
        by_expiry.setdefault(r["expiry"], []).append(r)

    today = _date.today()
    out: list[TermStructureExpiryRow] = []
    for expiry, rows in sorted(by_expiry.items()):
        rows.sort(key=lambda r: r["strike"])
        strikes = [r["strike"] for r in rows]
        atm_idx = min(
            range(len(strikes)),
            key=lambda i: abs(_dec(strikes[i]) - spot_val),
        )
        ladder: dict[str, Decimal] = {}
        for offset, label in ((-2, "ATM-2"), (-1, "ATM-1"), (0, "ATM"), (1, "ATM+1")):
            idx = atm_idx + offset
            if 0 <= idx < len(rows) and rows[idx].get("iv") is not None:
                ladder[label] = _dec(rows[idx]["iv"])
        dte = (expiry - today).days
        out.append(TermStructureExpiryRow(expiry=expiry, dte=dte, by_strike=ladder))
    return out


def _build_smile(repo: Repository, ticker: str) -> list[SmileExpiryCurve]:
    rows = repo.fetch_iv_smile_latest(ticker)
    if not rows:
        return []
    by_expiry: dict[_date, list[SmilePoint]] = {}
    for r in rows:
        by_expiry.setdefault(r["expiry"], []).append(
            SmilePoint(strike=r["strike"], iv=_dec(r["iv"]))
        )
    return [
        SmileExpiryCurve(expiry=ex, points=pts) for ex, pts in sorted(by_expiry.items())
    ]


# ----------------------------- entry points ---------------------------------


def assemble_volatility_series(
    *,
    ticker: str,
    repo: Repository,
    backfill_status: str = "ready",
) -> VolatilitySeriesResponse:
    """Read cached + derive on-the-fly; never hits UW. Side effect: persist
    derived series so subsequent calls are pure reads."""
    header = _build_header(repo, ticker)
    today = _date.today()

    rv_history = repo.fetch_realized_vol_history(ticker, days=365)
    spy_history = repo.fetch_index_ohlc_series("SPY")

    hv_iv = [
        IvHvPoint(
            date=r["market_date"],
            iv=_dec(r["implied_volatility"]),
            rv=_dec(r["realized_volatility"]),
        )
        for r in rv_history
    ]

    iv_pctile_dist = _build_iv_percentile_distribution(rv_history, header.iv)

    vrp_df = vol_series.compute_vrp_series(rv_history)
    iv_of_iv_df = vol_series.compute_iv_of_iv(rv_history)
    rvol_df = vol_series.compute_rvol_and_percentile(
        [{"market_date": r["market_date"], "price": r["price"]} for r in rv_history]
    )
    corr_df = vol_series.compute_stock_spy_corr(
        [{"market_date": r["market_date"], "price": r["price"]} for r in rv_history],
        spy_history,
    )
    z_df = vol_series.compute_iv_rv_z_overlay(rv_history)

    persist_vrp_daily(repo, ticker, vrp_df)
    persist_stock_analytics(repo, ticker, iv_of_iv_df, rvol_df, corr_df)
    repo.conn.commit()

    vrp_spread = [
        VrpDailyPoint(
            date=row.market_date,
            vrp=_dec(row.vrp),
            vrp_z_20=_dec(row.vrp_z_20),
        )
        for row in vrp_df.tail(30).itertuples()
    ]
    vrp_spread_headline = _vrp_spread_headline(vrp_df)

    iv_of_iv = [
        IvOfIvPoint(
            date=row.market_date,
            iv=_dec(row.iv),
            iv_of_iv_20=_dec(row.iv_of_iv_20),
        )
        for row in iv_of_iv_df.tail(90).itertuples()
    ]

    corr_by_date = {row.market_date: row.spy_corr_21 for row in corr_df.itertuples()}
    rv_corr = [
        RvCorrPoint(
            date=r["market_date"],
            rv=_dec(r["realized_volatility"]),
            spy_corr_21=_dec(corr_by_date.get(r["market_date"])),
        )
        for r in rv_history[-90:]
    ]

    quadrant = _build_regime_quadrant(rvol_df, corr_df)

    divergence = [
        DivergencePoint(
            date=row.market_date,
            iv_z=_dec(row.iv_z),
            rv_z=_dec(row.rv_z),
        )
        for row in z_df.tail(20).itertuples()
    ]
    divergence_headline = _divergence_headline(z_df)

    return VolatilitySeriesResponse(
        ticker=ticker,
        as_of=today,
        backfill_status=backfill_status,
        header=header,
        term_structure=_build_term_structure(repo, ticker),
        smile=_build_smile(repo, ticker),
        hv_iv_history=hv_iv,
        iv_percentile_distribution=iv_pctile_dist,
        iv_of_iv=iv_of_iv,
        rv_spy_corr=rv_corr,
        regime_quadrant=quadrant,
        divergence=divergence,
        divergence_headline=divergence_headline,
        vrp_spread=vrp_spread,
        vrp_spread_headline=vrp_spread_headline,
    )


def run_volatility_backfill(
    *,
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    nearest_expiries: list[str],
) -> str:
    """Pull historical UW data and (re)derive cached series. Idempotent.

    The UW source fetchers only normalize + write audit/payload rows;
    persistence of typed rows into history tables is the caller's
    responsibility (pipeline.py:61-113 pattern)."""
    try:
        rv_rows = fetch_realized_volatility(client, repo, run_id, ticker)
        if rv_rows:
            repo.upsert_realized_vol_rows(ticker, rv_rows)

        for ex in nearest_expiries[:2]:
            skew_rows = fetch_skew(client, repo, run_id, ticker, expiry=ex, delta=25)
            if skew_rows:
                repo.upsert_skew_rows(ticker, skew_rows)

        today = _date.today()
        smile_rows: list[dict] = []
        for ex in nearest_expiries[:4]:
            cached = repo.fetch_greeks_rows_for_smile(
                ticker=ticker,
                market_date=today,
                expiry=_date.fromisoformat(ex),
            )
            if cached:
                greeks_dicts = cached
            else:
                grs = fetch_greeks(client, repo, run_id, ticker, expiry=ex)
                if grs:
                    repo.insert_greeks_rows(run_id, ticker, grs)
                greeks_dicts = [g.model_dump() for g in grs]
            smile_rows.extend(
                build_iv_smile_snapshot_rows(
                    ticker=ticker, market_date=today, greeks_rows=greeks_dicts
                )
            )
        if smile_rows:
            repo.upsert_iv_smile_rows(smile_rows)

        repo.conn.commit()
        return "ready"
    except Exception:
        log.exception("volatility backfill failed for %s", ticker)
        return "failed"
