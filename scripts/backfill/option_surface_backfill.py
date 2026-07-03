"""One-shot backfill for option_surface_grid_daily recent gaps. UW-bound, gated
behind --confirm and a self-spend cap. Sibling of intraday_buckets_backfill.py.

option_surface_backfill() walks the last --days-back weekdays ending yesterday,
oldest-first, and fills any market_date not already fully captured (idempotent,
per-ticker). A full day costs ~1.9k UW calls (1 + N_expiries per ticker).

--quota caps how many calls THIS run adds. The job's quota_limit compares against
the UW *server-side* daily counter (x-uw-daily-req-count), shared with the live
stack — so we pre-flight one probe call, read the current count, and pass
quota_limit = current + --quota. The run stops when the server total reaches that.

Reproduce (fill June gaps oldest-first, add at most 20k UW calls):
  uv run python scripts/backfill/option_surface_backfill.py --confirm --quota 20000 --days-back 17
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.uw import fetch_greek_exposure_by_expiry
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_surface_capture import option_surface_backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("surface_backfill")


def _client(
    s: Settings, recorder: ExternalApiRequestRecorder | None = None
) -> UwClient:
    return UwClient(
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        timeout=s.request_timeout_seconds,
        telemetry_recorder=recorder,
        job_name="option_surface_backfill",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument(
        "--quota", type=int, default=20000, help="max UW calls THIS run adds"
    )
    ap.add_argument("--days-back", type=int, default=17, help="weekdays back to scan")
    ap.add_argument(
        "--min-remaining",
        type=int,
        default=2000,
        help="abort if UW daily budget left is below this floor",
    )
    args = ap.parse_args()

    s = Settings.from_env()
    repo = Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
    # Telemetry recorder → backfill UW spend visible to the budget governor
    # (research pool), Phase 0.
    recorder = ExternalApiRequestRecorder(s.db_dsn(), schema=s.db_schema)
    client = _client(s, recorder)
    try:
        # Pre-flight: one probe call to read the server-side daily budget.
        cards = repo.list_watchlist_cards()
        if not cards:
            log.error("no watchlist cards")
            return 2
        probe = cards[0].ticker
        run_id = repo.insert_scan_run(probe, notes="option_surface_backfill_probe")
        fetch_greek_exposure_by_expiry(client, repo, run_id, probe, date=None)
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()

        used = client.rate_limit.daily_count
        limit = client.rate_limit.daily_limit
        remaining = (limit - used) if (limit is not None and used is not None) else None
        log.info("UW budget: used=%s limit=%s remaining=%s", used, limit, remaining)

        if remaining is not None and remaining < args.min_remaining:
            log.error(
                "only %s UW calls left (< %s floor) — aborting",
                remaining,
                args.min_remaining,
            )
            return 1

        # Cap THIS run at ~--quota added calls, never past the server hard limit.
        stop_at = (used or 0) + args.quota
        if limit is not None:
            stop_at = min(stop_at, limit)
        log.info("will stop when server daily count reaches %s", stop_at)

        if not args.confirm:
            log.info(
                "DRY RUN — would backfill days_back=%d, adding up to %d calls. Re-run with --confirm.",
                args.days_back,
                args.quota,
            )
            return 0

        written = option_surface_backfill(
            repo=repo, client=client, days_back=args.days_back, quota_limit=stop_at
        )
        log.info("DONE — wrote %d surface-grid rows", written)
        return 0
    finally:
        recorder.close()
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
