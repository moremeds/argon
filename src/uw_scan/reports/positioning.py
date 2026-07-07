"""Positioning report assembler — banked `uw_positioning` row → response models.

Pure functions over the stored column dict (plus a spot price for implied
upside). No UW calls, no DB writes. Signal thresholds live here as module
constants so the card, screener, and any test share one source of truth.

Units (from migration 065 / observed UW payloads):
- ``si_pct_float``   fraction (0.47 == 47% of float short)
- ``si_days_to_cover`` raw days
- ``si_fee_rate``   annualized borrow fee, percent (2.80 == 2.8%)
- ``insider_net_flow`` UW dollar net-flow convention (sign = tilt)

Squeeze is scored off *absolute current levels* only — there is no banked
history to measure a fee-rate *spike* against. Spike-vs-baseline is a
documented follow-up (needs a rolling `uw_positioning` read).
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    PositioningScreenerRow,
    PositioningSignals,
    PositioningSnapshot,
)

# Squeeze scoring: each dimension contributes 0 (below), 1 (elevated), 2 (high).
# Total 0-6. Grounded in common short-squeeze desk heuristics, not fitted.
_SI_PCT_ELEVATED = Decimal("0.10")  # 10% of float short
_SI_PCT_HIGH = Decimal("0.20")  # 20% of float short
_DTC_ELEVATED = Decimal("3")  # 3 days to cover
_DTC_HIGH = Decimal("5")
_FEE_ELEVATED = Decimal("1.0")  # 1% annualized borrow fee
_FEE_HIGH = Decimal("5.0")  # 5% == hard-to-borrow


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _tier_points(value: Decimal | None, elevated: Decimal, high: Decimal) -> int:
    if value is None:
        return 0
    if value >= high:
        return 2
    if value >= elevated:
        return 1
    return 0


def _squeeze(
    si_pct_float: Decimal | None,
    days_to_cover: Decimal | None,
    fee_rate: Decimal | None,
) -> tuple[int | None, str]:
    """Composite squeeze score (0-6) + label. None score if no inputs at all."""
    if si_pct_float is None and days_to_cover is None and fee_rate is None:
        return None, "unknown"
    score = (
        _tier_points(si_pct_float, _SI_PCT_ELEVATED, _SI_PCT_HIGH)
        + _tier_points(days_to_cover, _DTC_ELEVATED, _DTC_HIGH)
        + _tier_points(fee_rate, _FEE_ELEVATED, _FEE_HIGH)
    )
    if score >= 4:
        label = "HIGH"
    elif score >= 2:
        label = "ELEVATED"
    else:
        label = "LOW"
    return score, label


def _insider_tilt(net_flow: Decimal | None) -> str:
    if net_flow is None:
        return "unknown"
    if net_flow > 0:
        return "BUYING"
    if net_flow < 0:
        return "SELLING"
    return "NEUTRAL"


def _implied_upside_pct(
    target_avg: Decimal | None, spot: Decimal | None
) -> Decimal | None:
    if target_avg is None or spot is None or spot == 0:
        return None
    return (target_avg - spot) / spot * Decimal("100")


def _rating_skew(buy: int | None, hold: int | None, sell: int | None) -> Decimal | None:
    b, h, s = buy or 0, hold or 0, sell or 0
    total = b + h + s
    if total == 0:
        return None
    return (Decimal(b) - Decimal(s)) / Decimal(total)


def _er_base_rate(positive: int | None, total: int | None) -> Decimal | None:
    if not total:
        return None
    return Decimal(positive or 0) / Decimal(total)


def _days_to_er(next_er: _date | None, as_of: _date | None) -> int | None:
    if next_er is None or as_of is None:
        return None
    return (next_er - as_of).days


def build_signals(row: dict[str, Any], spot: Decimal | None) -> PositioningSignals:
    as_of = row.get("snapshot_date")
    score, label = _squeeze(
        _dec(row.get("si_pct_float")),
        _dec(row.get("si_days_to_cover")),
        _dec(row.get("si_fee_rate")),
    )
    return PositioningSignals(
        squeeze_score=score,
        squeeze_label=label,
        insider_tilt=_insider_tilt(_dec(row.get("insider_net_flow"))),
        analyst_implied_upside_pct=_implied_upside_pct(
            _dec(row.get("analyst_target_avg")), spot
        ),
        analyst_rating_skew=_rating_skew(
            row.get("analyst_buy"), row.get("analyst_hold"), row.get("analyst_sell")
        ),
        er_positive_base_rate=_er_base_rate(
            row.get("earn_reactions_positive"), row.get("earn_reactions_total")
        ),
        days_to_next_er=_days_to_er(row.get("next_er_date"), as_of),
    )


def build_snapshot(
    ticker: str, row: dict[str, Any] | None, spot: Decimal | None
) -> PositioningSnapshot:
    if row is None:
        return PositioningSnapshot(ticker=ticker.upper(), available=False, spot=spot)
    return PositioningSnapshot(
        ticker=ticker.upper(),
        available=True,
        snapshot_date=row.get("snapshot_date"),
        spot=spot,
        si_pct_float=_dec(row.get("si_pct_float")),
        si_short_interest=_dec(row.get("si_short_interest")),
        si_total_float=_dec(row.get("si_total_float")),
        si_days_to_cover=_dec(row.get("si_days_to_cover")),
        si_shares_available=_dec(row.get("si_shares_available")),
        si_fee_rate=_dec(row.get("si_fee_rate")),
        si_rebate_rate=_dec(row.get("si_rebate_rate")),
        si_market_date=row.get("si_market_date"),
        analyst_buy=row.get("analyst_buy"),
        analyst_hold=row.get("analyst_hold"),
        analyst_sell=row.get("analyst_sell"),
        analyst_target_avg=_dec(row.get("analyst_target_avg")),
        analyst_target_hi=_dec(row.get("analyst_target_hi")),
        analyst_target_lo=_dec(row.get("analyst_target_lo")),
        inst_holder_count=row.get("inst_holder_count"),
        inst_total_value=_dec(row.get("inst_total_value")),
        insider_buy_volume=_dec(row.get("insider_buy_volume")),
        insider_sell_volume=_dec(row.get("insider_sell_volume")),
        insider_net_flow=_dec(row.get("insider_net_flow")),
        earn_reactions_positive=row.get("earn_reactions_positive"),
        earn_reactions_total=row.get("earn_reactions_total"),
        next_er_date=row.get("next_er_date"),
        signals=build_signals(row, spot),
    )


def build_screener_row(row: dict[str, Any]) -> PositioningScreenerRow:
    """Row already carries a joined ``spot`` column from the screener query."""
    spot = _dec(row.get("spot"))
    sig = build_signals(row, spot)
    return PositioningScreenerRow(
        ticker=str(row["ticker"]).upper(),
        snapshot_date=row.get("snapshot_date"),
        spot=spot,
        si_pct_float=_dec(row.get("si_pct_float")),
        si_days_to_cover=_dec(row.get("si_days_to_cover")),
        si_fee_rate=_dec(row.get("si_fee_rate")),
        squeeze_score=sig.squeeze_score,
        squeeze_label=sig.squeeze_label,
        insider_net_flow=_dec(row.get("insider_net_flow")),
        insider_tilt=sig.insider_tilt,
        analyst_implied_upside_pct=sig.analyst_implied_upside_pct,
        er_positive_base_rate=sig.er_positive_base_rate,
        days_to_next_er=sig.days_to_next_er,
    )
