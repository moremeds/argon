"""Top Net Impact scanner.

One UW call returns the market-wide ranking of tickers by net option premium
(net_call - net_put) for the session. We sort defensively by net_premium DESC,
assign a 1-based rank, and upsert — the repository carries each ticker's prior
rank into prev_rank so the chart can show per-update rank movement. Mirrors the
audit/scan-run bracket of `scanners.market_tide.run`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..api.client import UwClient
from ..sources import uw as uw_source
from ..storage.repository import Repository
from ..storage.top_net_impact_repository import TopNetImpactRepository

log = logging.getLogger(__name__)
ET_TZ = ZoneInfo("America/New_York")


def run(
    client: UwClient,
    repo: Repository,
    *,
    trading_date: date | None = None,
    limit: int = 40,
) -> int:
    """Fetch + persist one session's top-net-impact ranking; return row count."""
    run_id = repo.insert_scan_run("MARKET", notes="regime_top_net_impact_scan")
    try:
        rows = uw_source.fetch_top_net_impact(
            client, repo, run_id, trading_date=trading_date, limit=limit
        )
        # Defensive sort — never trust upstream order for the rank assignment.
        rows.sort(key=lambda r: r["net_premium"], reverse=True)
        d = trading_date or datetime.now(ET_TZ).date()
        ranked = [
            {
                "data_date": d,
                "ticker": r["ticker"],
                "net_premium": r["net_premium"],
                "rank": i + 1,
            }
            for i, r in enumerate(rows)
        ]
        tni_repo = TopNetImpactRepository(repo.conn, schema=repo._schema)
        n = tni_repo.upsert_rows(ranked)
        repo.finish_scan_run(run_id, status="ok")
        log.info("top_net_impact_scan_ok rows=%d date=%s", n, d)
        return n
    except Exception:
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status="error")
        raise
