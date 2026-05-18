"""Matrix-state contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal
from typing import Literal

from ._base import (
    CharmRegime,
    MatrixConsistencyTier,
    MatrixDirection,
    SkewRegime,
    VannaConditionalReading,
    _UwBase,
    _preserve_public_module,
)


class SetupClassification(_UwBase):
    setup_type: str  # "C"
    label: str  # "Deep Conviction"
    direction: str  # "bull" / "bear"
    score: Decimal
    confirmations: list[str] = []
    warnings: list[str] = []
    notes: str = ""

class MatrixState(_UwBase):
    ticker: str
    market_date: _date
    threshold_version: int = 1
    vanna_state: MatrixDirection
    charm_state: MatrixDirection
    skew_state: MatrixDirection
    term_state: MatrixDirection
    im_state: MatrixDirection
    flow_state: MatrixDirection
    vrp_state: MatrixDirection
    consistency_tier: MatrixConsistencyTier
    cluster_coverage_ok: bool
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
    vanna_conditional_reading: VannaConditionalReading | None = None
    directional_imbalance_3d: Decimal | None = None
    vanna_oi_change_bias: Literal["call_oi_build", "put_oi_build", "mixed"] | None = (
        None
    )
    charm_regime: CharmRegime | None = None
    charm_stress_override: bool = False
    skew_25d_5d_change: Decimal | None = None
    skew_regime: SkewRegime | None = None
    skew_term_structure: Decimal | None = None
    single_point_bump_pct: Decimal | None = None
    full_curve_slope_pct: Decimal | None = None
    term_johnson_slope_pc1: Decimal | None = None
    atm_straddle_mid: Decimal | None = None
    implied_move_expected_abs: Decimal | None = None
    implied_move_event_percentile: Decimal | None = None
    vrp_zscore_252d: Decimal | None = None

class MatrixSourceFreshness(_UwBase):
    vanna_charm: datetime | None = None
    skew: datetime | None = None
    term: datetime | None = None
    im_vrp: datetime | None = None
    vrp_rv: datetime | None = None
    oi: datetime | None = None


_preserve_public_module(
    SetupClassification,
    MatrixState,
    MatrixSourceFreshness,
)
