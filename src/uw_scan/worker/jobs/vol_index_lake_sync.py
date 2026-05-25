"""Nightly: parquet lake → uw_scan.vol_index_daily.

Gap-aware: each run reads the full R2 history for every symbol, compares against
the dates already in `vol_index_daily`, and upserts ONLY the missing dates plus
the current latest (which may have an intra-session refresh). Backfills the full
history on first run; on every subsequent run it heals any drift between R2 and
the DB regardless of where the gap is (tail or middle).

Accepts either a local-filesystem `Path` or a `LakeRoot` (R2 or local). The
scheduler resolves the root via `resolve_lake_root(settings, asset_class=
'volatility')` so this job reads from R2 when all four `R2_*` settings are
present, else from the local mirror. Existing Path-based callers (e.g.
`tests/integration/test_vol_index_lake_sync.py`) continue to work via the
`_normalize` shim inside `lake.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from psycopg import Connection

from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet
from uw_scan.sources.lake_resolver import LakeRoot
from uw_scan.storage.vol_index_repository import VolIndexRepository

logger = logging.getLogger(__name__)


def run_vol_index_lake_sync(conn: Connection, *, root: Path | LakeRoot) -> dict:
    """Sync all symbols under root into uw_scan.vol_index_daily.

    Returns a summary dict: {symbols: int, rows: int, gaps_filled: int}.
    `gaps_filled` counts dates that existed in R2 but were missing from the DB
    before this run — surfaces drift without spamming the logs.
    """
    symbols = list_vol_index_symbols(root)
    if not symbols:
        logger.info("vol_index_lake_sync: no symbols at %s", root)
        return {"symbols": 0, "rows": 0, "gaps_filled": 0}

    repo = VolIndexRepository(conn, schema="uw_scan")
    total_rows = 0
    total_gaps = 0
    for symbol in symbols:
        r2_rows = read_vol_index_parquet(root, symbol)
        if not r2_rows:
            continue
        r2_dates = {r["trade_date"] for r in r2_rows}
        db_dates = repo.fetch_dates_for(symbol)
        # Always re-upsert the latest known DB row in case the lake's
        # most-recent close was revised after our last sync (intra-session
        # final-vs-snapshot drift). The `or {None}` guard handles first-run
        # symbols where db_dates is empty.
        latest = max(db_dates) if db_dates else None
        to_pull_dates = (r2_dates - db_dates) | ({latest} if latest else set())
        rows_to_upsert = [r for r in r2_rows if r["trade_date"] in to_pull_dates]
        if not rows_to_upsert:
            continue
        gaps = len(r2_dates - db_dates)
        n = repo.upsert_rows(rows_to_upsert)
        total_rows += n
        total_gaps += gaps
        logger.info(
            "vol_index_lake_sync: %s — %d rows upserted (%d gaps filled), latest=%s",
            symbol,
            n,
            gaps,
            latest,
        )
    return {"symbols": len(symbols), "rows": total_rows, "gaps_filled": total_gaps}
