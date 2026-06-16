"""Skew First-Principles assembler.

Reads persisted raw series via the repo, calls the pure derivers in
cards/skew_first_principles.py, stitches a SkewAnalysisResponse, and persists
the per-day snapshot (standing 'persist analytical results' rule).
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from uw_scan.cards import skew_first_principles as sk
from uw_scan.models import (
    SkewAnalysisResponse,
    SkewDirectionalLean,
    SkewExpiryPoint,
    SkewHistoryPoint,
    SkewRead,
    SkewReadBullet,
    SkewRhoPoint,
    SkewSmileExpiryCurve,
    SkewSmilePoint,
    SkewStructureDetail,
    SkewStructureLeg,
)
from uw_scan.scanner.gates import earnings_gate as _earnings_gate
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or not (-1e30 < v < 1e30)):
        return None
    try:
        return Decimal(str(v))
    except Exception as exc:  # noqa: BLE001
        log.debug("decimal coercion skipped for %r: %s", v, repr(exc))
        return None


def _to_structure_detail(d: dict | None) -> SkewStructureDetail | None:
    if not d:
        return None
    return SkewStructureDetail(
        kind=d.get("kind", ""),
        dte_target=d.get("dte_target"),
        status=d.get("status", "ready"),
        note=d.get("note", ""),
        legs=[
            SkewStructureLeg(
                action=g.get("action", ""),
                right=g.get("right", ""),
                strike=_dec(g.get("strike")),
                target_delta=_dec(g.get("target_delta")),
                actual_delta=_dec(g.get("actual_delta")),
                expiry=g.get("expiry"),
                dte=g.get("dte"),
            )
            for g in d.get("legs", [])
        ],
    )


def _price_trend(rv_series: list[dict], *, window: int = 20) -> float | None:
    px = pd.to_numeric(pd.DataFrame(rv_series).get("price"), errors="coerce").dropna()
    if len(px) < window + 1:
        return None
    prev = float(px.iloc[-window - 1])
    if prev == 0:
        return None
    return float(px.iloc[-1]) / prev - 1.0


def build_skew_snapshot_row(
    *,
    ticker: str,
    market_date: _date,
    rr_series: list[dict],
    expiry_rows: list[dict],
    rv_series: list[dict],
    spy_rv_series: list[dict],
    positioning: dict | None,
    next_earnings_date: _date | None,
    verdict: dict | None,
    sector: str | None,
    today: _date,
    exposure_rows: list[dict] | None = None,
    regime: str | None = None,
) -> dict:
    """Pure stitch: raw series + verdict in, snapshot column dict out. No I/O.

    `regime` is the canonical market regime tag (latest CRI level, supplied by the
    caller). When None, fall back to the self-contained SPY-RV label. Regime is a
    display/context tag only — it left the verdict bucket key in migration 076."""
    rr_vals = [r.get("risk_reversal") for r in rr_series]
    rr_floats = [float(x) for x in rr_vals if x is not None]
    base = sk.compute_skew_baseline(rr_vals)
    rr_25d = rr_floats[-1] if rr_floats else None
    deviation = sk.classify_deviation(base["z"], base["pct"])

    # term structure (front = nearest expiry, back = furthest); degrade to flat
    front_rr = back_rr = None
    if expiry_rows:
        ordered = sorted(expiry_rows, key=lambda r: r.get("expiry") or _date.max)
        front_rr = ordered[0].get("risk_reversal")
        if len(ordered) >= 2:
            back_rr = ordered[-1].get("risk_reversal")
    term_class = sk.classify_skew_term(front_rr, back_rr)

    rho63 = sk.compute_spot_vol_rho(rv_series, window=63)
    rho21 = sk.compute_spot_vol_rho(rv_series, window=21)
    rho_sign = 0 if rho63 is None else (1 if rho63 > 0 else (-1 if rho63 < 0 else 0))
    trend = _price_trend(rv_series)
    drive = sk.classify_drive(trend, rho63)

    cls = sk.asset_class_baseline(ticker, sector=sector)
    pos = positioning or {}
    bflag = sk.borrow_flag(pos.get("si_fee_rate"), pos.get("si_days_to_cover"))
    # None earnings => "unknown" (not "block"): the scanner gate returns "block"
    # for None, but unknown earnings is not positive evidence of an active window.
    # Only a confirmed imminent window ("block") suppresses the lean (see resolve).
    egate = (
        "unknown"
        if next_earnings_date is None
        else _earnings_gate(next_earnings_date=next_earnings_date, today=today)
    )
    regime = regime if regime else sk.classify_market_regime(spy_rv_series)

    lean = sk.resolve_directional_lean(
        deviation_class=deviation,
        drive_class=drive,
        asset_class=cls["asset_class"],
        regime=regime,
        borrow_flag=bflag,
        earnings_gate=egate,
        verdict=verdict,
    )
    # Concrete strike-by-delta detail — ONLY when the lean is already gated non-neutral
    # (Phase-2 increment-1). Suppressed during an earnings block. Index ETFs are
    # included: their directional lean is research-validated (index_macro verdict
    # buckets), so they earn the same defined-risk expression as single-names. The
    # mean-reversion *trigger* is the only surface that skips indices (index skew is
    # structural and does not revert). Renders only when a swing chain exists.
    fam = sk.structure_family(lean)
    if fam is not None and egate != "block" and exposure_rows:
        earn_note = (
            f"exit before earnings {next_earnings_date.isoformat()}"
            if next_earnings_date is not None
            else "swing hold; exit before next earnings"
        )
        lean["structure_detail"] = sk.select_structure_legs(
            family=fam, exposure_rows=exposure_rows, earnings_note=earn_note
        )
    else:
        lean["structure_detail"] = None
    tail = sk.skew_sign_label(rr_25d)
    rho_confirms = (deviation == "RICH" and rho_sign < 0) or (
        deviation == "CHEAP" and rho_sign > 0
    )
    read = sk.build_read(
        tail=tail,
        rho=rho63,
        rho_confirms=rho_confirms,
        drive_class=drive,
        deviation_class=deviation,
        asset_class=cls["asset_class"],
        class_expected_sign=cls["expected_sign"],
        borrow_flag=bflag,
        earnings_gate=egate,
        directional_lean=lean,
    )
    spot = rv_series[-1].get("price") if rv_series else None

    return {
        "ticker": ticker.upper(),
        "market_date": market_date,
        "basis": "eod",
        "spot": _dec(spot),
        "rr_25d": _dec(rr_25d),
        "skew_25d": _dec(rr_25d),
        "rr_z_180d": _dec(base["z"]),
        "rr_pct_252d": _dec(base["pct"]),
        "deviation_class": deviation,
        "skew_term_class": term_class,
        "front_rr": _dec(front_rr),
        "back_rr": _dec(back_rr),
        "rho_spotvol_63d": _dec(rho63),
        "rho_spotvol_21d": _dec(rho21),
        "rho_sign": rho_sign,
        "drive_class": drive,
        "asset_class": cls["asset_class"],
        "class_expected_sign": cls["expected_sign"],
        "borrow_flag": bflag,
        "borrow_fee_rate": _dec(pos.get("si_fee_rate")),
        "days_to_cover": _dec(pos.get("si_days_to_cover")),
        "earnings_gate": egate,
        "regime": regime,
        "directional_lean": lean["lean"],
        "lean_confidence": lean["confidence"],
        "lean_basis": lean["basis"],
        "read_summary": read["summary_line"],
        "read_json": read,
    }


def _read_series_for_ticker(repo: Repository, ticker: str, today: _date) -> dict:
    """All repo reads needed to build the latest snapshot + response series."""
    rr_series = repo.fetch_matrix_skew_history(
        ticker=ticker, market_date=today, days=400
    )
    rv_series = repo.fetch_realized_vol_history(ticker, days=400)
    spy_rv = repo.fetch_realized_vol_history("SPY", days=400)
    latest_rr_date = rr_series[-1]["market_date"] if rr_series else today
    expiry_rows = repo.fetch_matrix_skew_expiry_rows(
        ticker=ticker, market_date=latest_rr_date
    )
    positioning = repo.get_uw_positioning(ticker)
    next_er = repo.fetch_latest_next_earnings_date(ticker)
    return {
        "rr_series": rr_series,
        "rv_series": rv_series,
        "spy_rv": spy_rv,
        "latest_rr_date": latest_rr_date,
        "expiry_rows": expiry_rows,
        "positioning": positioning,
        "next_er": next_er,
    }


def _history_points(rr_hist: list[dict]) -> list[SkewHistoryPoint]:
    """O(n) expanding z (vs trailing 180) + percentile (vs trailing 252) over the
    non-null RR series. Vectorised rolling — replaces the prior O(n^2) per-point
    Series rebuild; matches cards.compute_skew_baseline pointwise on dense data.
    (Also fixes a latent misalignment: the old loop sliced the filtered float list
    with the *unfiltered* rr_hist index, wrong whenever an RR value was null.)"""
    pts = [
        (r["market_date"], float(r["risk_reversal"]))
        for r in rr_hist
        if r.get("risk_reversal") is not None
    ]
    if not pts:
        return []
    s = pd.Series([v for _, v in pts], dtype="float64")
    rmean = s.rolling(180, min_periods=30).mean()
    rstd = s.rolling(180, min_periods=30).std(ddof=1)
    z = (s - rmean) / rstd.where(rstd > 0)
    pct = s.rolling(252, min_periods=30).apply(
        lambda w: float((w < w[-1]).mean() * 100.0), raw=True
    )
    out: list[SkewHistoryPoint] = []
    for k, (d, v) in enumerate(pts):
        zk = z.iloc[k]
        pk = pct.iloc[k]
        out.append(
            SkewHistoryPoint(
                date=d,
                rr=_dec(v),
                z=None if pd.isna(zk) else _dec(float(zk)),
                pct=None if pd.isna(pk) else _dec(float(pk)),
            )
        )
    return out


def _rho_points(rv_series: list[dict], *, window: int = 63) -> list[SkewRhoPoint]:
    """O(n) trailing-window spot-vol correlation series. Rolling corr over the
    dropna'd Δlog(price)/ΔIV pairs — replaces the prior O(n^2) per-point DataFrame
    rebuild; matches cards.compute_spot_vol_rho pointwise on dense data."""
    df = pd.DataFrame(rv_series)
    if df.empty or "market_date" not in df:
        return []
    px = pd.to_numeric(df.get("price"), errors="coerce")
    iv = pd.to_numeric(df.get("implied_volatility"), errors="coerce")
    pair = pd.DataFrame(
        {
            "d": df["market_date"],
            "dpx": np.log(px.where(px > 0)).diff(),
            "div": iv.diff(),
        }
    ).dropna(subset=["dpx", "div"])
    if len(pair) < window:
        return []
    roll = pair["dpx"].rolling(window).corr(pair["div"])
    return [
        SkewRhoPoint(date=d, rho=_dec(float(r)))
        for d, r in zip(pair["d"], roll, strict=False)
        if pd.notna(r)
    ]


def assemble_skew_analysis(
    *,
    ticker: str,
    repo: Repository,
    backfill_status: str = "ready",
    persist: bool = False,
) -> SkewAnalysisResponse:
    """Assemble the Skew tab response. Read-only by default: the GET endpoint no
    longer writes (the nightly rollup + markout own persistence). Pass persist=True
    only from a writer job. Live-computes the scalar read + O(n) response series."""
    t = ticker.upper()
    today = _date.today()
    data = _read_series_for_ticker(repo, t, today)

    if not data["rr_series"]:
        return SkewAnalysisResponse(ticker=t, as_of=today, backfill_status="empty")

    market_date = data["latest_rr_date"]
    # Slice RV/SPY to <= market_date so spot/rho/drive never read data dated after
    # the snapshot anchor (markout integrity — no look-ahead). C-7.
    rv_asof = [r for r in data["rv_series"] if r["market_date"] <= market_date]
    spy_asof = [r for r in data["spy_rv"] if r["market_date"] <= market_date]
    sector = repo.fetch_watchlist_sector(t)  # threads Macro/Credit/Sector-ETF. C-6.
    regime = (
        repo.fetch_latest_market_regime()
    )  # canonical CRI level (None -> SPY-RV fallback)
    # first pass with no verdict to learn the bucket keys
    pre = build_skew_snapshot_row(
        ticker=t,
        market_date=market_date,
        rr_series=data["rr_series"],
        expiry_rows=data["expiry_rows"],
        rv_series=rv_asof,
        spy_rv_series=spy_asof,
        positioning=data["positioning"],
        next_earnings_date=data["next_er"],
        verdict=None,
        sector=sector,
        today=today,
        regime=regime,
    )
    verdict = repo.get_skew_directional_verdict(
        asset_class=pre["asset_class"],
        deviation_class=pre["deviation_class"],
        drive_class=pre["drive_class"],
    )
    # Swing-DTE per-strike greeks for strike-by-delta structure detail (only consumed
    # when the lean is non-neutral). Empty list when no swing chain persisted yet.
    exposures = repo.fetch_latest_swing_greeks_by_strike(t)
    row = build_skew_snapshot_row(
        ticker=t,
        market_date=market_date,
        rr_series=data["rr_series"],
        expiry_rows=data["expiry_rows"],
        rv_series=rv_asof,
        spy_rv_series=spy_asof,
        positioning=data["positioning"],
        next_earnings_date=data["next_er"],
        verdict=verdict,
        sector=sector,
        today=today,
        exposure_rows=exposures,
        regime=regime,
    )

    if persist:
        repo.upsert_skew_analytics_snapshots([row])
        repo.conn.commit()

    # response series — O(n) (was O(n^2) per-point rebuilds)
    rr_hist = repo.fetch_matrix_skew_history(ticker=t, market_date=today, days=400)
    history = _history_points(rr_hist)
    rho_series = _rho_points(data["rv_series"])

    term = [
        SkewExpiryPoint(expiry=e["expiry"], rr=_dec(e.get("risk_reversal")))
        for e in data["expiry_rows"]
        if e.get("expiry") is not None
    ]

    smile_rows = repo.fetch_iv_smile_latest(t)  # _VolatilityV2Mixin
    smile = _build_smile_curves(smile_rows)

    rj = row["read_json"]
    lean = rj["directional_lean"]
    read = SkewRead(
        tail=rj["tail"],
        rho=_dec(rj["rho"]),
        rho_confirms=rj["rho_confirms"],
        drive=rj["drive"],
        deviation_class=rj["deviation_class"],
        class_context=rj["class_context"],
        borrow_context=rj["borrow_context"],
        earnings_gate=rj["earnings_gate"],
        summary_line=rj["summary_line"],
        summary_bullets=[
            SkewReadBullet(label=b["label"], body=b["body"])
            for b in rj.get("summary_bullets", [])
        ],
        directional_lean=SkewDirectionalLean(
            lean=lean["lean"],
            confidence=lean["confidence"],
            basis=lean["basis"],
            express=lean["express"],
            structure_detail=_to_structure_detail(lean.get("structure_detail")),
        ),
    )
    return SkewAnalysisResponse(
        ticker=t,
        as_of=today,
        backfill_status=backfill_status,
        spot=row["spot"],
        rr_25d=row["rr_25d"],
        rr_z_180d=row["rr_z_180d"],
        rr_pct_252d=row["rr_pct_252d"],
        deviation_class=row["deviation_class"],
        skew_term_class=row["skew_term_class"],
        front_rr=row["front_rr"],
        back_rr=row["back_rr"],
        rho_spotvol_63d=row["rho_spotvol_63d"],
        rho_spotvol_21d=row["rho_spotvol_21d"],
        rho_sign=row["rho_sign"],
        drive_class=row["drive_class"],
        asset_class=row["asset_class"],
        class_expected_sign=row["class_expected_sign"],
        borrow_flag=row["borrow_flag"],
        borrow_fee_rate=row["borrow_fee_rate"],
        days_to_cover=row["days_to_cover"],
        earnings_gate=row["earnings_gate"],
        regime=row["regime"],
        directional_lean=row["directional_lean"],
        lean_confidence=row["lean_confidence"],
        lean_basis=row["lean_basis"],
        read=read,
        history=history,
        rho_series=rho_series,
        term_structure=term,
        smile=smile,
    )


def _build_smile_curves(rows: list[dict]) -> list[SkewSmileExpiryCurve]:
    by_expiry: dict[Any, list[SkewSmilePoint]] = {}
    for r in rows or []:
        ex = r.get("expiry")
        if ex is None or r.get("strike") is None:
            continue
        by_expiry.setdefault(ex, []).append(
            SkewSmilePoint(strike=_dec(r["strike"]), iv=_dec(r.get("iv")))
        )
    return [
        SkewSmileExpiryCurve(expiry=ex, points=sorted(pts, key=lambda p: p.strike))
        for ex, pts in sorted(by_expiry.items())
    ]
