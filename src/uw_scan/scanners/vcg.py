"""VCG scanner — orchestrator on top of cards/vcg_scoring.

Reads VIX/VVIX/<credit-proxy> from vol_index_daily, aligns to a common date
set, runs ``cards/vcg_scoring.run_analysis``, persists the snapshot via
``VcgSnapshotRepository``.

No external API calls — all inputs come from the parquet-lake-backed
vol_index_daily table.
"""

from __future__ import annotations

import logging
from datetime import date as _date

import numpy as np
from psycopg import Connection

from uw_scan.cards import vcg_scoring
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger(__name__)

# Lookback — must cover the 252-day rolling percentile window (VIX/VVIX
# %ile) which is the largest budget. 21d OLS, 63d z-window, and 20-day
# history all fit inside that. Slack for proxy alignment gaps (HYG/JNK
# don't always overlap VIX days 1:1).
LOOKBACK_DAYS = 300
MIN_ALIGNED_BARS = vcg_scoring.MIN_BARS

DEFAULT_PROXY = "HYG"


def _load_series(
    vol_repo: VolIndexRepository,
    symbol: str,
    days: int,
    *,
    prefer_adj_close: bool = False,
) -> dict[_date, float]:
    """Build {date: price} from vol_index_daily.

    Credit ETFs (HYG/JNK/LQD) distribute monthly; using raw ``close`` would
    surface every ex-dividend drop as a log-return spike that the OLS reads
    as credit stress. Set ``prefer_adj_close=True`` for the credit proxy so
    distributions are absorbed at source; VIX/VVIX have no such adjustment
    and keep raw ``close``.
    """
    rows = vol_repo.fetch_history(symbol, days=days)
    out: dict[_date, float] = {}
    for r in rows:
        price = r.get("adj_close") if prefer_adj_close else None
        if price is None:
            price = r.get("close")
        if price is None:
            continue
        out[r["trade_date"]] = float(price)
    return out


def _align(
    series: dict[str, dict[_date, float]],
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Inner-join the series on shared dates."""
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
    *,
    proxy: str = DEFAULT_PROXY,
    schema: str = "uw_scan",
) -> int | None:
    """Run a VCG scan; persist a new snapshot row.

    Returns the inserted row id, or None if there isn't enough aligned data.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX": _load_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        proxy: _load_series(vol_repo, proxy, LOOKBACK_DAYS, prefer_adj_close=True),
    }
    aligned, common_dates = _align(raw)

    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "vcg_scan_skipped_thin_data proxy=%s aligned_bars=%d need=%d",
            proxy,
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        return None

    payload = vcg_scoring.run_analysis(aligned, common_dates, proxy=proxy)
    snap_repo = VcgSnapshotRepository(conn, schema=schema)
    data_date = _date.fromisoformat(payload["date"])
    row_id = snap_repo.insert_snapshot(payload=payload, data_date=data_date)
    sig = payload["signal"]
    log.info(
        "vcg_scan_persisted row_id=%d proxy=%s vcg=%s interp=%s ro=%d edr=%d",
        row_id,
        proxy,
        sig.get("vcg"),
        sig.get("interpretation"),
        sig.get("ro", 0),
        sig.get("edr", 0),
    )
    return row_id
