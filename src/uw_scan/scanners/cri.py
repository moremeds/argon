"""CRI scanner — orchestrator on top of cards/cri_scoring.

Reads VIX/VVIX/COR1M from vol_index_daily (parquet-lake-backed) and SPY
closes from daily_ohlc (massive-backed). Aligns to a common date set,
runs ``cards/cri_scoring.run_analysis``, persists the snapshot.

No external API calls — purely local DB reads + math + write.

Recovery: ``recover_recent_gaps`` walks the last N trading days and runs
the scanner for any day that has aligned vol_index_daily data but no
cri_snapshots row. Designed to be called once per scheduler tick so the
job self-heals if the worker was offline for a stretch.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date as _date
from datetime import timedelta

import numpy as np
from psycopg import Connection

from uw_scan.cards import cri_scoring
from uw_scan.scanners.live_quotes import (
    LiveQuote,
    carry_forward,
    live_session_date,
    quotes_payload,
    splice_session_value,
)
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger(__name__)

# Lookback window — enough for the 100d MA + the trailing 20-day history.
# 200 days gives slack for weekends/holidays so we still have ~140 trading days.
LOOKBACK_DAYS = 200

# Minimum aligned bars before we attempt a scan. Anything less and the
# MA / realized-vol blocks return NaN and downstream scores collapse to 0.
MIN_ALIGNED_BARS = cri_scoring.MA_WINDOW + cri_scoring.VOL_WINDOW


def _load_vol_series(
    vol_repo: VolIndexRepository,
    symbol: str,
    days: int,
    *,
    as_of: _date | None = None,
) -> dict[_date, float]:
    """Load up to ``days`` most-recent rows for ``symbol``.

    When ``as_of`` is set, the lookback is capped at ``trade_date <= as_of``
    so the historical-recovery path can re-aim the scanner at a previous
    day without changing the rest of the orchestration.

    The cap is pushed into SQL — see VolIndexRepository.fetch_history. Selecting
    the most-recent rows and filtering to ``<= as_of`` afterwards anchors the
    fetch window to today while anchoring the filter to ``as_of``; once ``as_of``
    is further back than the window, every row is filtered out and the caller
    sees an empty series rather than an error.
    """
    rows = vol_repo.fetch_history(symbol, days=days, as_of=as_of)
    return {
        r["trade_date"]: float(r["close"]) for r in rows if r.get("close") is not None
    }


def _load_spy_series(
    repo: Repository, days: int, *, as_of: _date | None = None
) -> dict[_date, float]:
    fetch_days = days * 2 if as_of is not None else days
    rows = repo.list_daily_ohlc("SPY", limit=fetch_days)
    if as_of is not None:
        rows = [r for r in rows if r.date <= as_of]
        rows = rows[:days]
    return {r.date: float(r.close) for r in rows}


def _load_spx_series(
    vol_repo: VolIndexRepository, days: int, *, as_of: _date | None = None
) -> dict[_date, float]:
    """SPX closing levels from vol_index_daily (parquet-lake-backed)."""
    return _load_vol_series(vol_repo, "SPX", days, as_of=as_of)


def _align(
    series: dict[str, dict[_date, float]],
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Inner-join the series on shared dates; return aligned arrays + ISO date list."""
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
    return aligned, [d.isoformat() for d in sorted_dates]


def run(
    conn: Connection,
    schema: str = "uw_scan",
    *,
    as_of: _date | None = None,
) -> int | None:
    """Run a CRI scan against the warm store; persist a new snapshot row.

    When ``as_of`` is set, the scanner computes for that historical date
    by capping every loaded series to ``trade_date <= as_of``. The
    resulting ``common_dates[-1]`` then equals ``as_of`` and the snapshot
    is persisted with ``data_date=as_of``. Used by ``recover_recent_gaps``.

    Returns the inserted row id, or None if there isn't enough aligned data.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    repo = Repository(conn, schema=schema)

    mandatory_vol = {
        "VIX": _load_vol_series(vol_repo, "VIX", LOOKBACK_DAYS, as_of=as_of),
        "VVIX": _load_vol_series(vol_repo, "VVIX", LOOKBACK_DAYS, as_of=as_of),
        "COR1M": _load_vol_series(vol_repo, "COR1M", LOOKBACK_DAYS, as_of=as_of),
    }

    # Attempt 1: SPX from vol_index_daily.
    aligned: dict[str, np.ndarray] = {}
    common_dates: list[str] = []
    spx = _load_spx_series(vol_repo, LOOKBACK_DAYS, as_of=as_of)
    if spx:
        aligned, common_dates = _align({**mandatory_vol, "SPX": spx})

    # Attempt 2 (fallback): SPY from daily_ohlc. Triggers when SPX is
    # entirely absent OR has insufficient overlap with the mandatory vol
    # series to make MIN_ALIGNED_BARS. A partial SPX backfill must not
    # suppress the snapshot if SPY can still produce one.
    if len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "cri_scan_spx_alignment_thin spx_bars=%d need=%d — falling back to SPY",
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        spy = _load_spy_series(repo, LOOKBACK_DAYS, as_of=as_of)
        aligned, common_dates = _align({**mandatory_vol, "SPY": spy})

    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "cri_scan_skipped_thin_data aligned_bars=%d need=%d as_of=%s",
            len(common_dates),
            MIN_ALIGNED_BARS,
            as_of,
        )
        return None

    # VIX3M is optional and intentionally OUTSIDE the alignment join. We
    # want today's value (or the latest available close on the same date
    # as the CRI snapshot) for the term-structure tile; we do NOT want a
    # stale VIX3M sync to suppress the whole snapshot.
    vix3m_series = _load_vol_series(vol_repo, "VIX3M", LOOKBACK_DAYS, as_of=as_of)
    if vix3m_series:
        vix3m_aligned = np.array(
            [
                vix3m_series.get(_date.fromisoformat(d), float("nan"))
                for d in common_dates
            ],
            dtype=float,
        )
        aligned["VIX3M"] = vix3m_aligned

    payload = cri_scoring.run_analysis(aligned, common_dates)

    snap_repo = CriSnapshotRepository(conn, schema=schema)
    data_date = _date.fromisoformat(payload["date"])
    row_id = snap_repo.insert_snapshot(payload=payload, data_date=data_date)
    log.info(
        "cri_scan_persisted row_id=%d data_date=%s score=%.1f level=%s fired=%s",
        row_id,
        data_date,
        payload["cri"]["score"],
        payload["cri"]["level"],
        payload["crash_trigger"]["fired"],
    )
    return row_id


def run_live(
    conn: Connection,
    schema: str = "uw_scan",
    *,
    quotes: Mapping[str, LiveQuote],
    persist: bool = False,
) -> dict | None:
    """CRI computed with live WS quotes spliced as today's provisional close.

    Mandatory series (VIX/VVIX/COR1M/SPX) without a fresh quote are carried
    forward from their last daily close so the inner-join alignment keeps
    today's bar — a dead COR1M feed degrades that input to "yesterday's
    value", it does not kill the live read. Returns the full payload (with
    history arrays — the API serves it directly); when ``persist`` is set,
    a SLIM copy (no history / spy_closes) lands in cri_snapshots with
    basis='live'. Returns None when no usable quote exists.
    """
    session_date = live_session_date(quotes)
    if session_date is None:
        return None

    vol_repo = VolIndexRepository(conn, schema=schema)
    series: dict[str, dict[_date, float]] = {
        "VIX": _load_vol_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_vol_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        "COR1M": _load_vol_series(vol_repo, "COR1M", LOOKBACK_DAYS),
        "SPX": _load_spx_series(vol_repo, LOOKBACK_DAYS),
    }
    live_syms: list[str] = []
    carried: list[str] = []
    for sym in list(series):
        q = quotes.get(sym)
        if q is not None:
            series[sym] = splice_session_value(series[sym], q.price, session_date)
            live_syms.append(sym)
        else:
            series[sym], was_carried = carry_forward(series[sym], session_date)
            if was_carried:
                carried.append(sym)
    if not live_syms:
        return None

    aligned, common_dates = _align(series)
    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "cri_live_skipped_thin_data aligned_bars=%d need=%d",
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        return None

    vix3m_series = _load_vol_series(vol_repo, "VIX3M", LOOKBACK_DAYS)
    q3m = quotes.get("VIX3M")
    if q3m is not None:
        vix3m_series = splice_session_value(vix3m_series, q3m.price, session_date)
    else:
        # Without carry-forward today's bar is NaN and the term-structure
        # tiles (vix3m / vix_vix3m_ratio) blank out on a LIVE read even
        # though the EOD view had values — same degradation rule as the
        # mandatory series.
        vix3m_series, was_carried = carry_forward(vix3m_series, session_date)
        if was_carried:
            carried.append("VIX3M")
    if vix3m_series:
        aligned["VIX3M"] = np.array(
            [
                vix3m_series.get(_date.fromisoformat(d), float("nan"))
                for d in common_dates
            ],
            dtype=float,
        )

    payload = cri_scoring.run_analysis(aligned, common_dates)
    payload["basis"] = "live"
    payload["live_quotes"] = quotes_payload(quotes)
    payload["carried_forward"] = carried

    if persist:
        slim = {k: v for k, v in payload.items() if k not in ("history", "spy_closes")}
        snap_repo = CriSnapshotRepository(conn, schema=schema)
        row_id = snap_repo.insert_snapshot(
            payload=slim, data_date=session_date, basis="live"
        )
        log.info(
            "cri_live_persisted row_id=%d session=%s live=%s carried=%s score=%.1f",
            row_id,
            session_date,
            sorted(live_syms),
            carried,
            payload["cri"]["score"],
        )
    return payload


def _existing_cri_dates(conn: Connection, schema: str, *, since: _date) -> set[_date]:
    """Distinct EOD ``data_date`` already in ``cri_snapshots`` since ``since``.

    basis='eod' only — a 5-min live row landing on today's date must not
    suppress the EOD gap recovery for that same date.
    """
    sql = f"""
        SELECT DISTINCT data_date
          FROM {schema}.cri_snapshots
         WHERE data_date IS NOT NULL
           AND data_date >= %s
           AND basis = 'eod'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since,))
        return {r[0] for r in cur.fetchall()}


def recover_recent_gaps(
    conn: Connection, schema: str = "uw_scan", *, lookback_days: int = 7
) -> dict:
    """Fill any missing CRI snapshot in the last ``lookback_days`` trading days.

    Walks the dates that exist in ``vol_index_daily`` across the three
    mandatory series (VIX/VVIX/COR1M) plus an SPX or SPY anchor, finds the
    subset within ``[latest - lookback_days, latest]`` that has no
    snapshot, and runs the scanner once per missing day. Silent on dates
    where data isn't yet present in the lake — that's the "skip if not
    available" half of the contract.

    Returns ``{"checked": N, "filled": K, "skipped": S}``. Idempotent: a
    second call right after the first sees no missing dates and is a no-op.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)

    # Intersect mandatory series so we only consider days the scanner can
    # actually score. SPX is preferred; SPY is the fallback (mirrors run()).
    vix = vol_repo.fetch_dates_for("VIX")
    vvix = vol_repo.fetch_dates_for("VVIX")
    cor1m = vol_repo.fetch_dates_for("COR1M")
    spx = vol_repo.fetch_dates_for("SPX")
    if not (vix and vvix and cor1m):
        log.info("cri_recover_skipped: mandatory series missing in lake")
        return {"checked": 0, "filled": 0, "skipped": 0}

    anchor = spx if spx else _spy_dates(conn, schema)
    aligned_days = sorted(vix & vvix & cor1m & anchor)
    if not aligned_days:
        return {"checked": 0, "filled": 0, "skipped": 0}

    latest = aligned_days[-1]
    cutoff = latest - timedelta(days=lookback_days)
    window = [d for d in aligned_days if d >= cutoff]

    existing = _existing_cri_dates(conn, schema, since=cutoff)
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
            log.warning("cri_recover_failed as_of=%s err=%s", d, repr(exc))
            conn.rollback()
            skipped += 1

    log.info(
        "cri_recover_done checked=%d filled=%d skipped=%d lookback=%dd",
        len(window),
        filled,
        skipped,
        lookback_days,
    )
    return {"checked": len(window), "filled": filled, "skipped": skipped}


def _spy_dates(conn: Connection, schema: str) -> set[_date]:
    """Trade dates present in ``daily_ohlc`` for SPY — the CRI fallback anchor."""
    sql = f"SELECT date FROM {schema}.daily_ohlc WHERE ticker = 'SPY'"
    with conn.cursor() as cur:
        cur.execute(sql)
        return {r[0] for r in cur.fetchall()}
