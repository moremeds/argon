"""EOD market-tide sentiment persistence.

Reads the most-recent session's bars from market_tide_snapshots, computes the
slope/sentiment, and upserts the daily row. Idempotent. Pure DB→DB (no UW
calls) — the bars were already captured by the 5-min market-tide scan.
"""

from __future__ import annotations

import logging

from ...reports.market_tide_sentiment import compute_sentiment
from ...storage.market_tide_sentiment_repository import MarketTideSentimentRepository
from ...storage.market_tide_snapshot_repository import MarketTideSnapshotRepository
from ...storage.repository import Repository

log = logging.getLogger(__name__)


def refresh_eod_sentiment(repo: Repository, *, sessions: int = 1) -> int:
    """Compute + upsert sentiment for the latest `sessions` sessions. Returns
    the count persisted."""
    tide = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    sink = MarketTideSentimentRepository(repo.conn, schema=repo._schema)
    rows = tide.fetch_sessions(sessions=sessions)
    n = 0
    for s in rows:
        if not s["points"]:
            continue
        sent = compute_sentiment(s["points"])
        sink.upsert(s["date"], sent)
        n += 1
        log.info(
            "market_tide_sentiment_eod date=%s state=%s/%s driver=%s trend=%.2f",
            s["date"],
            sent.state,
            sent.magnitude,
            sent.driver,
            sent.trend_strength or 0.0,
        )
    return n
