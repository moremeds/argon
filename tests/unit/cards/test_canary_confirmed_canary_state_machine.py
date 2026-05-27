from datetime import date, timedelta

from uw_scan.cards.canary_scoring import CanaryEventState, step_confirmed_canary


def _bdate(offset: int) -> date:
    return date(2026, 1, 1) + timedelta(days=offset)


def _state_with_one_open_window(fire_offset: int = 0) -> CanaryEventState:
    state = CanaryEventState()
    state.open_canary_windows.append(
        {
            "canary_fire_date": _bdate(fire_offset),
            "expires_after_td": 42,
            "consec_below_sma200": 0,
            "td_elapsed": 0,
        }
    )
    return state


def test_confirmation_requires_two_consecutive_closes_below_sma_200():
    state = _state_with_one_open_window()
    # Day +1: one close below — no fire.
    state = step_confirmed_canary(
        state, today=_bdate(1), spx_close_today=95.0, sma_200_today=100.0
    )
    assert not any(e.kind == "confirmed_canary" for e in state.emitted)
    assert state.open_canary_windows[0]["consec_below_sma200"] == 1
    # Day +2: second consecutive close below — fire.
    state = step_confirmed_canary(
        state, today=_bdate(2), spx_close_today=94.0, sma_200_today=100.0
    )
    assert any(e.kind == "confirmed_canary" for e in state.emitted)


def test_close_above_sma200_resets_counter():
    state = _state_with_one_open_window()
    state = step_confirmed_canary(
        state, today=_bdate(1), spx_close_today=95.0, sma_200_today=100.0
    )
    assert state.open_canary_windows[0]["consec_below_sma200"] == 1
    state = step_confirmed_canary(
        state, today=_bdate(2), spx_close_today=101.0, sma_200_today=100.0
    )
    assert state.open_canary_windows[0]["consec_below_sma200"] == 0


def test_window_consumed_on_confirmation():
    state = _state_with_one_open_window()
    for offset in (1, 2):
        state = step_confirmed_canary(
            state, today=_bdate(offset), spx_close_today=95.0, sma_200_today=100.0
        )
    assert state.open_canary_windows == []  # consumed


def test_window_expires_after_42_trading_days():
    state = _state_with_one_open_window()
    for offset in range(1, 44):
        state = step_confirmed_canary(
            state,
            today=_bdate(offset),
            spx_close_today=101.0,
            sma_200_today=100.0,
        )
    assert state.open_canary_windows == []  # expired


def test_fire_day_is_t0_not_t1_when_scanner_calls_same_day():
    state = _state_with_one_open_window()
    state = step_confirmed_canary(
        state, today=_bdate(0), spx_close_today=95.0, sma_200_today=100.0
    )
    assert state.open_canary_windows[0]["td_elapsed"] == 0
    assert state.open_canary_windows[0]["consec_below_sma200"] == 1


def test_two_concurrent_open_windows_tracked_independently():
    state = CanaryEventState()
    state.open_canary_windows.extend(
        [
            {
                "canary_fire_date": _bdate(0),
                "expires_after_td": 42,
                "consec_below_sma200": 0,
                "td_elapsed": 0,
            },
            {
                "canary_fire_date": _bdate(5),
                "expires_after_td": 42,
                "consec_below_sma200": 0,
                "td_elapsed": 0,
            },
        ]
    )
    # Day +6: close below SMA-200 — both windows tick.
    state = step_confirmed_canary(
        state, today=_bdate(6), spx_close_today=95.0, sma_200_today=100.0
    )
    state = step_confirmed_canary(
        state, today=_bdate(7), spx_close_today=94.0, sma_200_today=100.0
    )
    confirmations = [e for e in state.emitted if e.kind == "confirmed_canary"]
    # Both windows consumed on the same day (each fired its own confirmation)
    assert len(confirmations) == 2
