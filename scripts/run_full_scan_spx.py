"""Run the single-stock pipeline once for SPX so flow_events + watchlist_card
get populated. This is the missing-spot fix for `flow_data_refresh: SPX missing
spot`: run_single_stock pulls flow + IV + greeks and computes the card row
(including spot price), which unblocks future flow_data_refresh runs.
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("spx_seed")


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
            job_name="spx_seed",
        )
        for ticker in ("SPX", "SPY", "QQQ", "IWM"):
            try:
                report = run_single_stock(ticker, client, repo)
                history = repo.list_daily_ohlc(ticker, limit=40)
                intraday = repo.get_intraday_quote(ticker)
                prior_pcr = repo.get_pcr_history_30d_ago(
                    ticker, today=report.generated_at.date()
                )
                card_row = compute_watchlist_card_row(
                    report, history, intraday, prior_pcr
                )
                repo.upsert_watchlist_card(**card_row)
                conn.commit()
                logger.info("seeded %s", ticker)
            except Exception:
                logger.exception("failed seeding %s", ticker)
                conn.rollback()
    logger.info("done")


if __name__ == "__main__":
    main()
