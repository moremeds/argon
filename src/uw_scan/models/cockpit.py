"""Index dealer cockpit contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from ._base import _preserve_public_module, CharmRegime, FlowFootprintLabel, VannaConditionalReading, _UwBase
from .matrix import MatrixSourceFreshness, MatrixState


class CockpitStateResponse(_UwBase):
    state: MatrixState
    freshness: MatrixSourceFreshness

class CockpitDealerPoint(_UwBase):
    expiry: _date
    strike: Decimal
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None
    exposure_call_vanna: Decimal | None = None
    exposure_put_vanna: Decimal | None = None
    exposure_call_charm: Decimal | None = None
    exposure_put_charm: Decimal | None = None

class CockpitDealerMetrics(_UwBase):
    pin_candidate_strike: Decimal | None = None
    pin_candidate_expiry: _date | None = None
    pin_source_date: _date | None = None
    pin_distance_sigma: Decimal | None = None
    pin_regime_flag: bool | None = None
    dealer_net_vanna_proxy: Decimal | None = None
    dealer_net_charm_proxy: Decimal | None = None
    flow_color_lookback_3d: Literal["put_heavy", "call_heavy", "neutral"] | None = None
    flow_put_premium_3d: Decimal | None = None
    flow_call_premium_3d: Decimal | None = None
    iv_30d_delta_5d: Decimal | None = None
    net_gamma: Decimal | None = None
    net_gamma_sign: Literal["positive", "negative", "neutral"] | None = None
    gamma_regime: Literal["long_gamma", "short_gamma", "neutral"] | None = None
    vanna_conditional_reading: VannaConditionalReading | None = None
    directional_imbalance_3d: Decimal | None = None
    vanna_oi_change_bias: Literal["call_oi_build", "put_oi_build", "mixed"] | None = (
        None
    )
    charm_regime: CharmRegime | None = None
    charm_stress_override: bool | None = None

class VannaSignal(_UwBase):
    ticker: str
    market_date: _date
    dealer_net_vanna_proxy: Decimal | None = None
    flow_color_lookback_3d: Literal["put_heavy", "call_heavy", "neutral"] | None = None
    flow_put_premium_3d: Decimal | None = None
    flow_call_premium_3d: Decimal | None = None
    iv_30d_delta_5d: Decimal | None = None
    vanna_conditional_reading: VannaConditionalReading | None = None
    directional_imbalance_3d: Decimal | None = None
    vanna_oi_change_bias: Literal["call_oi_build", "put_oi_build", "mixed"] | None = (
        None
    )
    generated_at: datetime | None = None
    inserted_at: datetime | None = None

class CharmSignal(_UwBase):
    ticker: str
    market_date: _date
    pin_candidate_strike: Decimal | None = None
    pin_candidate_expiry: _date | None = None
    pin_source_date: _date | None = None
    pin_distance_sigma: Decimal | None = None
    pin_regime_flag: bool | None = None
    dealer_net_charm_proxy: Decimal | None = None
    net_gamma: Decimal | None = None
    net_gamma_sign: Literal["positive", "negative", "neutral"] | None = None
    gamma_regime: Literal["long_gamma", "short_gamma", "neutral"] | None = None
    charm_regime: CharmRegime | None = None
    charm_stress_override: bool | None = None
    generated_at: datetime | None = None
    inserted_at: datetime | None = None

class CockpitDealerResponse(_UwBase):
    ticker: str
    market_date: _date
    metrics: CockpitDealerMetrics = Field(default_factory=CockpitDealerMetrics)
    points: list[CockpitDealerPoint] = Field(default_factory=list)

class CockpitSkewPoint(_UwBase):
    market_date: _date
    expiry: _date | None = None
    risk_reversal: Decimal | None = None

class CockpitTermPoint(_UwBase):
    expiry: _date
    dte: int | None = None
    volatility: Decimal | None = None
    implied_move_perc: Decimal | None = None
    implied_move_expected_abs: Decimal | None = None

class CockpitSurfaceResponse(_UwBase):
    ticker: str
    market_date: _date
    skew: list[CockpitSkewPoint] = Field(default_factory=list)
    term: list[CockpitTermPoint] = Field(default_factory=list)

class CockpitFlowAlert(_UwBase):
    alert_id: str
    option_chain: str | None = None
    expiry: _date | None = None
    strike: Decimal | None = None
    option_type: str | None = None
    total_premium: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    total_ask_side_prem: Decimal | None = None
    total_bid_side_prem: Decimal | None = None
    has_sweep: bool | None = None
    has_floor: bool | None = None
    has_multileg: bool | None = None
    all_opening_trades: bool | None = None
    alert_rule: str | None = None
    flow_footprint_label: FlowFootprintLabel | None = None
    aggressor_label_confidence: Decimal | None = None
    created_at: datetime | None = None

class CockpitImPoint(_UwBase):
    market_date: _date
    days: int
    volatility: Decimal | None = None
    implied_move_perc: Decimal | None = None
    implied_move_expected_abs: Decimal | None = None
    percentile: Decimal | None = None

class CockpitFlowImResponse(_UwBase):
    ticker: str
    market_date: _date
    alerts: list[CockpitFlowAlert] = Field(default_factory=list)
    implied_moves: list[CockpitImPoint] = Field(default_factory=list)

class CockpitVrpPoint(_UwBase):
    market_date: _date
    iv: Decimal | None = None
    rv: Decimal | None = None
    vrp: Decimal | None = None
    iv_rank_1y: Decimal | None = None

class CockpitVrpResponse(_UwBase):
    ticker: str
    market_date: _date
    points: list[CockpitVrpPoint] = Field(default_factory=list)


_preserve_public_module(
    CockpitStateResponse,
    CockpitDealerPoint,
    CockpitDealerMetrics,
    VannaSignal,
    CharmSignal,
    CockpitDealerResponse,
    CockpitSkewPoint,
    CockpitTermPoint,
    CockpitSurfaceResponse,
    CockpitFlowAlert,
    CockpitImPoint,
    CockpitFlowImResponse,
    CockpitVrpPoint,
    CockpitVrpResponse,
)
