"""One-shot trigger for the two cockpit-feeding worker jobs.

Runs flow_data_refresh (populates option_chain_per_strike + options_volume_daily
for every watchlist ticker, including the freshly-added SPX) and
cockpit_daily_snapshot (populates greeks/skew/IV/RV/exposures and rebuilds
matrix_state_snapshots for the cockpit_tickers).

Use after editing the watchlist or when seeded data is too sparse for the
RV/IV-derived state fields. Idempotent — both jobs ON CONFLICT.
"""

from __future__ import annotations

import logging

import psycopg
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_jobs")


def main() -> None:
    settings = Settings.from_env()
    with (
        psycopg.connect(settings.db_dsn()) as conn,
        ExternalApiRequestRecorder(
            settings.db_dsn(), schema=settings.db_schema
        ) as recorder,
    ):
        repo = Repository(conn, schema=settings.db_schema)
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            telemetry_recorder=recorder,
            job_name="manual_backfill",
        )

        logger.info("=== flow_data_refresh: populating watchlist (incl. SPX) ===")
        flow_data_refresh(repo=repo, client=client, settings=settings)

        logger.info("=== cockpit_daily_snapshot: refreshing cockpit tickers ===")
        cockpit_daily_snapshot(repo=repo, client=client, settings=settings)

    logger.info("done")


if __name__ == "__main__":
    main()
