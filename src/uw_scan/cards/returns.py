"""Return calculations for the watchlist card."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from uw_scan.sources.ohlc import OhlcBar


@dataclass(frozen=True)
class Returns:
    ret_1d: Decimal | None
    ret_1w: Decimal | None
    ret_30d: Decimal | None


def compute_returns(history: list[OhlcBar], price: Decimal | None) -> Returns:
    """1-day / 1-week (5 trading days) / 30-day (21 trading days) returns.

    `history` is sorted ascending by date inside. When `price` is None we fall
    back to close-to-close: treat the most recent close as today's price and
    use the second-most-recent as the 1d reference.
    """
    sorted_hist = sorted(history, key=lambda b: b.date)
    n = len(sorted_hist)
    if n == 0:
        return Returns(None, None, None)
    if price is None:
        # close-to-close mode: drop last element, recurse with last_close as "today"
        last_close = sorted_hist[-1].close
        return compute_returns(sorted_hist[:-1], last_close)

    def _ret(lookback: int) -> Decimal | None:
        idx = n - lookback
        if idx < 0 or idx >= n:
            return None
        ref = sorted_hist[idx].close
        if ref == 0:
            return None
        return (price - ref) / ref

    return Returns(ret_1d=_ret(1), ret_1w=_ret(5), ret_30d=_ret(21))
