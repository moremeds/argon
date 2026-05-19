"""Pure derivation of the OI movers TAPE view from per-minute intraday bars.

Input: bucket dicts returned by ``OptionIntradayBucketRepository.fetch_buckets``.
Output: :class:`OptionIntradayProfile`. No DB / IO.

Volume here is side-aggregated (ask + bid + mid + multi). UW's intraday
endpoint publishes per-minute bars; we roll a 30-minute wall-clock window
to find the peak and downsample to a fixed 12-bucket sparkline so the UI
renders a stable width regardless of how many minute bars came back.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal
from typing import Any

from ..models import OptionIntradayProfile

logger = logging.getLogger(__name__)

DEFAULT_PEAK_WINDOW = timedelta(minutes=30)
DEFAULT_SPARKLINE_BUCKETS = 12


def _bucket_total_volume(bucket: dict[str, Any]) -> int:
    return (
        (bucket.get("volume_ask_side") or 0)
        + (bucket.get("volume_bid_side") or 0)
        + (bucket.get("volume_mid_side") or 0)
        + (bucket.get("volume_multi") or 0)
    )


def derive_intraday_profile(
    *,
    option_symbol: str,
    trade_date: _date,
    buckets: list[dict[str, Any]],
    peak_window: timedelta = DEFAULT_PEAK_WINDOW,
    sparkline_buckets: int = DEFAULT_SPARKLINE_BUCKETS,
) -> OptionIntradayProfile:
    """Derive the TAPE view from per-minute intraday bars.

    Returns an :class:`OptionIntradayProfile` with zero ``total_volume`` and
    ``None`` timestamps when no bucket contains non-zero side volume — the
    common case for deep OTM contracts whose OI built on a single block
    print outside the captured intraday window.
    """
    profile = OptionIntradayProfile(
        option_symbol=option_symbol,
        trade_date=trade_date,
    )

    if not buckets:
        return profile

    sorted_buckets = sorted(buckets, key=lambda b: b["start_time"])
    per_bucket_volume = [_bucket_total_volume(b) for b in sorted_buckets]
    total_volume = sum(per_bucket_volume)
    profile.total_volume = total_volume
    if total_volume <= 0:
        return profile

    non_zero_indices = [i for i, v in enumerate(per_bucket_volume) if v > 0]
    if non_zero_indices:
        profile.first_trade_time = sorted_buckets[non_zero_indices[0]]["start_time"]
        profile.last_trade_time = sorted_buckets[non_zero_indices[-1]]["start_time"]

    # Sliding wall-clock window. Invariant: j is the first index past the
    # right edge of the window anchored at i, so the running sum covers
    # buckets [i, j). When i advances by one, drop per_bucket_volume[i].
    n = len(sorted_buckets)
    peak_volume = 0
    peak_idx = 0
    window_sum = 0
    j = 0
    for i in range(n):
        if j < i:
            j = i
            window_sum = 0
        while (
            j < n
            and (sorted_buckets[j]["start_time"] - sorted_buckets[i]["start_time"])
            < peak_window
        ):
            window_sum += per_bucket_volume[j]
            j += 1
        if window_sum > peak_volume:
            peak_volume = window_sum
            peak_idx = i
        window_sum -= per_bucket_volume[i]

    profile.peak_window_start = sorted_buckets[peak_idx]["start_time"]
    profile.peak_window_end = profile.peak_window_start + peak_window
    pct = Decimal(peak_volume) / Decimal(total_volume) * Decimal(100)
    profile.peak_window_share_pct = pct.quantize(Decimal("0.1"))

    if profile.first_trade_time is not None and profile.last_trade_time is not None:
        start = profile.first_trade_time
        span = profile.last_trade_time - start
        if span.total_seconds() <= 0:
            # All trades in the same minute — pack everything into bucket 0.
            sparkline = [0] * sparkline_buckets
            sparkline[0] = total_volume
            profile.sparkline = sparkline
        else:
            step = span / sparkline_buckets
            sparkline = [0] * sparkline_buckets
            for bucket, v in zip(sorted_buckets, per_bucket_volume, strict=True):
                if v == 0:
                    continue
                t = bucket["start_time"]
                if t < start:
                    continue
                # Clamp the final-tick boundary so t==last_trade_time lands
                # in the last sub-range instead of overflowing past it.
                idx = int((t - start) / step)
                if idx >= sparkline_buckets:
                    idx = sparkline_buckets - 1
                sparkline[idx] += v
            profile.sparkline = sparkline

    return profile
