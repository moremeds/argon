"""Nightly gold factor: livewire lake prices + FRED yields -> gold_factor_daily / dxy_synthetic_daily.

1. Read the IB 1-day MIDPOINT closes of XAUUSD (`bronze/asset_class=cmdty`) and the six dollar-index
   pairs (`bronze/asset_class=fx_ib`) from the lake, in memory. livewire writes them at ~17:20 New York
   time (launchd `com.livewire.ib-evening`); the bar dated D is 17:15 New York D-1 to 17:00 New York D.
   argon stores no raw prices: the old xenon path wrote them to macro_series_daily (source 'IB'); those
   rows stay but no longer grow.
2. Read DFII10 / DGS10 from macro_series_daily (FRED, gold_fred_ingest_job).
3. Recompute the whole history and upsert it: the rolling fit is cheap and a revised input converges
   at once. The synthetic dollar index is upserted from the same levels first; it needs only the pairs.
A leg whose last lake bar is older than the last completed session still lets the compute run on
what the lake has; the job then raises naming the legs, so the miss reaches job_failures.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg

from uw_scan.macro import gold_factor as gf
from uw_scan.sources.lake import read_vol_index_parquet
from uw_scan.storage import gold_factor as store
from uw_scan.worker.market_session import is_us_equity_market_day

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
BAR_CLOSE_NY = time(17, 0)


def last_closed_bar(now: datetime) -> date:
    """Newest bar date whose 17:00 New York close has passed."""
    ny = now.astimezone(NY)
    return ny.date() if ny.time() >= BAR_CLOSE_NY else ny.date() - timedelta(days=1)


def expected_bar(now: datetime) -> date:
    """The last NYSE session whose bar has closed. FX and gold also trade on some NYSE holidays;
    those bars are used when present but never required."""
    d = last_closed_bar(now)
    while not is_us_equity_market_day(d):
        d -= timedelta(days=1)
    return d


def read_lake_legs(lake_root: Path, now: datetime) -> pd.DataFrame:
    """Close of every price leg, one column per leg, completed bars only."""
    cutoff = last_closed_bar(now)
    cols = {}
    for leg in gf.PRICE_LEGS:
        asset_class = "cmdty" if leg == "XAUUSD" else "fx_ib"
        rows = read_vol_index_parquet(
            lake_root / "bronze" / f"asset_class={asset_class}", leg
        )
        cols[leg] = pd.Series(
            {
                pd.Timestamp(r["trade_date"]): r["close"]
                for r in rows
                if r["trade_date"] <= cutoff
            },
            dtype="float64",
        )
    return pd.DataFrame(cols).reindex(columns=list(gf.PRICE_LEGS))


def stale_legs(legs: pd.DataFrame, now: datetime) -> list[str]:
    want = expected_bar(now)
    out = []
    for leg in gf.PRICE_LEGS:
        s = legs[leg].dropna()
        last = s.index[-1].date() if len(s) else None
        if last is None or last < want:
            out.append(f"{leg}: last lake bar {last}, expected {want}")
    return out


def gold_factor_compute_job(
    *, dsn: str, lake_root: Path, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    legs = read_lake_legs(lake_root, now)
    stale = stale_legs(legs, now)
    with psycopg.connect(dsn) as conn:
        levels = legs.join(store.fetch_yields(conn), how="outer").reindex(
            columns=list(gf.INPUTS)
        )
        store.upsert_dxy_rows(conn, gf.dxy_daily(levels), datetime.now(UTC))
        chg = gf.changes(levels)
        if len(chg) < gf.W + 2:
            raise RuntimeError(
                f"gold_factor: {len(chg)} complete rows, need {gf.W + 2}; check the lake legs "
                "and seed FRED with scripts/backfill/gold_factor_seed.py"
            )
        n = store.upsert_rows(conn, gf.compute(chg), datetime.now(UTC))
    logger.info("gold_factor: upserted %d rows through %s", n, chg.index[-1].date())
    if stale:
        raise RuntimeError(f"gold_factor: computed, but lake legs are stale: {stale}")
    return n
