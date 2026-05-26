from datetime import date, timedelta

from uw_scan.cards.canary_scoring import (
    HIGH_LOOKBACK_DAYS,
    CanaryEventState,
    step_primary_events,
)


def _bdate(offset: int) -> date:
    return date(2020, 1, 1) + timedelta(days=offset)


def _trading_days_between(a, b):
    """For tests, treat every calendar day as a trading day for simplicity."""
    return (b - a).days


def _build_uptrend_history(
    days: int, start: float = 100.0, growth: float = 0.001
) -> list[tuple[date, float]]:
    return [(_bdate(i), start * (1.0 + growth * i)) for i in range(days)]


def _step(state, full_history, i, sma_50, sma_200):
    """Drive the state machine one day using ONLY data up to and including index i.

    This honors the scorer's causal contract — the function should never
    receive future-dated rows. Test wrappers MUST slice the history.
    """
    d, v = full_history[i]
    return step_primary_events(
        state,
        today=d,
        spx_close_today=v,
        spx_history=full_history[: i + 1],  # ← causal slice
        sma_50_today=sma_50,
        sma_200_today=sma_200,
        trading_days_between=_trading_days_between,
    )


def test_5pct_canary_fires_on_fast_decline():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # Now drop 6% in 5 trading days — append the crash day to the history.
    crash_day = _bdate(HIGH_LOOKBACK_DAYS + 5)
    history_with_crash = history + [(crash_day, high_val * 0.94)]
    state = _step(
        state,
        history_with_crash,
        len(history_with_crash) - 1,
        sma_50=high_val,
        sma_200=high_val * 0.95,
    )
    assert any(e.kind == "5pct_canary" for e in state.emitted)


def test_buy_the_dip_fires_on_slow_decline_with_uptrend_smas():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # 5% breach but 20 trading days after the high → BTD path.
    dip_day = _bdate(HIGH_LOOKBACK_DAYS + 20)
    history_with_dip = history + [(dip_day, high_val * 0.945)]
    state = _step(
        state,
        history_with_dip,
        len(history_with_dip) - 1,
        sma_50=high_val * 1.01,
        sma_200=high_val * 0.95,
    )
    assert any(e.kind == "buy_the_dip" for e in state.emitted)


def test_canary_does_not_re_fire_against_same_anchor():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    full = list(history)
    for offset in (5, 7, 10):
        crash_day = _bdate(HIGH_LOOKBACK_DAYS + offset)
        full = full + [(crash_day, high_val * 0.93)]
        state = _step(
            state, full, len(full) - 1, sma_50=high_val, sma_200=high_val * 0.95
        )
    canaries = [e for e in state.emitted if e.kind == "5pct_canary"]
    assert len(canaries) == 1


def test_no_btd_after_canary_against_same_anchor():
    """Anchor invariant: once Canary fires against an anchor, BTD cannot also fire."""
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # Fast Canary fires at day +5.
    full = history + [(_bdate(HIGH_LOOKBACK_DAYS + 5), high_val * 0.94)]
    state = _step(
        state, full, len(full) - 1, sma_50=high_val * 1.01, sma_200=high_val * 0.95
    )
    assert any(e.kind == "5pct_canary" for e in state.emitted)
    # Day +20, still in 5% breach, SMA50>SMA200, slow-decline path normally
    # would fire BTD — but anchor invariant must block it.
    full = full + [(_bdate(HIGH_LOOKBACK_DAYS + 20), high_val * 0.94)]
    state = _step(
        state, full, len(full) - 1, sma_50=high_val * 1.01, sma_200=high_val * 0.95
    )
    btds = [e for e in state.emitted if e.kind == "buy_the_dip"]
    assert btds == []


def test_new_high_resets_anchor_flags():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    full = history + [(_bdate(HIGH_LOOKBACK_DAYS + 5), high_val * 0.94)]
    state = _step(state, full, len(full) - 1, sma_50=high_val, sma_200=high_val * 0.95)
    assert state.canary_fired_for_high is True
    # Print a NEW 252d high — must reset both flags.
    full = full + [(_bdate(HIGH_LOOKBACK_DAYS + 200), high_val * 1.10)]
    state = _step(state, full, len(full) - 1, sma_50=high_val, sma_200=high_val * 0.95)
    assert state.canary_fired_for_high is False
    assert state.btd_fired_for_high is False
