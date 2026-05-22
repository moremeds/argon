"""Master derivation: SingleStockReport + OHLC history + intraday + prior PCR
→ a complete watchlist_card row dict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from uw_scan.cards import gex as _gex
from uw_scan.cards.aggression import compute_aggression_pct
from uw_scan.cards.pcr import compute_pcr_delta_30d
from uw_scan.cards.returns import compute_returns
from uw_scan.models import SingleStockReport
from uw_scan.sources.ohlc import OhlcBar
from uw_scan.storage.repository import IntradayQuoteRow, PcrHistoryRow


def compute_watchlist_card_row(
    report: SingleStockReport,
    ohlc_history: list[OhlcBar],
    intraday: IntradayQuoteRow | None,
    prior_pcr: PcrHistoryRow | None,
) -> dict[str, Any]:
    # When an intraday quote exists, use its persisted source label
    # ("massive.com_ws" under the live WS pipeline, or "massive.com_intraday"
    # legacy) rather than a hardcoded literal — keeps the dashboard label
    # truthful about which writer produced the spot.
    spot = intraday.price if intraday is not None else report.market_structure.spot
    spot_source = intraday.source if intraday is not None else "uw_scan"
    spot_quoted_at = intraday.quoted_at if intraday is not None else report.generated_at

    returns = compute_returns(ohlc_history, intraday.price if intraday else None)
    flip_strike = _gex.find_flip_strike(report.strike_gex_curve)
    flip_distance = (
        (flip_strike - spot) / spot if (flip_strike is not None and spot) else None
    )
    per_1pct = (
        report.market_structure.net_gex * Decimal("0.01") * spot
        if report.market_structure.net_gex is not None and spot is not None
        else None
    )
    nearest = _gex.nearest_expiry(report.strike_gex_curve)

    agg = report.aggregates

    return {
        "ticker": report.ticker,
        "run_id": report.run_id,
        "scanned_at": report.generated_at,
        "spot": spot,
        "spot_quoted_at": spot_quoted_at,
        "spot_source": spot_source,
        "iv_atm": report.volatility.iv,
        "iv_rank": report.volatility.iv_rank,
        "setup_type": report.setup.setup_type if report.setup else None,
        "setup_direction": report.setup.direction if report.setup else None,
        "setup_score": report.setup.score if report.setup else None,
        "aggression_pct": compute_aggression_pct(report.flow),
        "ret_1d": returns.ret_1d,
        "ret_1w": returns.ret_1w,
        "ret_30d": returns.ret_30d,
        "gex_flip_distance": flip_distance,
        "gex_flip_price": flip_strike,
        "gex_per_1pct_move": per_1pct,
        "max_gex_strike": _gex.max_gex_strike(report.strike_gex_curve),
        "gex_expiring_pct": _gex.gex_expiring_pct(report.strike_gex_curve),
        "gex_expiring_date": nearest,
        "skew_25d_30dte": report.volatility.skew_25d,
        "call_oi_total": agg.call_oi_total if agg else None,
        "put_oi_total": agg.put_oi_total if agg else None,
        "pcr_oi": agg.pcr_oi if agg else None,
        "pcr_vol": agg.pcr_vol if agg else None,
        "pcr_delta_30d": (
            compute_pcr_delta_30d(agg.pcr_oi, prior_pcr.pcr_oi)
            if agg and prior_pcr
            else None
        ),
    }
