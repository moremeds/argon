"""Setup classification for Single-Stock Card (Type C).

Type C — Deep Conviction Directional (S1, single-stock context):
- Net premium magnitude ≥ NET_PREMIUM_THRESHOLD ($5M default)
- Direction is determined by signed option flow, not IV rank
- Flow imbalance must be material versus total observed option premium
- ≥ 1 corroborating signal (dark pool size, OI build)
"""

from __future__ import annotations

from decimal import Decimal

from .models import SetupClassification, SingleStockReport

NET_PREMIUM_THRESHOLD = Decimal("5000000")  # $5M
FLOW_IMBALANCE_THRESHOLD = Decimal("0.20")
DARK_POOL_NOTIONAL_THRESHOLD = Decimal("100000000")  # $100M
MIN_OI_BUILD_COUNT = 1


def _direction_from_flow(net_premium: Decimal) -> str:
    return "bull" if net_premium >= 0 else "bear"


def _flow_imbalance(net_premium: Decimal, total_premium: Decimal | None) -> Decimal | None:
    if total_premium is None:
        return None
    total = abs(total_premium)
    if total <= 0:
        return None
    return abs(net_premium) / total


def _flow_context(
    *,
    net_premium: Decimal,
    total_premium: Decimal | None,
    iv_rank: Decimal | None,
) -> tuple[bool, list[str], list[str], Decimal]:
    confirmations = [
        f"net premium = ${abs(net_premium):,.0f} "
        f"({_direction_from_flow(net_premium)})"
    ]
    warnings: list[str] = []

    imbalance = _flow_imbalance(net_premium, total_premium)
    if imbalance is not None:
        confirmations.append(f"flow imbalance = {imbalance:.2%}")
        if imbalance < FLOW_IMBALANCE_THRESHOLD:
            return False, confirmations, warnings, imbalance
    else:
        warnings.append("flow premium denominator unavailable; imbalance gate skipped")
        imbalance = Decimal("0")

    if iv_rank is None:
        warnings.append("iv_rank unavailable; direction uses flow, not IV rank")
    else:
        confirmations.append(f"iv_rank = {iv_rank} (structure context only)")

    return True, confirmations, warnings, imbalance


def classify_setup_c(report: SingleStockReport) -> SetupClassification | None:
    """Classify the report as Type C (Deep Conviction) if criteria met. Else None."""
    net_premium = report.flow.net_premium
    abs_net = abs(net_premium)

    if abs_net < NET_PREMIUM_THRESHOLD:
        return None

    direction = _direction_from_flow(net_premium)
    ok, confirmations, warnings, imbalance = _flow_context(
        net_premium=net_premium,
        total_premium=report.flow.bull_premium + report.flow.bear_premium,
        iv_rank=report.volatility.iv_rank,
    )
    if not ok:
        return None

    # At least one corroborating signal
    corroborated = False
    if (
        report.dark_pool_notional is not None
        and report.dark_pool_notional >= DARK_POOL_NOTIONAL_THRESHOLD
    ):
        confirmations.append(
            f"dark pool notional ${report.dark_pool_notional:,.0f} ≥ "
            f"threshold ${DARK_POOL_NOTIONAL_THRESHOLD:,.0f}"
        )
        corroborated = True

    if len(report.oi_change_top) >= MIN_OI_BUILD_COUNT:
        confirmations.append(
            f"{len(report.oi_change_top)} top OI-change movers present"
        )
        corroborated = True

    if not corroborated:
        return None

    # Score: weighted blend, capped at 5.0
    premium_score = min(Decimal("3"), abs_net / Decimal("100000000") * Decimal("3"))
    flow_score = max(Decimal("0"), min(Decimal("1"), imbalance))
    corr_score = Decimal("1") if corroborated else Decimal("0")

    raw = premium_score + flow_score + corr_score
    score = min(Decimal("5"), max(Decimal("0"), raw))

    return SetupClassification(
        setup_type="C",
        label="Deep Conviction",
        direction=direction,
        score=score,
        confirmations=confirmations,
        warnings=warnings,
        notes=(
            f"Type C: |net premium| ≥ ${NET_PREMIUM_THRESHOLD:,.0f}, "
            f"flow imbalance ≥ {FLOW_IMBALANCE_THRESHOLD:.0%} for {direction}, "
            f"corroborated by "
            f"{'dark pool' if report.dark_pool_notional and report.dark_pool_notional >= DARK_POOL_NOTIONAL_THRESHOLD else 'OI build'}."
        ),
    )
