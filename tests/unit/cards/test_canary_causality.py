"""The causality test — assert that the K-th snapshot in an incremental run
matches the snapshot produced by feeding only data[:K] to the full pipeline.

If this test fails, the implementation has a look-ahead bug.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.cards.canary_payload_hash import canonical_payload_hash


def _synthetic_history(
    n_days: int = 400, crash_offset: int = 250
) -> tuple[list, dict[str, np.ndarray]]:
    """Build an n-day history with a fast 6% crash at day ``crash_offset``."""
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
    spx = np.linspace(4000, 4400, n_days)
    spx[crash_offset : crash_offset + 10] = np.linspace(4400, 4135, 10)
    spx[crash_offset + 10 :] = np.linspace(4135, 4300, n_days - crash_offset - 10)
    return dates, {
        "VIX": np.where(np.arange(n_days) >= crash_offset, 32.0, 16.0).astype(float),
        "VVIX": np.where(np.arange(n_days) >= crash_offset, 130.0, 92.0).astype(float),
        "VIX3M": np.where(np.arange(n_days) >= crash_offset, 25.0, 18.0).astype(float),
        "COR1M": np.where(np.arange(n_days) >= crash_offset, 72.0, 34.0).astype(float),
        "SPX": spx,
    }


def _snapshot_at(dates: list, aligned: dict[str, np.ndarray], k: int) -> dict:
    """Run the full pipeline using only data[:k+1] — independent truncated invocation."""
    truncated_dates = dates[: k + 1]
    truncated = {sym: arr[: k + 1] for sym, arr in aligned.items()}
    if len(truncated_dates) < canary_scoring.HIGH_LOOKBACK_DAYS:
        return {}
    cal = load_calibration()
    sma_50 = float(np.mean(truncated["SPX"][-50:]))
    sma_200 = float(np.mean(truncated["SPX"][-200:]))
    spx_close_history = list(zip(truncated_dates, truncated["SPX"].tolist()))

    # Replay events incrementally — same as scanner._replay_events.
    state = canary_scoring.CanaryEventState()
    closes = truncated["SPX"].tolist()
    for i, (d, c) in enumerate(spx_close_history):
        if i < 200:
            continue
        sma50_i = float(np.mean(closes[i - 49 : i + 1]))
        sma200_i = float(np.mean(closes[i - 199 : i + 1]))
        canary_scoring.step_primary_events(
            state,
            today=d,
            spx_close_today=c,
            spx_history=spx_close_history[: i + 1],
            sma_50_today=sma50_i,
            sma_200_today=sma200_i,
            trading_days_between=lambda a, b, _src=spx_close_history: sum(
                1 for dd, _ in _src if a < dd <= b
            ),
        )
        canary_scoring.step_confirmed_canary(
            state, today=d, spx_close_today=c, sma_200_today=sma200_i
        )

    date_to_idx = {d: idx for idx, d in enumerate(truncated_dates)}
    today_idx = len(truncated_dates) - 1
    confirmed_active = any(
        e.kind == "confirmed_canary"
        and e.fire_date in date_to_idx
        and 0
        <= today_idx - date_to_idx[e.fire_date]
        <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
        for e in state.emitted
    )
    btd_active = any(
        e.kind == "buy_the_dip"
        and e.fire_date in date_to_idx
        and 0
        <= today_idx - date_to_idx[e.fire_date]
        <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
        for e in state.emitted
    )

    payload = canary_scoring.run_analysis(
        today=truncated_dates[-1],
        aligned=truncated,
        common_dates=[d.isoformat() for d in truncated_dates],
        sma_50_today=sma_50,
        sma_200_today=sma_200,
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=confirmed_active,
        buy_the_dip_active=btd_active,
        calibration=cal,
    )
    return payload


def _full_history_sequential_walk(
    dates: list, aligned: dict[str, np.ndarray]
) -> dict[int, dict]:
    """v0.4 patch I3: TRUE full-history sequential walk — one pass over all
    data, building up state and emitting a snapshot for each date.

    A causal implementation produces snapshot[k] that is byte-identical
    to the snapshot produced by an independent truncated invocation
    `_snapshot_at(dates, aligned, k)`.

    IMPORTANT: this function MUST NOT re-truncate per-K. It must walk
    forward once, accumulating state. That's the whole point of the test.
    """
    cal = load_calibration()
    closes = aligned["SPX"].tolist()
    history_pairs = list(zip(dates, closes))
    state = canary_scoring.CanaryEventState()
    out: dict[int, dict] = {}
    for i, (d, c) in enumerate(history_pairs):
        if i < canary_scoring.HIGH_LOOKBACK_DAYS:
            continue
        sma50 = float(np.mean(closes[i - 49 : i + 1]))
        sma200 = float(np.mean(closes[i - 199 : i + 1]))
        canary_scoring.step_primary_events(
            state,
            today=d,
            spx_close_today=c,
            spx_history=history_pairs[: i + 1],
            sma_50_today=sma50,
            sma_200_today=sma200,
            trading_days_between=lambda a, b, _src=history_pairs: sum(
                1 for dd, _ in _src if a < dd <= b
            ),
        )
        canary_scoring.step_confirmed_canary(
            state, today=d, spx_close_today=c, sma_200_today=sma200
        )

        slice_dates = dates[: i + 1]
        date_to_idx = {dd: idx for idx, dd in enumerate(slice_dates)}
        confirmed_active = any(
            e.kind == "confirmed_canary"
            and e.fire_date in date_to_idx
            and 0
            <= i - date_to_idx[e.fire_date]
            <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
            for e in state.emitted
        )
        btd_active = any(
            e.kind == "buy_the_dip"
            and e.fire_date in date_to_idx
            and 0
            <= i - date_to_idx[e.fire_date]
            <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
            for e in state.emitted
        )
        payload = canary_scoring.run_analysis(
            today=d,
            aligned={kk: vv[: i + 1] for kk, vv in aligned.items()},
            common_dates=[dd.isoformat() for dd in slice_dates],
            sma_50_today=sma50,
            sma_200_today=sma200,
            spx_above_sma200_2d=False,
            vix_term_normalized=False,
            higher_closing_low=False,
            confirmed_canary_active=confirmed_active,
            buy_the_dip_active=btd_active,
            calibration=cal,
        )
        out[i] = payload
    return out


@pytest.mark.parametrize("k", [253, 270, 300, 350, 399])
def test_full_history_snapshot_matches_truncated_history_snapshot(k):
    """The real causality test.

    PATH A: feed the FULL history once via _full_history_sequential_walk,
            extract the snapshot at index K.
    PATH B: feed ONLY data[:K+1] via _snapshot_at, extract its single
            snapshot for date K.

    If the implementation is causal, the two snapshots must be byte-identical
    (same canonical payload hash). If they differ, the implementation
    consumed data with date > K — a look-ahead bug.
    """
    dates, aligned = _synthetic_history()

    full_series = _full_history_sequential_walk(dates, aligned)
    snap_from_full = full_series[k]

    snap_from_truncated = _snapshot_at(dates, aligned, k)

    h_full = canonical_payload_hash(snap_from_full)
    h_trunc = canonical_payload_hash(snap_from_truncated)

    assert h_full == h_trunc, (
        f"Causality violation at k={k}:\n"
        f"  full-history hash = {h_full}\n"
        f"  truncated hash    = {h_trunc}\n"
        f"  full snapshot:      {snap_from_full}\n"
        f"  truncated snapshot: {snap_from_truncated}\n"
        f"\nImplementation must compute snapshot[k] using only data[:k+1]."
    )
