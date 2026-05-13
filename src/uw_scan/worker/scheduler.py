"""APScheduler driver: registers the three cron jobs + the ad-hoc rescan poll."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.jobs.rescan_loop import rescan_tick
from uw_scan.worker.jobs.spot_refresh import spot_refresh_once
from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
    nightly_vol_analytics_rollup,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("uw_scan.worker")


@contextmanager
def _repo(settings: Settings) -> Iterator[Repository]:
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


def _uw_client(settings: Settings) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )


def _ohlc_provider(settings: Settings) -> MassiveOhlcProvider | None:
    if settings.massive_api_key is None:
        logger.warning("MASSIVE_API_KEY not set; OHLC jobs are no-ops")
        return None
    return MassiveOhlcProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
    )


class _NoOhlc:
    """Null-object OhlcProvider for runs without a Massive key."""

    def fetch_daily(self, *_a, **_k):
        return []

    def fetch_intraday_quote(self, *_a, **_k):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def close(self):
        pass


def main() -> int:
    settings = Settings.from_env()
    sched = BlockingScheduler(timezone=settings.rth_tz)

    def _spot_refresh() -> None:
        provider = _ohlc_provider(settings)
        if provider is None:
            return
        try:
            with _repo(settings) as repo:
                n = spot_refresh_once(repo, provider)
                logger.info("spot_refresh updated %d cards", n)
        finally:
            provider.close()

    def _full_scan() -> None:
        with _uw_client(settings) as uw:
            ohlc = _ohlc_provider(settings) or _NoOhlc()
            try:
                with _repo(settings) as repo:
                    n = full_scan_once(repo, uw, ohlc)
                    logger.info("full_scan completed %d tickers", n)
            finally:
                ohlc.close()

    def _ohlc_pull() -> None:
        provider = _ohlc_provider(settings)
        if provider is None:
            return
        try:
            with _repo(settings) as repo:
                n = ohlc_pull_once(repo, provider)
                logger.info("ohlc_pull refreshed %d tickers", n)
        finally:
            provider.close()

    def _rescan() -> None:
        with _uw_client(settings) as uw:
            ohlc = _ohlc_provider(settings) or _NoOhlc()
            try:
                with _repo(settings) as repo:
                    rescan_tick(repo, uw, ohlc)
            finally:
                ohlc.close()

    def _spy_ohlc_refresh() -> None:
        if settings.massive_api_key is None:
            logger.warning("MASSIVE_API_KEY not set; skipping SPY refresh")
            return
        with _repo(settings) as repo:
            daily_spy_ohlc_refresh(
                repo=repo,
                api_key=settings.massive_api_key.get_secret_value(),
                tz=settings.rth_tz,
            )

    def _vol_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_vol_analytics_rollup(repo=repo)

    def _flow_data_refresh() -> None:
        with _uw_client(settings) as uw:
            with _repo(settings) as repo:
                flow_data_refresh(repo=repo, client=uw, settings=settings)

    def _trade_insights_ai_tick() -> None:
        trade_insights_ai_tick(settings)

    sched.add_job(
        _spot_refresh,
        IntervalTrigger(seconds=settings.spot_refresh_seconds),
        id="spot_refresh",
        name="Spot refresh",
    )
    sched.add_job(
        _full_scan,
        CronTrigger.from_crontab(settings.full_scan_cron, timezone=settings.rth_tz),
        id="full_scan",
        name="Full UW scan",
    )
    sched.add_job(
        _ohlc_pull,
        CronTrigger.from_crontab(settings.ohlc_pull_cron, timezone=settings.rth_tz),
        id="ohlc_pull",
        name="Daily OHLC pull",
    )
    sched.add_job(
        _rescan,
        IntervalTrigger(seconds=1),
        id="rescan_tick",
        name="Ad-hoc rescan poll",
    )
    # Volatility tab v2 jobs — ET-anchored via from_crontab (review I9).
    sched.add_job(
        _spy_ohlc_refresh,
        CronTrigger.from_crontab("30 16 * * 1-5", timezone=settings.rth_tz),
        id="daily_spy_ohlc_refresh",
        name="Daily SPY OHLC refresh",
    )
    sched.add_job(
        _vol_analytics_rollup,
        CronTrigger.from_crontab("0 18 * * 1-5", timezone=settings.rth_tz),
        id="nightly_vol_analytics_rollup",
        name="Nightly vol analytics rollup",
    )
    sched.add_job(
        _flow_data_refresh,
        CronTrigger.from_crontab("15 18 * * 1-5", timezone=settings.rth_tz),
        id="nightly_flow_data_refresh",
        name="Nightly Flow tab data refresh",
    )
    if settings.trade_insights_ai_enabled:
        sched.add_job(
            _trade_insights_ai_tick,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick",
            name="Trade Insights AI analysis poll",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )

    def _stop(_sig, _frame):
        logger.info("received signal, shutting down scheduler")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("scheduler started")
    sched.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
