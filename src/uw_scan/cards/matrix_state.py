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


@dataclass(frozen=True)
class MatrixInputs:
    ticker: str
    market_date: date
    vanna_state: MatrixDirection
    charm_state: MatrixDirection
    skew_state: MatrixDirection
    term_state: MatrixDirection
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
    pin_distance_sigma: Decimal | None = None
    vrp_sign_flip_status: bool | Literal["insufficient_history"] = (
        "insufficient_history"
    )
    vrp_sign_flip_aligned_days: int = 0
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

    _ = threshold_version  # TODO(phase-5): persist after migration 023.
    inputs = _read_inputs(repo, ticker=ticker.upper(), market_date=market_date)
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
        pin_distance_sigma=inputs.pin_distance_sigma,
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


def _read_inputs(repo: Repository, *, ticker: str, market_date: date) -> MatrixInputs:
    greeks = repo.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
    exposures = repo.fetch_matrix_exposure_rows(ticker=ticker, market_date=market_date)
    skew_rows = repo.fetch_matrix_skew_history(ticker=ticker, market_date=market_date)
    term_rows = repo.fetch_matrix_term_rows(ticker=ticker, market_date=market_date)
    iv_rows = repo.fetch_matrix_interpolated_iv_history(
        ticker=ticker, market_date=market_date
    )
    rv_rows = repo.fetch_matrix_realized_vol_history(
        ticker=ticker, market_date=market_date
    )
    chain_rows = repo.fetch_matrix_option_chain_rows(
        ticker=ticker, market_date=market_date
    )

    iv_30d = _latest_iv_30d(iv_rows, market_date)
    rv_30d = _latest_rv_30d(rv_rows, market_date)
    spot = _latest_spot(rv_rows, market_date)
    skew_fresh = _has_row_for_date(skew_rows, market_date)
    skew_z = _zscore_for_date(skew_rows, "risk_reversal", market_date, 180)
    vrp, vrp_z = _vrp_values(iv_rows, rv_rows, market_date)
    sign_flip_status, aligned_days = _vrp_sign_flip_status(iv_rows, rv_rows)
    term_state, term_classification, front_iv, back_iv = _term_state(term_rows)
    skew_state = (
        _state_from_z(skew_z, up_state="vol_up", down_state="vol_down")
        if skew_z is not None
        else "neutral"
        if skew_fresh
        else "stale"
    )
    vanna_state = _vanna_state(greeks, exposures)
    charm_state, pin_sigma = _charm_state(
        has_greeks=bool(greeks),
        chain_rows=chain_rows,
        spot=spot,
        rv_30d=rv_30d,
        iv_30d=iv_30d,
        term_state=term_state,
        skew_state=skew_state,
        market_date=market_date,
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
        implied_move_pct=_latest_implied_move_pct(iv_rows, market_date),
        front_iv=front_iv,
        back_iv=back_iv,
        pin_distance_sigma=pin_sigma,
        vrp_sign_flip_status=sign_flip_status,
        vrp_sign_flip_aligned_days=aligned_days,
    )


def _vanna_state(
    greeks: list[dict], exposures: list[dict]
) -> MatrixDirection:
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
) -> tuple[MatrixDirection, Decimal | None]:
    if not has_greeks:
        return "stale", None
    candidate = _nearest_high_oi_strike(chain_rows, spot=spot, market_date=market_date)
    if candidate is None:
        return "neutral", None
    expiry, strike = candidate
    pin_sigma = pin_distance_sigma_v1(spot, strike, rv_30d, (expiry - market_date).days)
    if pin_sigma is None or iv_30d is None:
        return "neutral", pin_sigma
    if pin_sigma < Decimal("1.0") and iv_30d < Decimal("0.35"):
        return "vol_down", pin_sigma
    high_vol = rv_30d is not None and iv_30d > rv_30d * Decimal("1.25")
    if high_vol and (
        term_state == "vol_up" or skew_state == "vol_up" or pin_sigma > Decimal("2.0")
    ):
        return "vol_up", pin_sigma
    return "neutral", pin_sigma


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
        if dte < 0 or dte > 5:
            continue
        if abs(strike - spot) / spot > Decimal("0.02"):
            continue
        oi = (row.get("call_oi") or 0) + (row.get("put_oi") or 0)
        filtered.append((expiry, Decimal(str(strike)), int(oi)))
    if not filtered:
        return None
    nearest_expiry = min(expiry for expiry, _strike, _oi in filtered)
    expiry_rows = [row for row in filtered if row[0] == nearest_expiry]
    expiry, strike, _oi = max(expiry_rows, key=lambda row: (row[2], -abs(row[1] - spot)))
    return expiry, strike


def _term_state(
    rows: list[dict],
) -> tuple[MatrixDirection, str | None, Decimal | None, Decimal | None]:
    if not rows:
        return "stale", None, None, None
    vols = [row for row in rows if row.get("volatility") is not None]
    if len(vols) < 2:
        return "vol_up", "mixed", None, None
    vols = sorted(vols, key=lambda row: (row.get("dte") is None, row.get("dte") or 0))
    front = Decimal(str(vols[0]["volatility"]))
    back = Decimal(str(vols[-1]["volatility"]))
    if front <= back:
        return "vol_down", "contango", front, back
    if back > 0 and front / back >= Decimal("1.15"):
        return "vol_up", "liquidity_back", front, back
    return "vol_down", "event_back", front, back


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
    row = _row_for_date(rows, market_date)
    return None if row is None else row.get("realized_volatility")


def _latest_spot(rows: list[dict], market_date: date) -> Decimal | None:
    row = _row_for_date(rows, market_date)
    return None if row is None else row.get("price")


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
    if len(values) < 2 or not any(row.get("market_date") == market_date for row in rows):
        return None
    mean = sum(values) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    if variance == 0:
        return Decimal(0)
    return (values[-1] - mean) / variance.sqrt()


def _vrp_values(
    iv_rows: list[dict], rv_rows: list[dict], market_date: date
) -> tuple[Decimal | None, Decimal | None]:
    series = _joined_vrp_series(iv_rows, rv_rows)
    current = next((value for day, value in reversed(series) if day == market_date), None)
    if current is None:
        return None, None
    values = [value for day, value in series if day <= market_date][-60:]
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


def _joined_vrp_series(iv_rows: list[dict], rv_rows: list[dict]) -> list[tuple[date, Decimal]]:
    rv_by_day = {
        row.get("market_date"): row.get("realized_volatility")
        for row in rv_rows
        if row.get("market_date") is not None
    }
    series = []
    for row in iv_rows:
        day = row.get("market_date")
        iv = row.get("volatility")
        rv = rv_by_day.get(day)
        if day is None or iv is None or rv is None:
            continue
        series.append((day, Decimal(str(iv)) - Decimal(str(rv))))
    return sorted(series, key=lambda item: item[0])
