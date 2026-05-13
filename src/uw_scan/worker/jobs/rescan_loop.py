"""Ad-hoc rescan loop: claim one queued job from uw_scan.jobs, run it, mark done/failed."""

from __future__ import annotations

import logging

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.pipeline import run_single_stock
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def rescan_tick(repo, uw_client, ohlc_provider: OhlcProvider) -> bool:
    """Process one queued rescan. Returns True if a job ran, False if the queue was empty."""
    _ = ohlc_provider  # unused here; cards derive uses repo's persisted OHLC
    # Heartbeat unconditionally — this loop fires every 1s, so its liveness
    # is the closest signal we have to "worker is up." Sidebar HealthPanel
    # reads now() - last_beat_at to render the worker dot.
    repo.upsert_heartbeat("rescan_tick")
    job = repo.claim_next_queued_job()
    if job is None:
        return False
    try:
        report = run_single_stock(job.ticker, uw_client, repo)
        history = repo.list_daily_ohlc(job.ticker, limit=40)
        intraday = repo.get_intraday_quote(job.ticker)
        prior_pcr = repo.get_pcr_history_30d_ago(
            job.ticker, today=report.generated_at.date()
        )
        card_row = compute_watchlist_card_row(report, history, intraday, prior_pcr)
        repo.upsert_watchlist_card(**card_row)
        repo.mark_job_done(str(job.id), report.run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("rescan job %s failed: %s", job.id, repr(exc))
        repo.mark_job_failed(str(job.id), repr(exc))
        return True
