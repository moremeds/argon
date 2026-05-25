"""Nightly: equity-asset parquet lake → uw_scan.vol_index_daily for credit ETFs.

Mirrors ``vol_index_lake_sync`` but walks the ``asset_class=equity`` root and
filters down to a configured allow-list (HYG/JNK/LQD by default — the VCG
scanner's credit proxies). All rows land in ``vol_index_daily`` so the scanner
can read VIX/VVIX/<proxy> through a single repository.

Incremental: each symbol's max(trade_date) in the DB sets the lower bound for
the next read. First run backfills the full available history.

Accepts either a local-filesystem `Path` or a `LakeRoot` (R2 or local). The
scheduler now resolves the root via `resolve_lake_root(settings, asset_class=
'equity')` so this job reads from R2 when all four `R2_*` settings are
present, else from the local mirror.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
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

    `read_vol_index_parquet` is reused as-is — it's symbol-keyed and assumes
    `<root>/symbol=<SYM>/1d.parquet`, which is the same layout the equity
    asset_class folder uses. Returns {symbols: int, rows: int}.
    """
    if not symbols:
        return {"symbols": 0, "rows": 0}

    repo = VolIndexRepository(conn, schema="uw_scan")
    total = 0
    synced = 0
    for symbol in symbols:
        latest = repo.latest_date_for(symbol)
        # Read from one day before latest so a same-day snapshot that closes
        # differently still gets re-upserted.
        since = (latest - timedelta(days=1)) if latest else None
        rows = read_vol_index_parquet(root, symbol, since=since)
        if not rows:
            logger.info(
                "credit_etf_lake_sync: %s — no rows under %s/symbol=%s",
                symbol,
                root,
                symbol,
            )
            continue
        n = repo.upsert_rows(rows)
        total += n
        synced += 1
        logger.info("credit_etf_lake_sync: %s — %d rows since %s", symbol, n, since)
    return {"symbols": synced, "rows": total}
