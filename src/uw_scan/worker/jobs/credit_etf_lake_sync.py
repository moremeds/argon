"""Nightly: equity-asset parquet lake → uw_scan.vol_index_daily for credit ETFs.

Mirrors ``vol_index_lake_sync`` but walks the ``asset_class=equity`` root and
filters down to a configured allow-list (HYG/JNK/LQD by default — the VCG
scanner's credit proxies). All rows land in ``vol_index_daily`` so the scanner
can read VIX/VVIX/<proxy> through a single repository.

Gap-aware: each run reads the full R2 history per symbol, compares against the
dates already in `vol_index_daily`, and upserts only the missing dates plus the
current latest. Heals tail-and-middle drift between R2 and the DB on every run.

Accepts either a local-filesystem `Path` or a `LakeRoot` (R2 or local). The
scheduler resolves the root via `resolve_lake_root(settings, asset_class=
'equity')` so this job reads from R2 when all four `R2_*` settings are
present, else from the local mirror.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from psycopg import Connection

from uw_scan.sources.lake import read_vol_index_parquet
from uw_scan.sources.lake_resolver import LakeRoot
from uw_scan.storage.vol_index_repository import VolIndexRepository

logger = logging.getLogger(__name__)


def run_credit_etf_lake_sync(
    conn: Connection,
    *,
    root: Path | LakeRoot,
    symbols: Sequence[str],
) -> dict:
    """Sync `symbols` under root into uw_scan.vol_index_daily.

    Returns {symbols: int, rows: int, gaps_filled: int}. `gaps_filled`
    counts R2 dates that were missing from the DB before this run.
    """
    if not symbols:
        return {"symbols": 0, "rows": 0, "gaps_filled": 0}

    repo = VolIndexRepository(conn, schema="uw_scan")
    total_rows = 0
    total_gaps = 0
    synced = 0
    for symbol in symbols:
        r2_rows = read_vol_index_parquet(root, symbol)
        if not r2_rows:
            logger.warning(
                "credit_etf_lake_sync: %s — no rows in lake (symbol absent OR "
                "lake returned empty mid-write); skipping",
                symbol,
            )
            continue
        r2_dates = {r["trade_date"] for r in r2_rows}
        db_dates = repo.fetch_dates_for(symbol)
        latest = max(db_dates) if db_dates else None
        to_pull_dates = (r2_dates - db_dates) | ({latest} if latest else set())
        rows_to_upsert = [r for r in r2_rows if r["trade_date"] in to_pull_dates]
        if not rows_to_upsert:
            continue
        gaps = len(r2_dates - db_dates)
        n = repo.upsert_rows(rows_to_upsert)
        total_rows += n
        total_gaps += gaps
        synced += 1
        logger.info(
            "credit_etf_lake_sync: %s — %d rows upserted (%d gaps filled), latest=%s",
            symbol,
            n,
            gaps,
            latest,
        )
    return {"symbols": synced, "rows": total_rows, "gaps_filled": total_gaps}
