"""VCG scanner — orchestrator on top of cards/vcg_scoring.

Reads VIX/VVIX/<credit-proxy> from vol_index_daily, aligns to a common date
set, runs ``cards/vcg_scoring.run_analysis``, persists the snapshot via
``VcgSnapshotRepository``.

No external API calls — all inputs come from the parquet-lake-backed
vol_index_daily table.

Recovery: ``recover_recent_gaps`` walks the last N trading days and runs
the scanner for any day that has aligned vol_index_daily data but no
vcg_snapshots row.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date as _date
from datetime import timedelta

import numpy as np
from psycopg import Connection

from uw_scan.cards import vcg_scoring
from uw_scan.scanners.live_quotes import (
    LiveQuote,
    carry_forward,
    live_session_date,
    quotes_payload,
    splice_session_value,
)
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
    as_of: _date | None = None,
) -> dict[_date, float]:
    """Build {date: price} from vol_index_daily.

    Credit ETFs (HYG/JNK/LQD) distribute monthly; using raw ``close`` would
    surface every ex-dividend drop as a log-return spike that the OLS reads
    as credit stress. Set ``prefer_adj_close=True`` for the credit proxy so
    distributions are absorbed at source; VIX/VVIX have no such adjustment
    and keep raw ``close``.

    When ``as_of`` is set the lookback caps at ``trade_date <= as_of`` so
    the historical-recovery path can re-aim the scanner at a previous day.
    """
    fetch_days = days * 2 if as_of is not None else days
    rows = vol_repo.fetch_history(symbol, days=fetch_days)
    if as_of is not None:
        rows = [r for r in rows if r["trade_date"] <= as_of]
        rows = rows[-days:]
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
    as_of: _date | None = None,
) -> int | None:
    """Run a VCG scan; persist a new snapshot row.

    When ``as_of`` is set, the scanner computes for that historical date by
    capping every loaded series; the snapshot persists with
    ``data_date=as_of``. Used by ``recover_recent_gaps``.

    Returns the inserted row id, or None if there isn't enough aligned data.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX": _load_series(vol_repo, "VIX", LOOKBACK_DAYS, as_of=as_of),
        "VVIX": _load_series(vol_repo, "VVIX", LOOKBACK_DAYS, as_of=as_of),
        proxy: _load_series(
            vol_repo,
            proxy,
            LOOKBACK_DAYS,
            prefer_adj_close=True,
            as_of=as_of,
        ),
    }
    aligned, common_dates = _align(raw)

    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "vcg_scan_skipped_thin_data proxy=%s aligned_bars=%d need=%d as_of=%s",
            proxy,
            len(common_dates),
            MIN_ALIGNED_BARS,
            as_of,
        )
        return None

    payload = vcg_scoring.run_analysis(aligned, common_dates, proxy=proxy)
    snap_repo = VcgSnapshotRepository(conn, schema=schema)
    data_date = _date.fromisoformat(payload["date"])
    row_id = snap_repo.insert_snapshot(payload=payload, data_date=data_date)
    sig = payload["signal"]
    log.info(
        "vcg_scan_persisted row_id=%d data_date=%s proxy=%s vcg=%s interp=%s ro=%d edr=%d",
        row_id,
        data_date,
        proxy,
        sig.get("vcg"),
        sig.get("interpretation"),
        sig.get("ro", 0),
        sig.get("edr", 0),
    )
    return row_id


def run_live(
    conn: Connection,
    schema: str = "uw_scan",
    *,
    quotes: Mapping[str, LiveQuote],
    proxy: str = DEFAULT_PROXY,
    persist: bool = False,
) -> dict | None:
    """VCG computed with live quotes spliced as today's provisional close.

    The live credit price splices onto the adj_close series — adj_close
    equals close between distributions, so an intraday HYG last-price is a
    consistent provisional bar until the next ex-div date re-syncs from
    the lake overnight. Slim persist (no history) with basis='live'.
    """
    session_date = live_session_date(quotes)
    if session_date is None:
        return None

    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX": _load_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        proxy: _load_series(vol_repo, proxy, LOOKBACK_DAYS, prefer_adj_close=True),
    }
    live_syms: list[str] = []
    carried: list[str] = []
    for sym in list(raw):
        q = quotes.get(sym)
        if q is not None:
            raw[sym] = splice_session_value(raw[sym], q.price, session_date)
            live_syms.append(sym)
        else:
            raw[sym], was_carried = carry_forward(raw[sym], session_date)
            if was_carried:
                carried.append(sym)
    if not live_syms:
        return None

    aligned, common_dates = _align(raw)
    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "vcg_live_skipped_thin_data proxy=%s aligned_bars=%d need=%d",
            proxy,
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        return None

    payload = vcg_scoring.run_analysis(aligned, common_dates, proxy=proxy)
    payload["basis"] = "live"
    payload["live_quotes"] = quotes_payload(quotes)
    payload["carried_forward"] = carried

    if persist:
        slim = {k: v for k, v in payload.items() if k != "history"}
        snap_repo = VcgSnapshotRepository(conn, schema=schema)
        row_id = snap_repo.insert_snapshot(
            payload=slim, data_date=session_date, basis="live"
        )
        log.info(
            "vcg_live_persisted row_id=%d session=%s proxy=%s vcg=%s",
            row_id,
            session_date,
            proxy,
            payload["signal"].get("vcg"),
        )
    return payload


def _existing_vcg_dates(
    conn: Connection, schema: str, *, since: _date, proxy: str
) -> set[_date]:
    """Distinct EOD ``data_date`` in ``vcg_snapshots`` for ``proxy`` since ``since``.

    Filters by ``payload->>'credit_proxy'`` (the field name vcg_scoring
    writes) so swapping HYG → JNK in config doesn't cause us to skip the
    JNK day because an HYG row happened to land on it. basis='eod' only —
    a 5-min live row landing on today's date must not suppress the EOD
    gap recovery for that same date.
    """
    sql = f"""
        SELECT DISTINCT data_date
          FROM {schema}.vcg_snapshots
         WHERE data_date IS NOT NULL
           AND data_date >= %s
           AND payload->>'credit_proxy' = %s
           AND basis = 'eod'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since, proxy))
        return {r[0] for r in cur.fetchall()}


def recover_recent_gaps(
    conn: Connection,
    schema: str = "uw_scan",
    *,
    proxy: str = DEFAULT_PROXY,
    lookback_days: int = 7,
) -> dict:
    """Fill any missing VCG snapshot in the last ``lookback_days`` trading days.

    Mirrors the CRI recovery shape — see ``scanners/cri.recover_recent_gaps``
    for the doc and contract.
    """
    vol_repo = VolIndexRepository(conn, schema=schema)
    vix = vol_repo.fetch_dates_for("VIX")
    vvix = vol_repo.fetch_dates_for("VVIX")
    proxy_dates = vol_repo.fetch_dates_for(proxy)
    if not (vix and vvix and proxy_dates):
        log.info("vcg_recover_skipped: mandatory series missing in lake")
        return {"checked": 0, "filled": 0, "skipped": 0}

    aligned_days = sorted(vix & vvix & proxy_dates)
    latest = aligned_days[-1]
    cutoff = latest - timedelta(days=lookback_days)
    window = [d for d in aligned_days if d >= cutoff]

    existing = _existing_vcg_dates(conn, schema, since=cutoff, proxy=proxy)
    missing = [d for d in window if d not in existing]

    filled = 0
    skipped = 0
    for d in missing:
        try:
            rid = run(conn, proxy=proxy, schema=schema, as_of=d)
            if rid is None:
                skipped += 1
            else:
                filled += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("vcg_recover_failed as_of=%s err=%s", d, repr(exc))
            conn.rollback()
            skipped += 1

    log.info(
        "vcg_recover_done proxy=%s checked=%d filled=%d skipped=%d lookback=%dd",
        proxy,
        len(window),
        filled,
        skipped,
        lookback_days,
    )
    return {"checked": len(window), "filled": filled, "skipped": skipped}
