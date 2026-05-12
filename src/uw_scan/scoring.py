"""Setup classification for Single-Stock Card.

S1 implements Type C (Deep Conviction Directional) only.

Criteria (from S1 plan + spec):
- Net premium magnitude ≥ NET_PREMIUM_THRESHOLD ($5M default)
- For bull: IV rank ≥ IV_RANK_HIGH (70) — vol mean-reversion + directional
- For bear: IV rank ≤ IV_RANK_LOW (30)
- At least one corroborating signal:
  - Dark pool notional > DARK_POOL_NOTIONAL_THRESHOLD
  - ATM call/put OI build present in oi_change top movers

Returns SetupClassification (typed) or None.
"""

from __future__ import annotations

from decimal import Decimal

from .models import SetupClassification, SingleStockReport

NET_PREMIUM_THRESHOLD = Decimal("5000000")  # $5M
IV_RANK_HIGH = Decimal("70")
IV_RANK_LOW = Decimal("30")
DARK_POOL_NOTIONAL_THRESHOLD = Decimal("100000000")  # $100M
MIN_OI_BUILD_COUNT = 1


def _direction_from_flow(net_premium: Decimal) -> str:
    return "bull" if net_premium >= 0 else "bear"


def classify_setup_c(report: SingleStockReport) -> SetupClassification | None:
    """Classify the report as Type C (Deep Conviction) if criteria met. Else None."""
    net_premium = report.flow.net_premium
    abs_net = abs(net_premium)
    iv_rank = report.volatility.iv_rank
    confirmations: list[str] = []
    warnings: list[str] = []

    if abs_net < NET_PREMIUM_THRESHOLD:
        return None

    direction = _direction_from_flow(net_premium)

    if iv_rank is None:
        warnings.append("iv_rank unavailable")
        # Don't classify without IV rank
        return None

    if direction == "bull" and iv_rank < IV_RANK_HIGH:
        return None
    if direction == "bear" and iv_rank > IV_RANK_LOW:
        return None

    confirmations.append(f"net premium = ${abs_net:,.0f} ({direction})")
    confirmations.append(f"iv_rank = {iv_rank}")

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
    ivr_score = Decimal("0")
    if direction == "bull":
        ivr_score = (iv_rank - IV_RANK_HIGH) / Decimal("30") * Decimal("1")
    else:
        ivr_score = (IV_RANK_LOW - iv_rank) / Decimal("30") * Decimal("1")
    ivr_score = max(Decimal("0"), min(Decimal("1"), ivr_score))
    corr_score = Decimal("1") if corroborated else Decimal("0")

    raw = premium_score + ivr_score + corr_score
    score = min(Decimal("5"), max(Decimal("0"), raw))

    return SetupClassification(
        setup_type="C",
        label="Deep Conviction",
        direction=direction,
        score=score,
        confirmations=confirmations,
        warnings=warnings,
        notes=(
            f"Type C: |net premium| ≥ ${NET_PREMIUM_THRESHOLD:,.0f}, IV rank "
            f"thresholds met for {direction}, corroborated by "
            f"{'dark pool' if report.dark_pool_notional and report.dark_pool_notional >= DARK_POOL_NOTIONAL_THRESHOLD else 'OI build'}."
        ),
    )
