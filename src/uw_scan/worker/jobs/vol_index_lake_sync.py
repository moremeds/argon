"""Nightly: parquet lake → uw_scan.vol_index_daily.

Incremental: each symbol's max(trade_date) in the DB sets the lower bound for
the next read. First run backfills the entire history.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from psycopg import Connection

from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet
from uw_scan.storage.vol_index_repository import VolIndexRepository

logger = logging.getLogger(__name__)


def run_vol_index_lake_sync(conn: Connection, *, root: Path) -> dict:
    """Sync all symbols under root into uw_scan.vol_index_daily.

    Returns a summary dict: {symbols: int, rows: int}.
    """
    symbols = list_vol_index_symbols(root)
    if not symbols:
        logger.info("vol_index_lake_sync: no symbols at %s", root)
        return {"symbols": 0, "rows": 0}

    repo = VolIndexRepository(conn, schema="uw_scan")
    total = 0
    for symbol in symbols:
        latest = repo.latest_date_for(symbol)
        # Read from one day before latest (so we re-upsert the most recent
        # row in case it was a same-day snapshot that closed differently).
        since = (latest - timedelta(days=1)) if latest else None
        rows = read_vol_index_parquet(root, symbol, since=since)
        if rows:
            n = repo.upsert_rows(rows)
            total += n
            logger.info("vol_index_lake_sync: %s — %d rows since %s", symbol, n, since)
    return {"symbols": len(symbols), "rows": total}
