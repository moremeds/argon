"""Pure GRG (Gamma Rotation Gap) scoring — ported from
radon/scripts/gamma_rotation_gap.py.

SPY-vs-TLT cross-asset dealer-gamma divergence. No DB, no network: takes
the UW greek-exposure history rows (date + net_gex per asset) plus
pre-resolved spot/flip, returns the snapshot payload dict.

DESCRIPTIVE indicator — see docs/research/grg-gamma-rotation-gap/CLAUDE.md.
Not validated as predictive.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

HISTORY_DAYS = 90
Z_WINDOW = 63
MIN_OBSERVATIONS = 70


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: coercion failure → default
        return default


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _zscore_series(values: Iterable[float], window: int = Z_WINDOW) -> np.ndarray:
    # radon gamma_rotation_gap.py:65-78 (verbatim)
    arr = np.array(list(values), dtype=float)
    out = np.full(len(arr), np.nan)
    for idx in range(len(arr)):
        start = max(0, idx - window + 1)
        chunk = arr[start : idx + 1]
        valid = chunk[np.isfinite(chunk)]
        if len(valid) < 10:
            continue
        sigma = float(np.std(valid, ddof=1))
        if sigma < 1e-12:
            continue
        out[idx] = (arr[idx] - float(np.mean(valid))) / sigma
    return out


def _slope(values: list[float], length: int = 3) -> float | None:
    # radon :81-85
    valid = [v for v in values if math.isfinite(v)]
    if len(valid) < length + 1:
        return None
    return valid[-1] - valid[-1 - length]


def _asset_state(net_gamma: float) -> str:
    # radon :102-107
    if net_gamma > 0:
        return "CUSHION"
    if net_gamma < 0:
        return "WHIP"
    return "NEUTRAL"


def _pair_state(spy_gamma: float, tlt_gamma: float) -> str:
    # radon :110-119
    if spy_gamma > 0 and tlt_gamma < 0:
        return "RISK_ON_DIVERGENCE"
    if spy_gamma < 0 and tlt_gamma > 0:
        return "RISK_OFF_DIVERGENCE"
    if spy_gamma > 0 and tlt_gamma > 0:
        return "DUAL_CUSHION"
    if spy_gamma < 0 and tlt_gamma < 0:
        return "DUAL_WHIP"
    return "NEUTRAL"


def _state_label(state: str) -> str:
    # radon :122-129
    return {
        "RISK_ON_DIVERGENCE": "Risk-on divergence",
        "RISK_OFF_DIVERGENCE": "Risk-off divergence",
        "DUAL_CUSHION": "Dual cushion",
        "DUAL_WHIP": "Dual whip",
        "NEUTRAL": "Neutral",
    }.get(state, state)


def _classify_signal(
    grg_z: float | None,
    spy_gamma: float,
    tlt_gamma: float,
    spy_slope_3d: float | None,
    spy_flip_gap_pct: float | None,
) -> dict[str, Any]:
    # radon :132-190
    state = _pair_state(spy_gamma, tlt_gamma)
    z = grg_z if grg_z is not None and math.isfinite(grg_z) else 0.0

    top_gates = [
        z >= 2.0,
        spy_gamma > 0,
        spy_slope_3d is not None and spy_slope_3d < 0,
        state == "RISK_ON_DIVERGENCE",
        spy_flip_gap_pct is not None and spy_flip_gap_pct > 0,
    ]
    bottom_gates = [
        z <= -2.0,
        spy_gamma < 0,
        spy_slope_3d is not None and spy_slope_3d > 0,
        state == "RISK_OFF_DIVERGENCE",
        spy_flip_gap_pct is not None and spy_flip_gap_pct > 0,
    ]
    top_score = sum(1 for gate in top_gates if gate)
    bottom_score = sum(1 for gate in bottom_gates if gate)

    if state == "DUAL_WHIP":
        interpretation = "DUAL_WHIP"
        tier: int | None = 2 if abs(z) >= 2 else 3
    elif state == "RISK_ON_DIVERGENCE" and z >= 2.5:
        interpretation = "TOP_WATCH"
        tier = 1 if top_score >= 4 else 2
    elif state == "RISK_ON_DIVERGENCE":
        interpretation = "RISK_ON"
        tier = 3
    elif state == "RISK_OFF_DIVERGENCE" and z <= -2.5:
        interpretation = "BOTTOM_WATCH"
        tier = 1 if bottom_score >= 4 else 2
    elif state == "RISK_OFF_DIVERGENCE":
        interpretation = "RISK_OFF"
        tier = 3
    elif state == "DUAL_CUSHION":
        interpretation = "CUSHION"
        tier = None
    else:
        interpretation = "NORMAL"
        tier = None

    return {
        "state": state,
        "state_label": _state_label(state),
        "interpretation": interpretation,
        "tier": tier,
        "top_watch": interpretation == "TOP_WATCH" or top_score >= 4,
        "bottom_watch": interpretation == "BOTTOM_WATCH" or bottom_score >= 4,
        "top_score": top_score,
        "bottom_score": bottom_score,
    }


def _gate_rows(
    z: float | None,
    spy_gamma: float,
    tlt_gamma: float,
    spy_slope_3d: float | None,
    spy_flip_gap_pct: float | None,
) -> list[dict[str, str]]:
    # radon :193-238
    z_val = z if z is not None and math.isfinite(z) else 0.0
    return [
        {
            "id": "polarity",
            "label": "Polarity",
            "status": "PASS" if spy_gamma > 0 and tlt_gamma < 0 else "WATCH",
            "copy": "SPY positive and TLT negative identifies the clean risk-on divergence.",
        },
        {
            "id": "magnitude",
            "label": "Magnitude",
            "status": "PASS" if abs(z_val) >= 2 else "WATCH",
            "copy": "Absolute GRG above 2σ means the cross-asset gamma spread is statistically stretched.",
        },
        {
            "id": "spy_cushion",
            "label": "SPY cushion",
            "status": "PASS" if spy_gamma > 0 else "FAIL",
            "copy": "Positive SPY gamma means dealer hedging is mechanically dampening equity moves.",
        },
        {
            "id": "duration_whip",
            "label": "TLT whip",
            "status": "PASS" if tlt_gamma < 0 else "WATCH",
            "copy": "Negative TLT gamma means duration moves are mechanically amplified.",
        },
        {
            "id": "decay",
            "label": "Decay",
            "status": "PASS"
            if spy_slope_3d is not None and spy_slope_3d < 0
            else "WATCH",
            "copy": "A negative 3-session SPY gamma slope marks possible equity cushion decay.",
        },
        {
            "id": "flip",
            "label": "Flip",
            "status": "PASS"
            if spy_flip_gap_pct is not None and spy_flip_gap_pct > 0
            else "WATCH",
            "copy": "Spot above the SPY gamma flip keeps the equity cushion valid.",
        },
    ]


def _summary_copy(interpretation: str, state: str) -> str:
    # radon :452-465
    if interpretation == "TOP_WATCH":
        return (
            "SPY gamma support is stretched while TLT gamma remains mechanically "
            "fragile. Treat upside chase as late-cycle until SPY support refreshes."
        )
    if interpretation == "BOTTOM_WATCH":
        return (
            "SPY gamma stress is stretched and repair conditions are forming. Watch "
            "for spot recapturing the gamma flip before calling a bottom."
        )
    if state == "RISK_ON_DIVERGENCE":
        return "SPY gamma is cushioning equities while TLT gamma is amplifying duration moves."
    if state == "RISK_OFF_DIVERGENCE":
        return "SPY gamma is amplifying equity moves while TLT gamma is cushioning duration."
    if state == "DUAL_WHIP":
        return "Both SPY and TLT are short gamma. Cross-asset moves can gap because dealers amplify both sides."
    if state == "DUAL_CUSHION":
        return "Both SPY and TLT are positive gamma. Dealer hedging is dampening both equity and duration moves."
    return "Cross-asset gamma is near neutral."


def _flip_gap_pct(spot: float | None, flip: float | None) -> float | None:
    """Positive when spot is ABOVE the gamma flip (cushion valid).

    radon negates UW's (flip-spot)/spot → (spot-flip)/spot*100.
    """
    if spot is None or flip is None or spot == 0:
        return None
    return (spot - flip) / spot * 100.0


def _extract_events(
    dates: list[str],
    spy_values: list[float],
    tlt_values: list[float],
    grg_z: np.ndarray,
    *,
    year_start: str,
    cap: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Gate-confirmed TOP_WATCH / BOTTOM_WATCH events since ``year_start`` (YTD).

    Classifies EVERY aligned day with the same gate logic as the latest signal
    but with ``spy_flip_gap_pct=None``: UW's greek-exposure history carries no
    per-day gamma flip or price (see cards/greek_exposure_history), so the flip
    gate can't contribute to a *historical* event — the other four gates still
    can. Result is most-recent-first and capped; the UI shows the top 5 of each.
    ``dates`` are ISO strings, so the ``d < year_start`` compare is lexical.
    """
    tops: list[dict[str, Any]] = []
    bottoms: list[dict[str, Any]] = []
    for idx, d in enumerate(dates):
        if d < year_start:
            continue
        z_raw = float(grg_z[idx])
        z = z_raw if math.isfinite(z_raw) else None
        spy_gamma = spy_values[idx]
        tlt_gamma = tlt_values[idx]
        slope_3d = spy_values[idx] - spy_values[idx - 3] if idx >= 3 else None
        cls = _classify_signal(z, spy_gamma, tlt_gamma, slope_3d, None)
        if not (cls["top_watch"] or cls["bottom_watch"]):
            continue
        event = {
            "date": d,
            "grg_z": _round(z),
            "pair_state": cls["state"],
            "tier": cls["tier"],
            "spy_net_gamma": _round(spy_gamma, 4),
            "tlt_net_gamma": _round(tlt_gamma, 4),
        }
        if cls["top_watch"]:
            tops.append(event)
        if cls["bottom_watch"]:
            bottoms.append(event)
    tops.reverse()
    bottoms.reverse()
    return {"tops": tops[:cap], "bottoms": bottoms[:cap]}


def run_analysis(
    spy_rows: list[dict],
    tlt_rows: list[dict],
    *,
    spy_spot: float | None,
    spy_flip: float | None,
    tlt_spot: float | None,
    tlt_flip: float | None,
    spy_prices: dict[str, float] | None = None,
    scan_time: str,
    market_open: bool,
) -> dict[str, Any]:
    """Build the GRG snapshot payload from UW greek-exposure history rows.

    ``spy_rows`` / ``tlt_rows`` are ``parse_greek_exposure_history`` output:
    each carries a ``date`` (date obj) and ``net_gex`` (call_gex+put_gex).
    Mirrors radon ``compute_gamma_rotation`` (:333-449).
    """
    spy_history = {
        r["date"].isoformat(): _f(r.get("net_gex"))
        for r in spy_rows
        if r.get("date") is not None
    }
    tlt_history = {
        r["date"].isoformat(): _f(r.get("net_gex"))
        for r in tlt_rows
        if r.get("date") is not None
    }
    dates = sorted(set(spy_history) & set(tlt_history))
    if len(dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Only {len(dates)} aligned observations; need {MIN_OBSERVATIONS}"
        )

    spy_values = [spy_history[d] for d in dates]
    tlt_values = [tlt_history[d] for d in dates]
    spy_z = _zscore_series(spy_values)
    tlt_z = _zscore_series(tlt_values)
    spread = spy_z - tlt_z
    grg_z = _zscore_series(spread)

    prices = spy_prices or {}
    history: list[dict[str, Any]] = []
    for idx, d in enumerate(dates):
        spy_gamma = spy_values[idx]
        tlt_gamma = tlt_values[idx]
        history.append(
            {
                "date": d,
                "spy_price": _round(prices.get(d), 4),
                "spy_net_gamma": _round(spy_gamma, 4),
                "tlt_net_gamma": _round(tlt_gamma, 4),
                "spy_gamma_z": _round(float(spy_z[idx]))
                if math.isfinite(float(spy_z[idx]))
                else None,
                "tlt_gamma_z": _round(float(tlt_z[idx]))
                if math.isfinite(float(tlt_z[idx]))
                else None,
                "grg_z": _round(float(grg_z[idx]))
                if math.isfinite(float(grg_z[idx]))
                else None,
                "raw_spread": _round(float(spread[idx]))
                if math.isfinite(float(spread[idx]))
                else None,
                "state": _pair_state(spy_gamma, tlt_gamma),
            }
        )

    latest_idx = len(dates) - 1
    latest_date = dates[-1]
    spy_cur = spy_values[-1]
    tlt_cur = tlt_values[-1]
    latest_grg = (
        float(grg_z[latest_idx]) if math.isfinite(float(grg_z[latest_idx])) else None
    )
    latest_spread = (
        float(spread[latest_idx]) if math.isfinite(float(spread[latest_idx])) else None
    )
    spy_slope_3d = _slope(spy_values, 3)
    tlt_slope_3d = _slope(tlt_values, 3)
    spy_flip_gap_pct = _flip_gap_pct(spy_spot, spy_flip)
    tlt_flip_gap_pct = _flip_gap_pct(tlt_spot, tlt_flip)

    classification = _classify_signal(
        latest_grg, spy_cur, tlt_cur, spy_slope_3d, spy_flip_gap_pct
    )
    gates = _gate_rows(latest_grg, spy_cur, tlt_cur, spy_slope_3d, spy_flip_gap_pct)
    year_start = f"{latest_date[:4]}-01-01"
    events = _extract_events(
        dates,
        spy_values,
        tlt_values,
        grg_z,
        year_start=year_start,
    )

    def _asset(
        ticker: str,
        spot: float | None,
        flip: float | None,
        flip_gap_pct: float | None,
        values: list[float],
        z_values: np.ndarray,
        slope_3d: float | None,
    ) -> dict[str, Any]:
        latest_gamma = values[-1]
        one_d = values[-1] - values[-2] if len(values) >= 2 else None
        return {
            "ticker": ticker,
            "spot": _round(spot, 4),
            "data_date": latest_date,
            "net_gamma": _round(latest_gamma, 4),
            "net_gex": _round(latest_gamma, 4),
            "gamma_z": _round(float(z_values[-1]))
            if math.isfinite(float(z_values[-1]))
            else None,
            "gamma_1d_change": _round(one_d, 4),
            "gamma_3d_change": _round(slope_3d, 4),
            "state": _asset_state(latest_gamma),
            "flip": _round(flip, 4),
            "spot_vs_flip_pct": _round(flip_gap_pct, 4),
        }

    signal = {
        **classification,
        "grg_z": _round(latest_grg, 4),
        "raw_spread": _round(latest_spread, 4),
        "spy_gamma_z": _round(float(spy_z[-1]))
        if math.isfinite(float(spy_z[-1]))
        else None,
        "tlt_gamma_z": _round(float(tlt_z[-1]))
        if math.isfinite(float(tlt_z[-1]))
        else None,
        "spy_3d_gamma_change": _round(spy_slope_3d, 4),
        "tlt_3d_gamma_change": _round(tlt_slope_3d, 4),
        "summary": _summary_copy(
            classification["interpretation"], classification["state"]
        ),
    }

    return {
        "scan_time": scan_time,
        "market_open": market_open,
        "data_date": latest_date,
        "source": "Unusual Whales",
        "lookback_days": len(dates),
        "z_window": Z_WINDOW,
        "basis": "eod",
        "signal": signal,
        "assets": {
            "SPY": _asset(
                "SPY",
                spy_spot,
                spy_flip,
                spy_flip_gap_pct,
                spy_values,
                spy_z,
                spy_slope_3d,
            ),
            "TLT": _asset(
                "TLT",
                tlt_spot,
                tlt_flip,
                tlt_flip_gap_pct,
                tlt_values,
                tlt_z,
                tlt_slope_3d,
            ),
        },
        "gates": gates,
        # YTD display window. z-scores are computed over the full fetched
        # series (≈1Y) so the 63-session window is warm before Jan 1; the
        # chart then shows the current year only. Falls back to the last
        # HISTORY_DAYS if the series somehow predates the year boundary by
        # less than a full year (keeps a non-empty chart).
        "history": [h for h in history if h["date"] >= year_start]
        or history[-HISTORY_DAYS:],
        "events": events,
        "top_bottom": {
            "top": {
                "active": bool(signal["top_watch"]),
                "copy": "Potential top: stretched positive GRG, positive SPY gamma, equity cushion decay, and duration gamma stress.",
            },
            "bottom": {
                "active": bool(signal["bottom_watch"]),
                "copy": "Potential bottom: stretched negative GRG, SPY gamma repair, and recapture of the SPY gamma flip after stress.",
            },
        },
    }
