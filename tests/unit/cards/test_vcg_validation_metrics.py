"""Metric battery used by the comparator. Each metric is exercised against
a small hand-computed reference."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from uw_scan.cards.drawdown import DrawdownEvent
from uw_scan.cards.vcg_validation_metrics import (
    actionable_lead_days,
    alarm_day_ratio,
    close_to_trough_lead_days,
    fp_day_rate,
    fp_episode_rate,
    hit_rate,
    next_trading_day,
    ro_episodes,
    utility_score,
)


def _dseries(values: dict[date, bool]) -> pd.Series:
    idx = sorted(values.keys())
    return pd.Series([values[d] for d in idx], index=idx, dtype=bool)


def test_close_to_trough_lead_simple() -> None:
    ro_date = date(2020, 3, 10)
    trough = date(2020, 3, 20)
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 3, 31)).date
    lead = close_to_trough_lead_days(ro_date, trough, trading_days)
    assert lead == 8  # business days between 2020-03-10 and 2020-03-20


def test_actionable_lead_negative_when_ro_at_trough_close() -> None:
    ro = trough = date(2020, 3, 20)
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 3, 31)).date
    a = actionable_lead_days(ro, trough, trading_days)
    assert a < 0  # next session after ro is post-trough


def test_next_trading_day_skips_weekends() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 4, 1)).date
    # Friday 2020-03-13 -> next bday is Monday 2020-03-16
    nt = next_trading_day(date(2020, 3, 13), trading_days)
    assert nt == date(2020, 3, 16)


def test_hit_rate_counts_only_actionable() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 4, 1)).date
    events = [
        DrawdownEvent(date(2020, 3, 5), date(2020, 3, 15), 100, 92, None, 0.08, "Fast"),
        DrawdownEvent(
            date(2020, 3, 20), date(2020, 3, 25), 100, 90, None, 0.10, "Fast"
        ),
    ]
    # RO fires Mar 10 — in event 1's [peak Mar 5, trough Mar 15] window (post-peak,
    # pre-trough → valid mid-drawdown hit). For event 2 (peak Mar 20), with
    # peak_lookback=5 the lookback window starts at Mar 13, so Mar 10 is OUT
    # and event 2 has no RO.
    ro = _dseries({d: (d == date(2020, 3, 10)) for d in trading_days})
    hr = hit_rate(events, ro_signal=ro, trading_days=trading_days, peak_lookback=5)
    assert hr == pytest.approx(0.5)


def test_ro_episodes_groups_contiguous_days() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 3, 13)).date
    on_days = {
        date(2020, 3, 3),
        date(2020, 3, 4),
        date(2020, 3, 5),  # episode 1
        date(2020, 3, 10),
        date(2020, 3, 11),  # episode 2
    }
    ro = _dseries({d: (d in on_days) for d in trading_days})
    eps = ro_episodes(ro)
    assert len(eps) == 2
    assert eps[0] == (date(2020, 3, 3), date(2020, 3, 5))
    assert eps[1] == (date(2020, 3, 10), date(2020, 3, 11))


def test_alarm_day_ratio_basic() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 3, 13)).date
    on_days = {date(2020, 3, 3), date(2020, 3, 4)}
    ro = _dseries({d: (d in on_days) for d in trading_days})
    r = alarm_day_ratio(ro)
    assert r == pytest.approx(2.0 / len(trading_days))


def test_fp_episode_rate_definitional_horizon() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 4, 30)).date
    ro_days = {date(2020, 3, 3), date(2020, 3, 4)}  # one episode of length 2
    ro = _dseries({d: (d in ro_days) for d in trading_days})
    # No drawdown event in next 30 bdays -> FP
    rate = fp_episode_rate(ro, events=[], trading_days=trading_days, horizon_days=30)
    assert rate == pytest.approx(1.0)


def test_utility_score_formula() -> None:
    score = utility_score(
        median_lead=2.5, hit_rate_val=0.75, fp_episode_rate_val=0.1, k_fp=5.0
    )
    assert score == pytest.approx(2.5 * 0.75 - 5.0 * 0.1)


def test_fp_day_rate_vs_episode_rate_diverge_for_long_regime() -> None:
    trading_days = list(pd.bdate_range(date(2020, 3, 2), date(2020, 4, 30)).date)
    ro_days = {trading_days[i] for i in range(20)}  # 20-day continuous RO regime
    ro = _dseries({d: (d in ro_days) for d in trading_days})
    day_rate = fp_day_rate(ro, events=[], trading_days=trading_days, horizon_days=10)
    ep_rate = fp_episode_rate(ro, events=[], trading_days=trading_days, horizon_days=30)
    # Day-rate punishes every day, episode-rate counts the single regime as one FP
    assert day_rate == pytest.approx(1.0)
    assert ep_rate == pytest.approx(1.0)
    # Add a qualifying event 25 days after RO start — episode-rate drops
    # because the event's [peak, trough] interval overlaps the 30-day horizon,
    # but day-rate stays high because the per-day horizon is only 10d.
    ev = DrawdownEvent(trading_days[20], trading_days[25], 100, 90, None, 0.10, "Fast")
    day_rate2 = fp_day_rate(ro, events=[ev], trading_days=trading_days, horizon_days=10)
    ep_rate2 = fp_episode_rate(
        ro, events=[ev], trading_days=trading_days, horizon_days=30
    )
    assert ep_rate2 < ep_rate  # episode caught a 25-day-out event within 30d horizon
    assert day_rate2 >= ep_rate2  # day-rate is stricter


def test_mid_drawdown_ro_is_not_false_positive() -> None:
    """REGRESSION GUARD (third-pass review item 4 — highest risk): an RO
    that fires AFTER the event peak but BEFORE the event trough must be
    counted as a HIT, not a false positive. The interval-overlap semantics
    of _event_interval_overlaps protect this."""
    trading_days = list(pd.bdate_range(date(2020, 3, 2), date(2020, 4, 30)).date)
    # Event peak at day 5, trough at day 12; RO fires day 8 (mid-drawdown)
    event = DrawdownEvent(
        trading_days[5], trading_days[12], 100, 90, None, 0.10, "Fast"
    )
    ro_days = {trading_days[8]}
    ro = _dseries({d: (d in ro_days) for d in trading_days})
    ep_rate = fp_episode_rate(
        ro, events=[event], trading_days=trading_days, horizon_days=30
    )
    assert ep_rate == pytest.approx(0.0), (
        "mid-drawdown RO must overlap event interval, not be counted as FP"
    )
