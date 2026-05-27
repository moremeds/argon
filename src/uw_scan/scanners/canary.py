"""5% Canary scanner — reads vol_index_daily, runs cards/canary_scoring, persists.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §5, §11.
"""

from __future__ import annotations

import logging
import math
from datetime import date as _date
from decimal import Decimal
from typing import Iterable

import numpy as np
from psycopg import Connection

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, load_calibration
from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.cards.canary_scoring import NormalizationError
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger(__name__)

# v0.3: 350 trading rows required (not calendar days).
MIN_ALIGNED_BARS = 350
CALENDAR_DAYS_REQUESTED = 500
RV_WINDOW = 20


def _load(vol_repo: VolIndexRepository, symbol: str, days: int) -> dict[_date, float]:
    """Load {date: close}. v0.5 patch: raise on NaN / non-finite values."""
    rows = vol_repo.fetch_history(symbol, days=days)
    out: dict[_date, float] = {}
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        cv = float(c)
        if not math.isfinite(cv):
            raise NormalizationError(
                f"{symbol} close is not finite on {r['trade_date']}: {c!r}"
            )
        out[r["trade_date"]] = cv
    return out


def _align(
    series: dict[str, dict[_date, float]],
) -> tuple[dict[str, np.ndarray], list[_date]]:
    if not series:
        return {}, []
    keys = list(series.keys())
    common = set(series[keys[0]].keys())
    for k in keys[1:]:
        common &= set(series[k].keys())
    if not common:
        return {sym: np.array([]) for sym in keys}, []
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in keys
    }
    return aligned, sorted_dates


def _compute_smas(spx_arr: np.ndarray) -> tuple[float, float]:
    sma_50 = float(np.mean(spx_arr[-50:]))
    sma_200 = float(np.mean(spx_arr[-200:]))
    return sma_50, sma_200


def _above_sma200_two_consecutive(spx_arr: np.ndarray) -> bool:
    """Returns True iff SPX closed above its 200d SMA on both today and yesterday.

    The SMA is recomputed for each of the two days using each day's own
    trailing 200 closes (not a single shared SMA), so the result is causal.
    """
    if len(spx_arr) < 201:
        return False
    sma200_today = float(np.mean(spx_arr[-200:]))
    sma200_prev = float(np.mean(spx_arr[-201:-1]))
    # Coerce numpy.bool_ → Python bool at the function boundary so the
    # value flows cleanly through Jsonb and the canonical payload hash.
    return bool(
        float(spx_arr[-1]) >= sma200_today and float(spx_arr[-2]) >= sma200_prev
    )


def _compute_cap_lift_inputs(
    spx_arr: np.ndarray,
    sma_200: float,
    vix_arr: np.ndarray,
    vix3m_arr: np.ndarray,
) -> tuple[bool, bool, bool]:
    closes = spx_arr.tolist()
    today = closes[-1]
    spx_above_sma200_2d = _above_sma200_two_consecutive(spx_arr)
    vix_term_normalized = bool(
        (float(vix_arr[-1]) / float(vix3m_arr[-1])) < 1.0
        if float(vix3m_arr[-1]) > 0
        else False
    )
    higher_closing_low = bool(
        canary_scoring.higher_closing_low_close_only(
            closes, sma_200_today=sma_200, spx_close_today=today
        )
    )
    return spx_above_sma200_2d, vix_term_normalized, higher_closing_low


def _replay_events(
    spx_close_history: list[tuple[_date, float]],
) -> canary_scoring.CanaryEventState:
    """Walk through the SPX close history day-by-day to materialize the event state."""
    state = canary_scoring.CanaryEventState()
    closes = [c for _, c in spx_close_history]
    for i, (d, c) in enumerate(spx_close_history):
        history_slice = spx_close_history[: i + 1]
        if i < 200:
            continue
        sma_50 = float(np.mean(closes[i - 49 : i + 1]))
        sma_200 = float(np.mean(closes[i - 199 : i + 1]))
        canary_scoring.step_primary_events(
            state,
            today=d,
            spx_close_today=c,
            spx_history=history_slice,
            sma_50_today=sma_50,
            sma_200_today=sma_200,
            trading_days_between=lambda a, b, _src=spx_close_history: sum(
                1 for dd, _ in _src if a < dd <= b
            ),
        )
        canary_scoring.step_confirmed_canary(
            state, today=d, spx_close_today=c, sma_200_today=sma_200
        )
    return state


def _events_in_window(
    events: Iterable,
    kind: str,
    fire_window_days: int,
    today: _date,
    all_dates: list[_date],
) -> bool:
    """Was an event of ``kind`` active through today?

    `fire_window_days` is an index distance, not a Python slice length:
    SPEED_ACTIVITY_WINDOW_DAYS=42 means T+0..T+42 inclusive (43 observations).
    """
    eligible_dates = [d for d in all_dates if d <= today]
    date_to_idx = {d: i for i, d in enumerate(eligible_dates)}
    today_idx = date_to_idx.get(today)
    if today_idx is None:
        return False
    for e in events:
        if e.kind != kind:
            continue
        fire_idx = date_to_idx.get(e.fire_date)
        if fire_idx is not None and 0 <= today_idx - fire_idx <= fire_window_days:
            return True
    return False


def run(
    conn: Connection, *, schema: str = "uw_scan", force_recompute: bool = False
) -> int | None:
    """Run a 5% Canary scan; persist a new snapshot row. Returns row id or None."""
    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX": _load(vol_repo, "VIX", CALENDAR_DAYS_REQUESTED),
        "VVIX": _load(vol_repo, "VVIX", CALENDAR_DAYS_REQUESTED),
        "VIX3M": _load(vol_repo, "VIX3M", CALENDAR_DAYS_REQUESTED),
        "COR1M": _load(vol_repo, "COR1M", CALENDAR_DAYS_REQUESTED),
        "SPX": _load(vol_repo, "SPX", CALENDAR_DAYS_REQUESTED),
    }
    aligned, common_dates = _align(raw)
    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "canary_scan_skipped_thin_data aligned=%d need=%d",
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        return None

    cal = load_calibration()
    today = common_dates[-1]
    sma_50, sma_200 = _compute_smas(aligned["SPX"])
    spx_close_history = list(zip(common_dates, aligned["SPX"].tolist()))
    event_state = _replay_events(spx_close_history)

    confirmed_active = _events_in_window(
        event_state.emitted,
        "confirmed_canary",
        canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS,
        today,
        common_dates,
    )
    btd_active = _events_in_window(
        event_state.emitted,
        "buy_the_dip",
        canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS,
        today,
        common_dates,
    )

    sma200_2d, term_norm, higher_low = _compute_cap_lift_inputs(
        aligned["SPX"], sma_200, aligned["VIX"], aligned["VIX3M"]
    )

    payload = canary_scoring.run_analysis(
        today=today,
        aligned=aligned,
        common_dates=[d.isoformat() for d in common_dates],
        sma_50_today=sma_50,
        sma_200_today=sma_200,
        spx_above_sma200_2d=sma200_2d,
        vix_term_normalized=term_norm,
        higher_closing_low=higher_low,
        confirmed_canary_active=confirmed_active,
        buy_the_dip_active=btd_active,
        calibration=cal,
    )

    snap_repo = CanarySnapshotRepository(conn, schema=schema)
    row_id = snap_repo.insert_snapshot(
        payload=payload,
        data_date=today,
        composite_version=COMPOSITE_VERSION,
        score_form=cal.score_form,
        score=Decimal(str(payload["canary"]["score"])),
        raw_score=Decimal(str(payload["canary"]["raw_score"])),
        band=payload["canary"]["band"],
        tactical_score=Decimal(str(payload["tactical_vol"]["score"])),
        structural_score=Decimal(str(payload["structural_vol"]["score"])),
        speed_score=payload["speed"]["score"],
        warning_state=payload["canary"]["warning_state"],
        payload_hash=canonical_payload_hash(payload),
        on_conflict="overwrite" if force_recompute else "noop",
    )
    log.info(
        "canary_scan_persisted row=%s score=%.1f band=%s state=%s",
        row_id,
        payload["canary"]["score"],
        payload["canary"]["band"],
        payload["canary"]["warning_state"],
    )
    return row_id
