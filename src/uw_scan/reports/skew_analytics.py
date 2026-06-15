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
) -> dict:
    """Pure stitch: raw series + verdict in, snapshot column dict out. No I/O."""
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
    regime = sk.classify_market_regime(spy_rv_series)

    lean = sk.resolve_directional_lean(
        deviation_class=deviation,
        drive_class=drive,
        asset_class=cls["asset_class"],
        regime=regime,
        borrow_flag=bflag,
        earnings_gate=egate,
        verdict=verdict,
    )
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


def assemble_skew_analysis(
    *,
    ticker: str,
    repo: Repository,
    backfill_status: str = "ready",
    persist: bool = True,
) -> SkewAnalysisResponse:
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
    )
    verdict = repo.get_skew_directional_verdict(
        asset_class=pre["asset_class"],
        deviation_class=pre["deviation_class"],
        drive_class=pre["drive_class"],
        regime=pre["regime"],
    )
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
    )

    if persist:
        repo.upsert_skew_analytics_snapshots([row])
        repo.conn.commit()

    # response series
    rr_hist = repo.fetch_matrix_skew_history(ticker=t, market_date=today, days=400)
    rr_floats = [
        float(r["risk_reversal"]) for r in rr_hist if r.get("risk_reversal") is not None
    ]
    history: list[SkewHistoryPoint] = []
    for i, r in enumerate(rr_hist):
        if r.get("risk_reversal") is None:
            continue
        win = rr_floats[: i + 1]
        b = sk.compute_skew_baseline(win)
        history.append(
            SkewHistoryPoint(
                date=r["market_date"],
                rr=_dec(r["risk_reversal"]),
                z=_dec(b["z"]),
                pct=_dec(b["pct"]),
            )
        )

    rho_series: list[SkewRhoPoint] = []
    rv_df = data["rv_series"]
    for i in range(63, len(rv_df)):
        rho = sk.compute_spot_vol_rho(rv_df[: i + 1], window=63)
        rho_series.append(SkewRhoPoint(date=rv_df[i]["market_date"], rho=_dec(rho)))

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
