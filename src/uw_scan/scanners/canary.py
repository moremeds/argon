"""5% Canary scanner — reads vol_index_daily, runs cards/canary_scoring, persists.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §5, §11.

Recovery: ``recover_recent_gaps`` walks the last N trading days and runs the
scanner for any day that has aligned vol_index_daily data but no
canary_snapshots row at the current composite_version.
"""

from __future__ import annotations

import logging
import math
from datetime import date as _date, timedelta
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


def _load(
    vol_repo: VolIndexRepository,
    symbol: str,
    days: int,
    *,
    as_of: _date | None = None,
) -> dict[_date, float]:
    """Load {date: close}. v0.5 patch: raise on NaN / non-finite values.

    When ``as_of`` is set the lookback caps at ``trade_date <= as_of`` so
    ``recover_recent_gaps`` can re-aim the scanner at a previous day.
    """
    fetch_days = days * 2 if as_of is not None else days
    rows = vol_repo.fetch_history(symbol, days=fetch_days)
    if as_of is not None:
        rows = [r for r in rows if r["trade_date"] <= as_of]
        rows = rows[-days:]
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
    conn: Connection,
    *,
    schema: str = "uw_scan",
    force_recompute: bool = False,
    as_of: _date | None = None,
) -> int | None:
    """Run a 5% Canary scan; persist a new snapshot row. Returns row id or None.

    When ``as_of`` is set, the scanner computes for that historical date by
    capping every loaded series to ``trade_date <= as_of`` so
    ``common_dates[-1]`` equals ``as_of``. Used by ``recover_recent_gaps``.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX": _load(vol_repo, "VIX", CALENDAR_DAYS_REQUESTED, as_of=as_of),
        "VVIX": _load(vol_repo, "VVIX", CALENDAR_DAYS_REQUESTED, as_of=as_of),
        "VIX3M": _load(vol_repo, "VIX3M", CALENDAR_DAYS_REQUESTED, as_of=as_of),
        "COR1M": _load(vol_repo, "COR1M", CALENDAR_DAYS_REQUESTED, as_of=as_of),
        "SPX": _load(vol_repo, "SPX", CALENDAR_DAYS_REQUESTED, as_of=as_of),
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
        "canary_scan_persisted row=%s data_date=%s score=%.1f band=%s state=%s",
        row_id,
        today,
        payload["canary"]["score"],
        payload["canary"]["band"],
        payload["canary"]["warning_state"],
    )
    return row_id


def _existing_canary_dates(
    conn: Connection, schema: str, *, since: _date, composite_version: int
) -> set[_date]:
    """Distinct ``data_date`` already in ``canary_snapshots`` at this composite_version."""
    sql = f"""
        SELECT DISTINCT data_date
          FROM {schema}.canary_snapshots
         WHERE data_date IS NOT NULL
           AND data_date >= %s
           AND composite_version = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since, composite_version))
        return {r[0] for r in cur.fetchall()}


def recover_recent_gaps(
    conn: Connection,
    schema: str = "uw_scan",
    *,
    lookback_days: int = 7,
) -> dict:
    """Fill any missing 5% Canary snapshot in the last ``lookback_days`` days.

    Mirrors the CRI/VCG recovery shape. composite_version is part of the
    canary uniqueness key — older snapshots from a previous calibration
    don't count as "filled" for the current version.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    needed = ("VIX", "VVIX", "VIX3M", "COR1M", "SPX")
    dates_by_sym = {sym: vol_repo.fetch_dates_for(sym) for sym in needed}
    if not all(dates_by_sym.values()):
        log.info("canary_recover_skipped: mandatory series missing in lake")
        return {"checked": 0, "filled": 0, "skipped": 0}

    aligned_days = sorted(set.intersection(*dates_by_sym.values()))
    if not aligned_days:
        return {"checked": 0, "filled": 0, "skipped": 0}

    latest = aligned_days[-1]
    cutoff = latest - timedelta(days=lookback_days)
    window = [d for d in aligned_days if d >= cutoff]

    existing = _existing_canary_dates(
        conn, schema, since=cutoff, composite_version=COMPOSITE_VERSION
    )
    missing = [d for d in window if d not in existing]

    filled = 0
    skipped = 0
    for d in missing:
        try:
            rid = run(conn, schema=schema, as_of=d)
            if rid is None:
                skipped += 1
            else:
                filled += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("canary_recover_failed as_of=%s err=%s", d, repr(exc))
            conn.rollback()
            skipped += 1

    log.info(
        "canary_recover_done checked=%d filled=%d skipped=%d lookback=%dd",
        len(window),
        filled,
        skipped,
        lookback_days,
    )
    return {"checked": len(window), "filled": filled, "skipped": skipped}
