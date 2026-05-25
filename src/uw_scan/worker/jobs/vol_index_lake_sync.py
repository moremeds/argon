"""Nightly: parquet lake → uw_scan.vol_index_daily.

Incremental: each symbol's max(trade_date) in the DB sets the lower bound for
the next read. First run backfills the entire history.

Accepts either a local-filesystem `Path` or a `LakeRoot` (R2 or local). The
scheduler now resolves the root via `resolve_lake_root(settings, asset_class=
'volatility')` so this job reads from R2 when all four `R2_*` settings are
present, else from the local mirror. Existing Path-based callers (e.g.
`tests/integration/test_vol_index_lake_sync.py`) continue to work via the
`_normalize` shim inside `lake.py`.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from psycopg import Connection

from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet
from uw_scan.sources.lake_resolver import LakeRoot
from uw_scan.storage.vol_index_repository import VolIndexRepository

logger = logging.getLogger(__name__)


def run_vol_index_lake_sync(conn: Connection, *, root: Path | LakeRoot) -> dict:
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
