"""Cockpit 6-dimension matrix state deriver.

Phase 2 intentionally ships a v1 proxy for the dealer-flow dimensions. The
`pin_distance_sigma_v1` charm proxy measures vol-scaled distance from spot to
the nearest high-OI strike at the nearest expiry within five days. It is a
deliberate approximation, not the final charm classifier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from uw_scan.models import MatrixDirection, MatrixState
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

EXPECTED_FRESH_DIMS_V1 = frozenset({"vanna", "charm", "skew", "term", "vrp"})
_DIRECTIONAL = {"vol_up", "vol_down"}
_CONTENT_TIERS = {"strict", "strong", "weak"}
EXPECTED_ABS_MOVE_FACTOR = Decimal("0.7979")


@dataclass(frozen=True)
class MatrixInputs:
    ticker: str
    market_date: date
    vanna_state: MatrixDirection
    charm_state: MatrixDirection
    skew_state: MatrixDirection
    term_state: MatrixDirection
    threshold_version: int = 1
    im_state: MatrixDirection = "stale"
    flow_state: MatrixDirection = "stale"
    vrp_state: MatrixDirection = "stale"
    term_classification: (
        Literal["contango", "event_back", "liquidity_back", "mixed"] | None
    ) = None
    skew_25d_zscore_180d: Decimal | None = None
    iv_atm_30d: Decimal | None = None
    rv_30d: Decimal | None = None
    vrp: Decimal | None = None
    vrp_zscore_60d: Decimal | None = None
    implied_move_pct: Decimal | None = None
    front_iv: Decimal | None = None
    back_iv: Decimal | None = None
    front_back_spread: Decimal | None = None
    pin_distance_sigma: Decimal | None = None
    vrp_sign_flip_status: bool | Literal["insufficient_history"] = (
        "insufficient_history"
    )
    vrp_sign_flip_aligned_days: int = 0
    vanna_conditional_reading: (
        Literal["grind_up", "reverse_selloff", "reflexive_sell_pressure", "weak_noise"]
        | None
    ) = None
    directional_imbalance_3d: Decimal | None = None
    vanna_oi_change_bias: Literal["call_oi_build", "put_oi_build", "mixed"] | None = (
        None
    )
    charm_regime: (
        Literal["operative_magnet", "broken_magnet", "opex_vortex", "neutral"] | None
    ) = None
    charm_stress_override: bool = False
    skew_25d_5d_change: Decimal | None = None
    skew_regime: Literal["smirk", "accelerated", "crash_smile", "neutral"] | None = None
    skew_term_structure: Decimal | None = None
    single_point_bump_pct: Decimal | None = None
    full_curve_slope_pct: Decimal | None = None
    term_johnson_slope_pc1: Decimal | None = None
    atm_straddle_mid: Decimal | None = None
    implied_move_expected_abs: Decimal | None = None
    implied_move_event_percentile: Decimal | None = None
    vrp_zscore_252d: Decimal | None = None
    dim5_stale_wins: bool = True


def dim5_vote(
    im_state: MatrixDirection,
    flow_state: MatrixDirection,
    *,
    stale_wins: bool = True,
) -> MatrixDirection:
    if stale_wins and (im_state == "stale" or flow_state == "stale"):
        return "stale"
    if im_state == "stale":
        return flow_state
    if flow_state == "stale":
        return im_state
    if im_state == flow_state:
        return im_state
    return "neutral"


def pin_distance_sigma_v1(
    spot: Decimal | None,
    nearest_strike: Decimal | None,
    rv_30d: Decimal | None,
    dte_days: int,
) -> Decimal | None:
    if (
        spot is None
        or nearest_strike is None
        or rv_30d is None
        or spot <= 0
        or rv_30d <= 0
        or dte_days <= 0
    ):
        return None
    sigma_to_expiry = spot * rv_30d * Decimal(dte_days / 252).sqrt()
    if sigma_to_expiry <= 0:
        return None
    return abs(spot - nearest_strike) / sigma_to_expiry


def build_matrix_state(
    repo: Repository,
    *,
    ticker: str,
    market_date: date,
    threshold_version: int = 1,
) -> MatrixState:
    """Build a deterministic matrix snapshot from persisted source tables."""

    inputs = _read_inputs(
        repo,
        ticker=ticker.upper(),
        market_date=market_date,
        threshold_version=threshold_version,
    )
    return build_matrix_state_from_inputs(inputs)


def build_matrix_state_from_inputs(inputs: MatrixInputs) -> MatrixState:
    dim_states: dict[str, MatrixDirection] = {
        "vanna": inputs.vanna_state,
        "charm": inputs.charm_state,
        "skew": inputs.skew_state,
        "term": inputs.term_state,
        "vrp": inputs.vrp_state,
    }
    fresh_votes = {
        dim: state
        for dim, state in dim_states.items()
        if dim in EXPECTED_FRESH_DIMS_V1 and state != "stale"
    }

    dim5 = dim5_vote(
        inputs.im_state, inputs.flow_state, stale_wins=inputs.dim5_stale_wins
    )
    expected_fresh = set(EXPECTED_FRESH_DIMS_V1)
    if not inputs.dim5_stale_wins and dim5 != "stale":
        expected_fresh.add("dim_5")
        fresh_votes["dim_5"] = dim5

    cluster_coverage_ok = not (
        inputs.vanna_state in {"neutral", "stale"}
        and inputs.charm_state in {"neutral", "stale"}
    )

    missing = expected_fresh - set(fresh_votes)
    if len(missing) >= 2:
        tier = "insufficient_data"
    else:
        tier = _directional_tier(fresh_votes)
        if not cluster_coverage_ok and tier in _CONTENT_TIERS:
            tier = "no_trade"

    vrp_state = inputs.vrp_state
    override_applied = False
    if inputs.vrp_sign_flip_status is True and tier in _CONTENT_TIERS:
        vrp_state = "vol_up"
        tier = _downgrade_tier(tier)
        override_applied = True

    _log_vrp_sign_flip(
        ticker=inputs.ticker,
        market_date=inputs.market_date,
        status=inputs.vrp_sign_flip_status,
        aligned_days=inputs.vrp_sign_flip_aligned_days,
        override_applied=override_applied,
    )

    return MatrixState(
        ticker=inputs.ticker.upper(),
        market_date=inputs.market_date,
        threshold_version=inputs.threshold_version,
        vanna_state=inputs.vanna_state,
        charm_state=inputs.charm_state,
        skew_state=inputs.skew_state,
        term_state=inputs.term_state,
        im_state=inputs.im_state,
        flow_state=inputs.flow_state,
        vrp_state=vrp_state,
        consistency_tier=tier,
        cluster_coverage_ok=cluster_coverage_ok,
        term_classification=inputs.term_classification,
        skew_25d_zscore_180d=inputs.skew_25d_zscore_180d,
        iv_atm_30d=inputs.iv_atm_30d,
        rv_30d=inputs.rv_30d,
        vrp=inputs.vrp,
        vrp_zscore_60d=inputs.vrp_zscore_60d,
        implied_move_pct=inputs.implied_move_pct,
        front_iv=inputs.front_iv,
        back_iv=inputs.back_iv,
        front_back_spread=inputs.front_back_spread,
        pin_distance_sigma=inputs.pin_distance_sigma,
        vrp_sign_flip_status=inputs.vrp_sign_flip_status,
        vrp_sign_flip_aligned_days=inputs.vrp_sign_flip_aligned_days,
        vanna_conditional_reading=inputs.vanna_conditional_reading,
        directional_imbalance_3d=inputs.directional_imbalance_3d,
        vanna_oi_change_bias=inputs.vanna_oi_change_bias,
        charm_regime=inputs.charm_regime,
        charm_stress_override=inputs.charm_stress_override,
        skew_25d_5d_change=inputs.skew_25d_5d_change,
        skew_regime=inputs.skew_regime,
        skew_term_structure=inputs.skew_term_structure,
        single_point_bump_pct=inputs.single_point_bump_pct,
        full_curve_slope_pct=inputs.full_curve_slope_pct,
        term_johnson_slope_pc1=inputs.term_johnson_slope_pc1,
        atm_straddle_mid=inputs.atm_straddle_mid,
        implied_move_expected_abs=inputs.implied_move_expected_abs,
        implied_move_event_percentile=inputs.implied_move_event_percentile,
        vrp_zscore_252d=inputs.vrp_zscore_252d,
    )


def _directional_tier(votes: dict[str, MatrixDirection]) -> str:
    directional = [state for state in votes.values() if state in _DIRECTIONAL]
    if "vol_up" in directional and "vol_down" in directional:
        return "no_trade"

    n = len(votes)
    agree = len(directional)
    neutral_dims = [dim for dim, state in votes.items() if state == "neutral"]
    neutral_fresh = len(neutral_dims)

    if n == 0:
        return "insufficient_data"
    if agree == n:
        return "strict"
    if agree == n - 1 and neutral_fresh == 1:
        return "strong"
    if agree == n - 2 and neutral_fresh == 2:
        if {"vrp", "term"} & set(neutral_dims):
            return "no_trade"
        return "weak"
    return "no_trade"


def _downgrade_tier(tier: str) -> str:
    return {"strict": "strong", "strong": "weak", "weak": "no_trade"}[tier]


def _log_vrp_sign_flip(
    *,
    ticker: str,
    market_date: date,
    status: bool | Literal["insufficient_history"],
    aligned_days: int,
    override_applied: bool,
) -> None:
    logger.info(
        "cockpit_matrix: vrp_sign_flip ticker=%s market_date=%s status=%s "
        "aligned_days=%d override_applied=%s",
        ticker,
        market_date,
        status,
        aligned_days,
        override_applied,
        extra={
            "event": "vrp_sign_flip",
            "ticker": ticker,
            "market_date": market_date.isoformat(),
            "status": status,
            "aligned_days": aligned_days,
            "override_applied": override_applied,
        },
    )


def _read_inputs(
    repo: Repository, *, ticker: str, market_date: date, threshold_version: int
) -> MatrixInputs:
    greeks = repo.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
    straddle_mid_rows = repo.fetch_matrix_straddle_mid_rows(
        ticker=ticker, market_date=market_date
    )
    exposures = repo.fetch_matrix_exposure_rows(ticker=ticker, market_date=market_date)
    skew_rows = repo.fetch_matrix_skew_history(ticker=ticker, market_date=market_date)
    skew_expiry_rows = repo.fetch_matrix_skew_expiry_rows(
        ticker=ticker, market_date=market_date
    )
    term_rows = repo.fetch_matrix_term_rows(ticker=ticker, market_date=market_date)
    iv_rows = repo.fetch_matrix_interpolated_iv_history(
        ticker=ticker, market_date=market_date, days=300
    )
    rv_rows = repo.fetch_matrix_realized_vol_history(
        ticker=ticker, market_date=market_date, days=300
    )
    chain_rows = repo.fetch_matrix_option_chain_rows(
        ticker=ticker, market_date=market_date
    )

    iv_30d = _latest_iv_30d(iv_rows, market_date)
    rv_30d = _latest_rv_30d(rv_rows, market_date)
    spot = _latest_spot(rv_rows, market_date)
    atm_straddle_mid = _atm_straddle_mid(straddle_mid_rows, spot=spot)
    skew_fresh = _has_row_for_date(skew_rows, market_date)
    skew_z = _zscore_for_date(skew_rows, "risk_reversal", market_date, 180)
    skew_change = _skew_change_for_date(skew_rows, market_date, days=5)
    skew_regime = _skew_regime(skew_z, skew_change)
    skew_term = _skew_term_structure(skew_expiry_rows)
    vrp, vrp_z = _vrp_values(iv_rows, rv_rows, market_date, window=60)
    _vrp_current, vrp_z_252 = _vrp_values(iv_rows, rv_rows, market_date, window=252)
    sign_flip_status, aligned_days = _vrp_sign_flip_status(iv_rows, rv_rows)
    term_metrics = _term_metrics(term_rows)
    term_state = term_metrics["state"]
    term_classification = term_metrics["classification"]
    front_iv = term_metrics["front_iv"]
    back_iv = term_metrics["back_iv"]
    skew_state = (
        _state_from_z(skew_z, up_state="vol_up", down_state="vol_down")
        if skew_z is not None
        else "neutral"
        if skew_fresh
        else "stale"
    )
    vanna_state = _vanna_state(greeks, exposures)
    charm_state, pin_sigma, charm_regime, charm_stress_override = _charm_state(
        has_greeks=bool(greeks),
        chain_rows=chain_rows,
        spot=spot,
        rv_30d=rv_30d,
        iv_30d=iv_30d,
        term_state=term_state,
        skew_state=skew_state,
        market_date=market_date,
    )
    dealer_metrics = repo.fetch_cockpit_dealer_metrics(
        ticker=ticker, market_date=market_date
    )
    vrp_state = (
        _state_from_z(vrp_z, up_state="vol_down", down_state="vol_up")
        if vrp_z is not None
        else "neutral"
        if vrp is not None
        else "stale"
    )

    return MatrixInputs(
        ticker=ticker,
        market_date=market_date,
        threshold_version=threshold_version,
        vanna_state=vanna_state,
        charm_state=charm_state,
        skew_state=skew_state,
        term_state=term_state,
        vrp_state=vrp_state,
        term_classification=term_classification,
        skew_25d_zscore_180d=skew_z,
        iv_atm_30d=iv_30d,
        rv_30d=rv_30d,
        vrp=vrp,
        vrp_zscore_60d=vrp_z,
        vrp_zscore_252d=vrp_z_252,
        implied_move_pct=_latest_implied_move_pct(iv_rows, market_date),
        front_iv=front_iv,
        back_iv=back_iv,
        front_back_spread=term_metrics["front_back_spread"],
        pin_distance_sigma=pin_sigma,
        vrp_sign_flip_status=sign_flip_status,
        vrp_sign_flip_aligned_days=aligned_days,
        directional_imbalance_3d=dealer_metrics.directional_imbalance_3d,
        vanna_oi_change_bias=_oi_change_bias(
            repo.fetch_matrix_oi_change_rows(ticker=ticker, market_date=market_date)
        ),
        vanna_conditional_reading=_vanna_conditional_reading(
            iv_30d_delta_5d=dealer_metrics.iv_30d_delta_5d,
            directional_imbalance_3d=dealer_metrics.directional_imbalance_3d,
            flow_color=dealer_metrics.flow_color_lookback_3d,
            net_gamma_sign=dealer_metrics.net_gamma_sign,
        ),
        charm_regime=charm_regime,
        charm_stress_override=charm_stress_override,
        skew_25d_5d_change=skew_change,
        skew_regime=skew_regime,
        skew_term_structure=skew_term,
        single_point_bump_pct=term_metrics["single_point_bump_pct"],
        full_curve_slope_pct=term_metrics["full_curve_slope_pct"],
        term_johnson_slope_pc1=term_metrics["term_johnson_slope_pc1"],
        atm_straddle_mid=atm_straddle_mid,
        implied_move_expected_abs=_implied_move_expected_abs(
            term_rows, atm_straddle_mid=atm_straddle_mid, spot=spot
        ),
        implied_move_event_percentile=None,
    )


def _vanna_state(greeks: list[dict], exposures: list[dict]) -> MatrixDirection:
    if not greeks:
        return "stale"
    if not exposures:
        return "neutral"
    net = sum(
        (row.get("call_vanna") or Decimal(0)) + (row.get("put_vanna") or Decimal(0))
        for row in exposures
    )
    if net > 0:
        return "vol_up"
    if net < 0:
        return "vol_down"
    return "neutral"


def _charm_state(
    *,
    has_greeks: bool,
    chain_rows: list[dict],
    spot: Decimal | None,
    rv_30d: Decimal | None,
    iv_30d: Decimal | None,
    term_state: MatrixDirection,
    skew_state: MatrixDirection,
    market_date: date,
) -> tuple[MatrixDirection, Decimal | None, str | None, bool]:
    if not has_greeks:
        return "stale", None, None, False
    candidate = _nearest_high_oi_strike(chain_rows, spot=spot, market_date=market_date)
    if candidate is None:
        return "neutral", None, "neutral", False
    expiry, strike = candidate
    pin_sigma = pin_distance_sigma_v1(spot, strike, rv_30d, (expiry - market_date).days)
    if pin_sigma is None or iv_30d is None:
        return "neutral", pin_sigma, "neutral", False
    high_vol = rv_30d is not None and iv_30d > rv_30d * Decimal("1.25")
    stress_override = bool(
        high_vol
        and (
            term_state == "vol_up"
            or skew_state == "vol_up"
            or pin_sigma > Decimal("2.0")
        )
    )
    dte = (expiry - market_date).days
    if pin_sigma < Decimal("1.0") and iv_30d < Decimal("0.35"):
        regime = (
            "opex_vortex"
            if dte <= 1 and pin_sigma < Decimal("0.5")
            else "operative_magnet"
        )
        return "vol_down", pin_sigma, regime, False
    if stress_override:
        regime = "opex_vortex" if dte <= 1 else "broken_magnet"
        return "vol_up", pin_sigma, regime, True
    return "neutral", pin_sigma, "neutral", False


def _nearest_high_oi_strike(
    rows: list[dict], *, spot: Decimal | None, market_date: date
) -> tuple[date, Decimal] | None:
    if spot is None or spot <= 0:
        return None
    filtered = []
    for row in rows:
        expiry = row.get("expiry")
        strike = row.get("strike")
        if expiry is None or strike is None:
            continue
        dte = (expiry - market_date).days
        # 0-DTE makes pin_distance_sigma_v1 degenerate (sqrt(0) → 0).
        # Skip same-day so we pick the next available expiry.
        if dte <= 0 or dte > 5:
            continue
        if abs(strike - spot) / spot > Decimal("0.02"):
            continue
        oi = (row.get("call_oi") or 0) + (row.get("put_oi") or 0)
        filtered.append((expiry, Decimal(str(strike)), int(oi)))
    if not filtered:
        return None
    nearest_expiry = min(expiry for expiry, _strike, _oi in filtered)
    expiry_rows = [row for row in filtered if row[0] == nearest_expiry]
    expiry, strike, _oi = max(
        expiry_rows, key=lambda row: (row[2], -abs(row[1] - spot))
    )
    return expiry, strike


def _term_state(
    rows: list[dict],
) -> tuple[MatrixDirection, str | None, Decimal | None, Decimal | None]:
    metrics = _term_metrics(rows)
    return (
        metrics["state"],
        metrics["classification"],
        metrics["front_iv"],
        metrics["back_iv"],
    )


def _term_metrics(rows: list[dict]) -> dict:
    if not rows:
        return _empty_term_metrics("stale")
    vols = [row for row in rows if row.get("volatility") is not None]
    if len(vols) < 2:
        out = _empty_term_metrics("vol_up")
        out["classification"] = "mixed"
        return out
    vols = sorted(vols, key=lambda row: (row.get("dte") is None, row.get("dte") or 0))
    front = Decimal(str(vols[0]["volatility"]))
    back = Decimal(str(vols[-1]["volatility"]))
    single_bump = _single_point_bump_pct(vols)
    slope = _full_curve_slope_pct(vols)
    classification: str
    state: MatrixDirection
    if front <= back:
        state = "vol_down"
        classification = "contango"
    elif single_bump is not None and single_bump >= Decimal("0.15"):
        state = "vol_down"
        classification = "event_back"
    elif back > 0 and front / back >= Decimal("1.15"):
        state = "vol_up"
        classification = "liquidity_back"
    else:
        state = "vol_down"
        classification = "event_back"
    return {
        "state": state,
        "classification": classification,
        "front_iv": front,
        "back_iv": back,
        "front_back_spread": back - front,
        "single_point_bump_pct": single_bump,
        "full_curve_slope_pct": slope,
        # V1 proxy for the research PC1 slope; full rolling PCA belongs to Phase 5.
        "term_johnson_slope_pc1": slope,
    }


def _empty_term_metrics(state: MatrixDirection) -> dict:
    return {
        "state": state,
        "classification": None,
        "front_iv": None,
        "back_iv": None,
        "front_back_spread": None,
        "single_point_bump_pct": None,
        "full_curve_slope_pct": None,
        "term_johnson_slope_pc1": None,
    }


def _single_point_bump_pct(rows: list[dict]) -> Decimal | None:
    if len(rows) < 2:
        return None
    vols = [Decimal(str(row["volatility"])) for row in rows]
    dtes = [row.get("dte") for row in rows]
    max_index = max(range(len(vols)), key=lambda i: vols[i])
    if max_index == len(vols) - 1:
        return Decimal("0")
    baseline_values = [value for i, value in enumerate(vols) if i != max_index]
    baseline = sum(baseline_values) / Decimal(len(baseline_values))
    if baseline <= 0:
        return None
    if dtes[max_index] is None:
        return None
    bump = (vols[max_index] - baseline) / baseline
    return bump if bump > 0 else Decimal("0")


def _full_curve_slope_pct(rows: list[dict]) -> Decimal | None:
    if len(rows) < 2:
        return None
    vols = [Decimal(str(row["volatility"])) for row in rows]
    front = vols[0]
    back = vols[-1]
    if front <= 0:
        return None
    return (back - front) / front


def _state_from_z(
    z: Decimal | None, *, up_state: MatrixDirection, down_state: MatrixDirection
) -> MatrixDirection:
    if z is None:
        return "stale"
    if z > Decimal("0.5") and up_state == "vol_down":
        return up_state
    if z < Decimal("-0.5") and down_state == "vol_up":
        return down_state
    if z > Decimal("1.0") and up_state == "vol_up":
        return up_state
    if z < Decimal("-1.0") and down_state == "vol_down":
        return down_state
    return "neutral"


def _latest_iv_30d(rows: list[dict], market_date: date) -> Decimal | None:
    row = _row_for_date(rows, market_date)
    return None if row is None else row.get("volatility")


def _latest_implied_move_pct(rows: list[dict], market_date: date) -> Decimal | None:
    row = _row_for_date(rows, market_date)
    return None if row is None else row.get("implied_move_perc")


def _latest_rv_30d(rows: list[dict], market_date: date) -> Decimal | None:
    # UW returns realized_volatility as NULL for the most recent ~3 days
    # (RV is a backward-looking aggregate). Walk back to the latest non-null
    # RV value at or before market_date so derived state fields don't all
    # silently go null on the day the snapshot is run.
    for row in reversed(rows):
        if row.get("market_date") is None or row["market_date"] > market_date:
            continue
        rv = row.get("realized_volatility")
        if rv is not None:
            return rv
    return None


def _latest_spot(rows: list[dict], market_date: date) -> Decimal | None:
    # Same fallback pattern as _latest_rv_30d: prices may be missing on the
    # most recent date if UW's series lags. Walk back to the latest non-null.
    for row in reversed(rows):
        if row.get("market_date") is None or row["market_date"] > market_date:
            continue
        price = row.get("price")
        if price is not None:
            return price
    return None


def _row_for_date(rows: list[dict], market_date: date) -> dict | None:
    for row in reversed(rows):
        if row.get("market_date") == market_date:
            return row
    return None


def _has_row_for_date(rows: list[dict], market_date: date) -> bool:
    return any(row.get("market_date") == market_date for row in rows)


def _zscore_for_date(
    rows: list[dict], key: str, market_date: date, window: int
) -> Decimal | None:
    values = [
        Decimal(str(row[key]))
        for row in rows
        if row.get("market_date") <= market_date and row.get(key) is not None
    ][-window:]
    if len(values) < 2 or not any(
        row.get("market_date") == market_date for row in rows
    ):
        return None
    mean = sum(values) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    if variance == 0:
        return Decimal(0)
    return (values[-1] - mean) / variance.sqrt()


def _skew_change_for_date(
    rows: list[dict], market_date: date, *, days: int
) -> Decimal | None:
    current = _row_for_date(rows, market_date)
    if current is None or current.get("risk_reversal") is None:
        return None
    prior_cutoff = market_date.toordinal() - days
    prior_rows = [
        row
        for row in rows
        if row.get("market_date") is not None
        and row.get("market_date").toordinal() <= prior_cutoff
        and row.get("risk_reversal") is not None
    ]
    if not prior_rows:
        return None
    prior = prior_rows[-1]
    return Decimal(str(current["risk_reversal"])) - Decimal(str(prior["risk_reversal"]))


def _skew_regime(
    zscore: Decimal | None, change_5d: Decimal | None
) -> Literal["smirk", "accelerated", "crash_smile", "neutral"] | None:
    if zscore is None and change_5d is None:
        return None
    z = zscore or Decimal(0)
    change = change_5d or Decimal(0)
    if z <= Decimal("-3") and change <= Decimal("-10"):
        return "crash_smile"
    if abs(change) >= Decimal("2") or abs(z) >= Decimal("1.5"):
        return "accelerated"
    if z < 0:
        return "smirk"
    return "neutral"


def _skew_term_structure(rows: list[dict]) -> Decimal | None:
    values = [
        Decimal(str(row["risk_reversal"]))
        for row in sorted(
            rows, key=lambda row: (row.get("expiry") is None, row.get("expiry"))
        )
        if row.get("risk_reversal") is not None
    ]
    if len(values) < 2:
        return None
    return values[0] - values[-1]


def _vrp_values(
    iv_rows: list[dict], rv_rows: list[dict], market_date: date, *, window: int
) -> tuple[Decimal | None, Decimal | None]:
    series = _joined_vrp_series(iv_rows, rv_rows)
    # UW's RV endpoint returns null for the most recent ~3 days, so the
    # joined IV-RV series typically has no row for today. Use the latest
    # point at-or-before market_date instead of requiring exact match.
    current = next(
        (value for day, value in reversed(series) if day <= market_date), None
    )
    if current is None:
        return None, None
    values = [value for day, value in series if day <= market_date][-window:]
    if len(values) < 2:
        return current, None
    mean = sum(values) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    if variance == 0:
        return current, Decimal(0)
    return current, (current - mean) / variance.sqrt()


def _vrp_sign_flip_status(
    iv_rows: list[dict], rv_rows: list[dict]
) -> tuple[bool | Literal["insufficient_history"], int]:
    series = _joined_vrp_series(iv_rows, rv_rows)[-30:]
    aligned_days = len(series)
    if aligned_days < 30:
        return "insufficient_history", aligned_days
    signs = [1 if value > 0 else -1 if value < 0 else 0 for _day, value in series]
    non_zero = [sign for sign in signs if sign != 0]
    if len(non_zero) < 2:
        return False, aligned_days
    return any(prev != cur for prev, cur in zip(non_zero, non_zero[1:])), aligned_days


def _joined_vrp_series(
    iv_rows: list[dict], rv_rows: list[dict]
) -> list[tuple[date, Decimal]]:
    # interpolated_iv_snapshots is sparse (4 most recent days), while
    # realized_volatility_history carries `implied_volatility` for every day.
    # Combine both sources so VRP can be computed across the full RV history.
    iv_by_day = {
        row.get("market_date"): row.get("volatility")
        for row in iv_rows
        if row.get("market_date") is not None and row.get("volatility") is not None
    }
    series = []
    for row in rv_rows:
        day = row.get("market_date")
        rv = row.get("realized_volatility")
        if day is None or rv is None:
            continue
        iv = iv_by_day.get(day)
        if iv is None:
            iv = row.get("implied_volatility")
        if iv is None:
            continue
        series.append((day, Decimal(str(iv)) - Decimal(str(rv))))
    return sorted(series, key=lambda item: item[0])


def _atm_straddle_mid(rows: list[dict], *, spot: Decimal | None) -> Decimal | None:
    candidates = []
    for row in rows:
        call_mid = row.get("call_mid")
        put_mid = row.get("put_mid")
        strike = row.get("strike")
        expiry = row.get("expiry")
        if call_mid is None or put_mid is None or strike is None:
            continue
        distance = abs(Decimal(str(strike)) - spot) if spot is not None else Decimal(0)
        candidates.append(
            (expiry, distance, Decimal(str(call_mid)) + Decimal(str(put_mid)))
        )
    if not candidates:
        return None
    _expiry, _distance, straddle = min(
        candidates, key=lambda item: (item[0] is None, item[0], item[1])
    )
    return straddle


def _implied_move_expected_abs(
    rows: list[dict], *, atm_straddle_mid: Decimal | None, spot: Decimal | None
) -> Decimal | None:
    if atm_straddle_mid is not None and spot is not None and spot > 0:
        return (atm_straddle_mid / spot) * EXPECTED_ABS_MOVE_FACTOR
    ordered = [
        row
        for row in sorted(
            rows, key=lambda row: (row.get("dte") is None, row.get("dte") or 0)
        )
        if row.get("implied_move_perc") is not None
    ]
    if not ordered:
        return None
    return Decimal(str(ordered[0]["implied_move_perc"])) * EXPECTED_ABS_MOVE_FACTOR


def _vanna_conditional_reading(
    *,
    iv_30d_delta_5d: Decimal | None,
    directional_imbalance_3d: Decimal | None,
    flow_color: str | None,
    net_gamma_sign: str | None,
) -> Literal["grind_up", "reverse_selloff", "reflexive_sell_pressure", "weak_noise"]:
    if iv_30d_delta_5d is None or net_gamma_sign is None:
        return "weak_noise"
    flow_is_put = flow_color == "put_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d < 0
    )
    flow_is_call = flow_color == "call_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d > 0
    )
    if iv_30d_delta_5d < 0 and flow_is_put and net_gamma_sign == "positive":
        return "grind_up"
    if iv_30d_delta_5d < 0 and flow_is_call and net_gamma_sign == "positive":
        return "reverse_selloff"
    if iv_30d_delta_5d > 0 and flow_is_put and net_gamma_sign == "negative":
        return "reflexive_sell_pressure"
    return "weak_noise"


def _oi_change_bias(
    rows: list[dict],
) -> Literal["call_oi_build", "put_oi_build", "mixed"] | None:
    call_oi = Decimal(0)
    put_oi = Decimal(0)
    for row in rows:
        symbol = str(row.get("option_symbol") or "")
        diff = Decimal(row.get("oi_diff_plain") or 0)
        if "C" in symbol[-9:]:
            call_oi += diff
        elif "P" in symbol[-9:]:
            put_oi += diff
    if call_oi == 0 and put_oi == 0:
        return None
    if call_oi > put_oi:
        return "call_oi_build"
    if put_oi > call_oi:
        return "put_oi_build"
    return "mixed"
