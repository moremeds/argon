"""Market-wide options tide scanner.

One UW call per tick returns the full day's 5-min net call/put premium series;
we upsert every bar (idempotent) and stamp the current 5-min bar with the live
index spot from the WS-fed `intraday_quote` table. Mirrors the audit/scan-run
bracket of `scanners.gex.run`.
"""

from __future__ import annotations

import logging
from datetime import date

from ..api.client import UwClient
from ..sources import uw as uw_source
from ..storage.market_tide_snapshot_repository import MarketTideSnapshotRepository
from ..storage.repository import Repository

log = logging.getLogger(__name__)


def run(
    client: UwClient,
    repo: Repository,
    *,
    spot_ticker: str = "SPY",
    trading_date: date | None = None,
    capture_spot: bool = True,
) -> int:
    """Fetch + persist one session of market tide; return the bar count.

    ``capture_spot`` stamps the live index spot onto the latest bar — correct
    for the realtime worker, but the backfill passes False (a current spot is
    meaningless against a past bar; historical overlay stays NULL).
    """
    run_id = repo.insert_scan_run("MARKET", notes="regime_market_tide_scan")
    try:
        bars = uw_source.fetch_market_tide(
            client, repo, run_id, trading_date=trading_date
        )
        tide_repo = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
        n = tide_repo.upsert_bars(bars)

        # Stamp the most-recent bar (the current 5-min bucket) with the live
        # index spot. Earlier ticks already stamped earlier bars; bars that
        # predate the worker's start today keep a NULL overlay.
        if bars and capture_spot:
            q = repo.get_intraday_quote(spot_ticker.upper())
            if q is not None and q.price is not None:
                latest = max(bars, key=lambda b: b["ts"])
                tide_repo.set_spot(
                    data_date=latest["data_date"],
                    ts=latest["ts"],
                    spot=q.price,
                    spot_ticker=spot_ticker.upper(),
                    spot_quoted_at=q.quoted_at,
                )

        repo.finish_scan_run(run_id, status="ok")
        log.info("market_tide_scan_ok bars=%d spot_ticker=%s", n, spot_ticker)
        return n
    except Exception:
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status="error")
        raise
