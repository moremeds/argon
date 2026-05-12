"""Setup classification for Single-Stock Card (Type C) and Full Scan (Type F).

Type C — Deep Conviction Directional (S1, single-stock context):
- Net premium magnitude ≥ NET_PREMIUM_THRESHOLD ($5M default)
- For bull: IV rank ≥ IV_RANK_HIGH (70) — vol mean-reversion + directional
- For bear: IV rank ≤ IV_RANK_LOW (30)
- ≥ 1 corroborating signal (dark pool size, OI build)

Type F — Multi-Signal Confluence (S2, scan-row context):
- Base: same flow + IV-rank gate as Type C
- PLUS ≥ 2 of: GEX-vs-OI shift, VRP magnitude, relative volume, flow polarization

F takes precedence over C in the scan context.
"""

from __future__ import annotations

from decimal import Decimal

from .models import BulkScreenerRow, SetupClassification, SingleStockReport

NET_PREMIUM_THRESHOLD = Decimal("5000000")  # $5M
IV_RANK_HIGH = Decimal("70")
IV_RANK_LOW = Decimal("30")
DARK_POOL_NOTIONAL_THRESHOLD = Decimal("100000000")  # $100M
MIN_OI_BUILD_COUNT = 1

# Type F (multi-signal) thresholds — see plan §Setup Type F.
F_GEX_OI_RATIO_THRESHOLD = Decimal("0.01")
F_VRP_MAGNITUDE_THRESHOLD = Decimal("0.05")
F_RELATIVE_VOLUME_THRESHOLD = Decimal("1.5")
F_FLOW_POLARIZATION_THRESHOLD = Decimal("50000000")  # $50M
F_MIN_SIGNALS = 2


def _direction_from_flow(net_premium: Decimal) -> str:
    return "bull" if net_premium >= 0 else "bear"


def _row_net_premium(row: BulkScreenerRow) -> Decimal | None:
    """Combine net_call_premium + net_put_premium into a single net signed value.

    UW reports `net_call_premium` (positive when call buying dominates) and
    `net_put_premium` (positive when put buying dominates). Net premium for
    direction = net_call_premium - net_put_premium.
    """
    ncp = row.net_call_premium
    npp = row.net_put_premium
    if ncp is None and npp is None:
        return None
    ncp = ncp if ncp is not None else Decimal("0")
    npp = npp if npp is not None else Decimal("0")
    return ncp - npp


def _check_c_base(row: BulkScreenerRow) -> tuple[bool, str | None, list[str]]:
    """Check whether a screener row meets Type C base criteria.

    Returns (ok, direction, confirmations). When ok is False, direction may still
    be set but confirmations is empty.
    """
    net_premium = _row_net_premium(row)
    if net_premium is None:
        return False, None, []
    abs_net = abs(net_premium)
    if abs_net < NET_PREMIUM_THRESHOLD:
        return False, None, []
    direction = _direction_from_flow(net_premium)
    iv_rank = row.iv_rank
    if iv_rank is None:
        return False, direction, []
    if direction == "bull" and iv_rank < IV_RANK_HIGH:
        return False, direction, []
    if direction == "bear" and iv_rank > IV_RANK_LOW:
        return False, direction, []
    confirmations = [
        f"net premium = ${abs_net:,.0f} ({direction})",
        f"iv_rank = {iv_rank}",
    ]
    return True, direction, confirmations


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


def detect_f_signals(row: BulkScreenerRow) -> list[str]:
    """Return the list of corroborating signals present on the screener row.

    Signals checked (per plan §Setup Type F):
      1. abs(gex_net_change) / total_open_interest > F_GEX_OI_RATIO_THRESHOLD
      2. abs(variance_risk_premium) > F_VRP_MAGNITUDE_THRESHOLD
      3. relative_volume > F_RELATIVE_VOLUME_THRESHOLD
      4. abs(net_call_premium - net_put_premium) > F_FLOW_POLARIZATION_THRESHOLD
    """
    signals: list[str] = []

    if (
        row.gex_net_change is not None
        and row.total_open_interest is not None
        and row.total_open_interest > 0
    ):
        ratio = abs(row.gex_net_change) / Decimal(row.total_open_interest)
        if ratio > F_GEX_OI_RATIO_THRESHOLD:
            signals.append(f"gex_oi_shift={ratio:.4f}")

    if (
        row.variance_risk_premium is not None
        and abs(row.variance_risk_premium) > F_VRP_MAGNITUDE_THRESHOLD
    ):
        signals.append(f"vrp_anomaly={row.variance_risk_premium}")

    if (
        row.relative_volume is not None
        and row.relative_volume > F_RELATIVE_VOLUME_THRESHOLD
    ):
        signals.append(f"relative_volume={row.relative_volume}")

    polarization = _row_net_premium(row)
    if polarization is not None and abs(polarization) > F_FLOW_POLARIZATION_THRESHOLD:
        signals.append(f"flow_polarization=${abs(polarization):,.0f}")

    return signals


def classify_setup_f(row: BulkScreenerRow) -> SetupClassification | None:
    """Classify a scan-row as Type F (Multi-Signal Confluence). Else None.

    F = Type C base + ≥ F_MIN_SIGNALS corroborating signals. F takes precedence
    over C in the scan context — callers should call this BEFORE the C-only
    fallback when ranking screener rows.
    """
    ok, direction, confirmations = _check_c_base(row)
    if not ok or direction is None:
        return None

    signals = detect_f_signals(row)
    if len(signals) < F_MIN_SIGNALS:
        return None

    # Score: blend net-premium magnitude, IV-rank distance, and signal count.
    net_premium = _row_net_premium(row) or Decimal("0")
    abs_net = abs(net_premium)
    iv_rank = row.iv_rank or Decimal("0")

    premium_score = min(Decimal("2"), abs_net / Decimal("100000000") * Decimal("2"))
    if direction == "bull":
        ivr_score = (iv_rank - IV_RANK_HIGH) / Decimal("30") * Decimal("1")
    else:
        ivr_score = (IV_RANK_LOW - iv_rank) / Decimal("30") * Decimal("1")
    ivr_score = max(Decimal("0"), min(Decimal("1"), ivr_score))
    signal_score = min(Decimal("2"), Decimal(len(signals)) * Decimal("0.5"))

    raw = premium_score + ivr_score + signal_score + Decimal("1")  # +1 base for F
    score = min(Decimal("6"), max(Decimal("0"), raw))

    confs = list(confirmations) + [f"{len(signals)} corroborating signals: {signals}"]

    return SetupClassification(
        setup_type="F",
        label="Multi-Signal Confluence",
        direction=direction,
        score=score,
        confirmations=confs,
        warnings=[],
        notes=(
            f"Type F: Type C base met ({direction}), plus {len(signals)} of 4 "
            f"corroborating signals (need ≥ {F_MIN_SIGNALS})."
        ),
    )


def classify_setup_c_from_row(row: BulkScreenerRow) -> SetupClassification | None:
    """Type C classification on a screener row (no per-ticker deep dive).

    Used in the Full Scan as the fallback when Type F doesn't qualify. Scan-row
    Type C does NOT check dark pool / OI build (those are S3 fanout); the C
    base check (premium + IV rank) is sufficient at the scan level.
    """
    ok, direction, confirmations = _check_c_base(row)
    if not ok or direction is None:
        return None

    net_premium = _row_net_premium(row) or Decimal("0")
    abs_net = abs(net_premium)
    iv_rank = row.iv_rank or Decimal("0")

    premium_score = min(Decimal("3"), abs_net / Decimal("100000000") * Decimal("3"))
    if direction == "bull":
        ivr_score = (iv_rank - IV_RANK_HIGH) / Decimal("30") * Decimal("1")
    else:
        ivr_score = (IV_RANK_LOW - iv_rank) / Decimal("30") * Decimal("1")
    ivr_score = max(Decimal("0"), min(Decimal("1"), ivr_score))

    raw = premium_score + ivr_score
    score = min(Decimal("4"), max(Decimal("0"), raw))

    return SetupClassification(
        setup_type="C",
        label="Deep Conviction",
        direction=direction,
        score=score,
        confirmations=confirmations,
        warnings=[],
        notes=(
            f"Type C (scan-row): |net premium| ≥ ${NET_PREMIUM_THRESHOLD:,.0f}, "
            f"IV rank gate met for {direction}."
        ),
    )
