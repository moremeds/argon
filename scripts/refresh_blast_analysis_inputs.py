"""One-shot refresh of the two source tables the trade-blast lane reads
from (`uw_positioning` and `massive_fundamentals`).

The APScheduler worker normally keeps these tables fresh via the
`positioning_refresh` (06:00 ET, Sun-Thu) and `fundamentals_refresh`
(19:00 ET, Sun-Thu) cron jobs (see src/uw_scan/worker/scheduler.py). When
running without a long-lived worker process (e.g. local dev outside
`bash scripts/dev.sh`), those tables can sit empty and the blast lane's
framework conviction ledger collapses — short-interest, earnings reactions
and fundamentals all degrade to `na`.

This script invokes `positioning_refresh_once` and `fundamentals_refresh_once`
directly against the active watchlist, with the same construction shape the
scheduler uses (per src/uw_scan/worker/scheduler.py::_uw_client,
_fundamentals_provider, _repo). It is idempotent; running it twice produces
the same DB state as the cron jobs running twice.

Usage:
    uv run python scripts/refresh_blast_analysis_inputs.py            # all watchlist tickers
    uv run python scripts/refresh_blast_analysis_inputs.py --ticker TSLA
    uv run python scripts/refresh_blast_analysis_inputs.py --skip-fundamentals
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once
from uw_scan.worker.jobs.positioning_jobs import positioning_refresh_once

logger = logging.getLogger("refresh_blast_analysis_inputs")


def _build_uw_client(settings: Settings) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        job_name="refresh_blast_analysis_inputs",
    )


def _build_fundamentals_provider(settings: Settings):
    from uw_scan.sources.massive_fundamentals import MassiveFundamentalsProvider

    if settings.massive_api_key is None:
        return None
    return MassiveFundamentalsProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
        timeout=settings.request_timeout_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh blast lane source tables (uw_positioning + massive_fundamentals)."
    )
    parser.add_argument(
        "--ticker",
        help="Refresh just one ticker (case-insensitive). Default: all watchlist.",
    )
    parser.add_argument(
        "--skip-positioning",
        action="store_true",
        help="Skip the UW positioning refresh leg.",
    )
    parser.add_argument(
        "--skip-fundamentals",
        action="store_true",
        help="Skip the massive fundamentals refresh leg.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    settings = Settings.from_env()
    ticker_filter: Callable[[str], bool] | None = None
    if args.ticker:
        ticker_upper = args.ticker.upper()
        # Watchlist tickers are uppercase by convention, but compare
        # case-insensitively so an --ticker tsla never silently no-ops.
        ticker_filter = lambda t: t.upper() == ticker_upper  # noqa: E731

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)

        if not args.ticker:
            # No per-ticker scope; default refreshes the whole active watchlist.
            # Positioning hits 5 UW endpoints per ticker; fundamentals hits 3
            # Massive endpoints per ticker. Surface the rough call count up
            # front so an operator doesn't burn their daily budget unaware.
            tickers = repo.list_active_watchlist()
            est_positioning = 0 if args.skip_positioning else len(tickers) * 5
            est_fundamentals = 0 if args.skip_fundamentals else len(tickers) * 3
            logger.warning(
                "default-all refresh: %d active watchlist tickers — "
                "est %d UW calls + %d Massive calls; pass --ticker T to scope down",
                len(tickers),
                est_positioning,
                est_fundamentals,
            )

        if not args.skip_positioning:
            with _build_uw_client(settings) as uw:
                n = positioning_refresh_once(repo, uw, ticker_filter=ticker_filter)
                logger.info("positioning_refresh: refreshed %d tickers", n)
        else:
            logger.info("positioning_refresh: skipped (--skip-positioning)")

        if not args.skip_fundamentals:
            provider = _build_fundamentals_provider(settings)
            if provider is None:
                logger.warning("MASSIVE_API_KEY not set; skipping fundamentals refresh")
            else:
                try:
                    n = fundamentals_refresh_once(
                        repo, provider, ticker_filter=ticker_filter
                    )
                    logger.info("fundamentals_refresh: refreshed %d tickers", n)
                finally:
                    provider.close()
        else:
            logger.info("fundamentals_refresh: skipped (--skip-fundamentals)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
