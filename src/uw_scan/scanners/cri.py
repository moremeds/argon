"""CRI scanner — orchestrator on top of cards/cri_scoring.

Reads VIX/VVIX/COR1M from vol_index_daily (parquet-lake-backed) and SPY
closes from daily_ohlc (massive-backed). Aligns to a common date set,
runs ``cards/cri_scoring.run_analysis``, persists the snapshot.

No external API calls — purely local DB reads + math + write.
"""

from __future__ import annotations

import logging
from datetime import date as _date

import numpy as np
from psycopg import Connection

from uw_scan.cards import cri_scoring
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
    vol_repo: VolIndexRepository, symbol: str, days: int
) -> dict[_date, float]:
    rows = vol_repo.fetch_history(symbol, days=days)
    return {
        r["trade_date"]: float(r["close"]) for r in rows if r.get("close") is not None
    }


def _load_spy_series(repo: Repository, days: int) -> dict[_date, float]:
    rows = repo.list_daily_ohlc("SPY", limit=days)
    return {r.date: float(r.close) for r in rows}


def _load_spx_series(vol_repo: VolIndexRepository, days: int) -> dict[_date, float]:
    """SPX closing levels from vol_index_daily (parquet-lake-backed)."""
    return _load_vol_series(vol_repo, "SPX", days)


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


def run(conn: Connection, schema: str = "uw_scan") -> int | None:
    """Run a CRI scan against the warm store; persist a new snapshot row.

    Returns the inserted row id, or None if there isn't enough aligned data.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    repo = Repository(conn, schema=schema)

    mandatory_vol = {
        "VIX": _load_vol_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_vol_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        "COR1M": _load_vol_series(vol_repo, "COR1M", LOOKBACK_DAYS),
    }

    # Attempt 1: SPX from vol_index_daily.
    aligned: dict[str, np.ndarray] = {}
    common_dates: list[str] = []
    spx = _load_spx_series(vol_repo, LOOKBACK_DAYS)
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
        spy = _load_spy_series(repo, LOOKBACK_DAYS)
        aligned, common_dates = _align({**mandatory_vol, "SPY": spy})

    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "cri_scan_skipped_thin_data aligned_bars=%d need=%d",
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        return None

    # VIX3M is optional and intentionally OUTSIDE the alignment join. We
    # want today's value (or the latest available close on the same date
    # as the CRI snapshot) for the term-structure tile; we do NOT want a
    # stale VIX3M sync to suppress the whole snapshot.
    vix3m_series = _load_vol_series(vol_repo, "VIX3M", LOOKBACK_DAYS)
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
        "cri_scan_persisted row_id=%d score=%.1f level=%s fired=%s",
        row_id,
        payload["cri"]["score"],
        payload["cri"]["level"],
        payload["crash_trigger"]["fired"],
    )
    return row_id
