import math
from datetime import date

import pandas as pd
import pytest

from uw_scan.reports.magnet_data import (
    atm_iv_at_horizon,
    find_price_discontinuities,
    interp_atm_iv,
    normalize_iv,
    trim_to_clean_segment,
)


def _closes(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "close"])


# Real sessions from uw_scan.daily_ohlc on the mini, frozen 2026-08-09.
_CRWD_SPLIT = _closes(
    [
        (date(2026, 4, 9), 394.68),
        (date(2026, 4, 10), 379.02),
        (date(2026, 4, 13), 402.24),
        (date(2026, 4, 14), 99.6225),  # 4:1 split, unadjusted in daily_ohlc
        (date(2026, 4, 15), 102.79),
        (date(2026, 4, 16), 104.55),
    ]
)

_AAOI_REAL_MOVE = _closes(
    [
        (date(2026, 2, 24), 56.27),
        (date(2026, 2, 25), 58.12),
        (date(2026, 2, 26), 53.69),
        (date(2026, 2, 27), 84.23),  # +56.9% on the day — real, not a split
        (date(2026, 3, 2), 102.51),
    ]
)

_KORU_NEAREST_MISS = _closes(
    [
        (date(2026, 6, 2), 61.2405),
        (date(2026, 6, 3), 59.836),
        (date(2026, 6, 4), 52.485),
        (date(2026, 6, 5), 30.5005),  # log -0.5428, the largest real move measured
        (date(2026, 6, 8), 35.472),
        (date(2026, 6, 9), 34.601),
    ]
)


def test_normalize_iv_passes_decimal_through():
    assert normalize_iv(0.42) == pytest.approx(0.42)


def test_normalize_iv_converts_percent():
    # The grid stores some sessions as percent. load_atm_iv uses the same >3.0 rule.
    assert normalize_iv(42.0) == pytest.approx(0.42)


def test_interp_atm_iv_is_linear_in_total_variance():
    # w = sigma^2 * dte.  near: 0.40^2*7 = 1.12   far: 0.30^2*28 = 2.52
    # target 14 sits 1/3 of the way from 7 to 28 -> w = 1.12 + (2.52-1.12)/3
    got = interp_atm_iv(0.40, 7, 0.30, 28, 14)
    assert got == pytest.approx(
        math.sqrt((1.12 + (2.52 - 1.12) / 3.0) / 14.0), rel=1e-9
    )


def test_interp_atm_iv_returns_endpoint_when_target_equals_near():
    assert interp_atm_iv(0.40, 7, 0.30, 28, 7) == pytest.approx(0.40)


def test_interp_atm_iv_rejects_non_positive_target():
    with pytest.raises(ValueError):
        interp_atm_iv(0.40, 7, 0.30, 28, 0)


def test_atm_iv_at_horizon_interpolates_between_straddling_expiries():
    curve = [(7, 0.40), (28, 0.30)]
    assert atm_iv_at_horizon(curve, 14) == pytest.approx(
        interp_atm_iv(0.40, 7, 0.30, 28, 14)
    )


def test_atm_iv_at_horizon_uses_exact_expiry_when_present():
    assert atm_iv_at_horizon([(7, 0.40), (14, 0.35), (28, 0.30)], 14) == pytest.approx(
        0.35
    )


def test_atm_iv_at_horizon_rejects_an_expiry_more_than_twice_the_target():
    # A 90-day expiry is not a measurement of a 7-day cone.
    assert atm_iv_at_horizon([(90, 0.30)], 7) is None


def test_atm_iv_at_horizon_rejects_an_expiry_less_than_half_the_target():
    assert atm_iv_at_horizon([(3, 0.60)], 14) is None


def test_atm_iv_at_horizon_accepts_a_single_nearby_expiry():
    assert atm_iv_at_horizon([(10, 0.33)], 7) == pytest.approx(0.33)


def test_atm_iv_at_horizon_returns_none_on_an_empty_curve():
    assert atm_iv_at_horizon([], 7) is None


def test_find_price_discontinuities_flags_the_crwd_four_for_one_split():
    # 402.24 -> 99.6225 is 0.2477, a 4:1 split showing through unadjusted.
    assert find_price_discontinuities(_CRWD_SPLIT) == {date(2026, 4, 14)}


def test_find_price_discontinuities_keeps_a_real_fifty_seven_percent_day():
    # AAOI 53.69 -> 84.23. Large, real, and must survive: dropping sessions like
    # this is what made the whole-ticker filter discard 19.8% of the sample.
    assert find_price_discontinuities(_AAOI_REAL_MOVE) == set()


def test_find_price_discontinuities_keeps_the_largest_measured_real_move():
    # KORU 52.485 -> 30.5005 = log -0.5428, the biggest non-split move in the
    # whole 151-ticker scan. If the threshold ever drifts below ln(2) this is
    # the test that fails first.
    assert find_price_discontinuities(_KORU_NEAREST_MISS) == set()


def test_find_price_discontinuities_honours_a_custom_threshold():
    assert find_price_discontinuities(_KORU_NEAREST_MISS, threshold=0.5) == {
        date(2026, 6, 5)
    }


def test_find_price_discontinuities_handles_too_few_rows():
    assert find_price_discontinuities(_CRWD_SPLIT.head(1)) == set()
    assert find_price_discontinuities(_closes([])) == set()


def test_trim_to_clean_segment_starts_on_the_split_bar():
    # The 4:1 bar's own close (99.6225) is already post-split and must survive;
    # only the 402.24 -> 99.6225 return into it is fabricated.
    got = trim_to_clean_segment(_CRWD_SPLIT)
    assert got["date"].tolist() == [
        date(2026, 4, 14),
        date(2026, 4, 15),
        date(2026, 4, 16),
    ]
    assert got["close"].iloc[0] == pytest.approx(99.6225)


def test_trim_to_clean_segment_is_a_no_op_without_a_split():
    got = trim_to_clean_segment(_AAOI_REAL_MOVE)
    assert len(got) == len(_AAOI_REAL_MOVE)


def test_trim_to_clean_segment_reindexes_from_zero():
    # Positional i+h indexing downstream requires a 0-based contiguous index.
    assert trim_to_clean_segment(_CRWD_SPLIT).index.tolist() == [0, 1, 2]
