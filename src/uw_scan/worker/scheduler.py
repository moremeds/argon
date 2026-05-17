"""APScheduler driver: registers the three cron jobs + the ad-hoc rescan poll."""

from __future__ import annotations

import logging
import signal
import sys
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

import psycopg
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.jobs.rescan_loop import rescan_tick
from uw_scan.worker.jobs.spot_refresh import spot_refresh_once
from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
    nightly_vol_analytics_rollup,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("uw_scan.worker")
RESCAN_WORKER_CONCURRENCY = 2
WorkerGroup = Literal["uw", "massive", "ai"]
WORKER_ROLES: set[str] = {"all", "uw", "massive"}


def _spot_refresh_market_date(now: datetime) -> date | None:
    """Return the ET market date when delayed minute bars are worth polling."""
    local = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    if local.weekday() >= 5:
        return None
    current = local.time()
    if time(9, 30) <= current <= time(20, 15):
        return local.date()
    return None


def _uw_auto_request_allowed(now: datetime) -> bool:
    """Return True during the weekday ET window where scheduled flow refresh may run."""
    local = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    if local.weekday() >= 5:
        return False
    current = local.time()
    return time(5, 0) <= current < time(20, 0)


def _validate_worker_settings(settings: Settings) -> None:
    role = settings.worker_role.lower()
    if role not in WORKER_ROLES:
        raise RuntimeError(
            "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive "
            f"(got {settings.worker_role!r})"
        )
    if settings.worker_count < 1:
        raise RuntimeError("UW_SCAN_WORKER_COUNT must be >= 1")
    if settings.worker_index < 0 or settings.worker_index >= settings.worker_count:
        raise RuntimeError(
            "UW_SCAN_WORKER_INDEX must be between 0 and "
            f"{settings.worker_count - 1} (got {settings.worker_index})"
        )


def _worker_groups(settings: Settings) -> set[WorkerGroup]:
    role = settings.worker_role.lower()
    if role == "all":
        return {"uw", "massive", "ai"}
    if role == "uw":
        return {"uw"}
    if role == "massive":
        return {"massive"}
    raise RuntimeError(
        "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive "
        f"(got {settings.worker_role!r})"
    )


def _worker_owns_ticker(ticker: str, *, index: int, count: int) -> bool:
    if count <= 1:
        return True
    normalized = ticker.strip().upper().encode("utf-8")
    return zlib.crc32(normalized) % count == index


def _ticker_shard_filter(settings: Settings) -> Callable[[str], bool]:
    _validate_worker_settings(settings)
    return lambda ticker: _worker_owns_ticker(
        ticker, index=settings.worker_index, count=settings.worker_count
    )


def _rescan_worker_concurrency(settings: Settings) -> int:
    if settings.worker_role.lower() == "uw" and settings.worker_count > 1:
        return 1
    return RESCAN_WORKER_CONCURRENCY


def _is_primary_worker(settings: Settings) -> bool:
    return settings.worker_role.lower() == "all" or settings.worker_index == 0


def _worker_label(settings: Settings) -> str:
    role = settings.worker_role.lower()
    if role == "all":
        return "all"
    return f"{role}-{settings.worker_index}-of-{settings.worker_count}"


def _worker_heartbeat_name(settings: Settings) -> str:
    role = settings.worker_role.lower()
    if role == "all":
        return "worker"
    return f"worker:{role}:{settings.worker_index}"


def _record_worker_heartbeat(settings: Settings) -> None:
    with _repo(settings) as repo:
        repo.upsert_heartbeat(_worker_heartbeat_name(settings))


@contextmanager
def _repo(settings: Settings) -> Iterator[Repository]:
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


@contextmanager
def _external_api_recorder(settings: Settings) -> Iterator[ExternalApiRequestRecorder]:
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    try:
        yield recorder
    finally:
        recorder.close()


def _uw_client(
    settings: Settings,
    *,
    telemetry_recorder: ExternalApiRequestRecorder | None = None,
    job_name: str | None = None,
) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        telemetry_recorder=telemetry_recorder,
        job_name=job_name,
    )


def _ohlc_provider(
    settings: Settings,
    *,
    telemetry_recorder: ExternalApiRequestRecorder | None = None,
    job_name: str | None = None,
) -> MassiveOhlcProvider | None:
    if settings.massive_api_key is None:
        logger.warning("MASSIVE_API_KEY not set; OHLC jobs are no-ops")
        return None
    return MassiveOhlcProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
        timeout=settings.request_timeout_seconds,
        telemetry_recorder=telemetry_recorder,
        job_name=job_name,
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
    _validate_worker_settings(settings)
    groups = _worker_groups(settings)
    ticker_filter = _ticker_shard_filter(settings)
    sched = BlockingScheduler(timezone=settings.rth_tz)

    def _spot_refresh() -> None:
        now = datetime.now(ZoneInfo(settings.rth_tz))
        market_date = _spot_refresh_market_date(now)
        with _repo(settings) as repo:
            repo.upsert_heartbeat("spot_refresh")
        if market_date is None:
            logger.debug("spot_refresh skipped outside market hours")
            return
        with _external_api_recorder(settings) as recorder:
            provider = _ohlc_provider(
                settings, telemetry_recorder=recorder, job_name="spot_refresh"
            )
            if provider is None:
                return
            try:
                with _repo(settings) as repo:
                    n = spot_refresh_once(
                        repo,
                        provider,
                        market_date=market_date,
                        ticker_filter=ticker_filter,
                    )
                    logger.info("spot_refresh updated %d cards", n)
            finally:
                provider.close()

    def _full_scan() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="full_scan"
            ) as uw:
                with _repo(settings) as repo:
                    # _NoOhlc() is intentional: OHLC fetches are owned by
                    # _ohlc_pull / _spot_refresh. See worker/CLAUDE.md
                    # "Provider concurrency model".
                    n = full_scan_once(repo, uw, _NoOhlc(), ticker_filter=ticker_filter)
                    logger.info("full_scan completed %d tickers", n)

    def _ohlc_pull() -> None:
        with _external_api_recorder(settings) as recorder:
            provider = _ohlc_provider(
                settings, telemetry_recorder=recorder, job_name="ohlc_pull"
            )
            if provider is None:
                return
            try:
                with _repo(settings) as repo:
                    n = ohlc_pull_once(repo, provider, ticker_filter=ticker_filter)
                    logger.info("ohlc_pull refreshed %d tickers", n)
            finally:
                provider.close()

    def _rescan() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="rescan_tick"
            ) as uw:
                with _repo(settings) as repo:
                    # _NoOhlc() is intentional: OHLC fetches are owned by
                    # _ohlc_pull / _spot_refresh. See worker/CLAUDE.md
                    # "Provider concurrency model".
                    rescan_tick(repo, uw, _NoOhlc())

    def _spy_ohlc_refresh() -> None:
        if settings.massive_api_key is None:
            logger.warning("MASSIVE_API_KEY not set; skipping SPY refresh")
            return
        with _external_api_recorder(settings) as recorder:
            with _repo(settings) as repo:
                daily_spy_ohlc_refresh(
                    repo=repo,
                    api_key=settings.massive_api_key.get_secret_value(),
                    tz=settings.rth_tz,
                    telemetry_recorder=recorder,
                )

    def _vol_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_vol_analytics_rollup(repo=repo)

    def _flow_data_refresh() -> None:
        if not _uw_auto_request_allowed(datetime.now(ZoneInfo(settings.rth_tz))):
            logger.info("flow_data_refresh skipped outside UW flow refresh window")
            return
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="flow_data_refresh"
            ) as uw:
                with _repo(settings) as repo:
                    flow_data_refresh(
                        repo=repo,
                        client=uw,
                        settings=settings,
                        ticker_filter=ticker_filter,
                        lock_key=91501 + settings.worker_index,
                    )

    def _cockpit_daily_snapshot() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="cockpit_daily_snapshot",
            ) as uw:
                with _repo(settings) as repo:
                    cockpit_daily_snapshot(repo=repo, client=uw, settings=settings)

    def _trade_insights_ai_tick() -> None:
        trade_insights_ai_tick(settings)

    def _vol_index_lake_sync() -> None:
        # Parquet lake (~/market-warehouse/.../volatility) → vol_index_daily.
        # Local I/O + Postgres only — no external API spend, no UW/Massive role
        # binding required. Primary worker runs it to avoid duplicate upserts.
        with _repo(settings) as repo:
            run_vol_index_lake_sync(repo.conn, root=settings.lake_vol_index_root)

    def _regime_cri_scan() -> None:
        # Reads vol_index_daily + daily_ohlc; writes cri_snapshots. No external
        # API spend. Append-only — running twice in an hour is harmless.
        from uw_scan.scanners import cri as cri_scanner

        with _repo(settings) as repo:
            row_id = cri_scanner.run(repo.conn, schema=settings.db_schema)
            if row_id is None:
                logger.info("regime_cri_scan_skipped_thin_data")
            else:
                logger.info("regime_cri_scan_persisted row_id=%d", row_id)

    def _regime_gex_scan() -> None:
        # Weekday gate — UW data only meaningful during regular sessions.
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            logger.info("regime_gex_scan_skipped_weekend")
            return
        from uw_scan.scanners import gex as gex_scanner

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="regime_gex_scan"
            ) as uw:
                with _repo(settings) as repo:
                    for ticker in settings.gex_scan_tickers:
                        try:
                            gex_scanner.run(uw, repo, ticker=ticker)
                        except Exception as exc:
                            logger.warning(
                                "regime_gex_scan_failed ticker=%s err=%s",
                                ticker,
                                repr(exc),
                            )

    sched.add_job(
        lambda: _record_worker_heartbeat(settings),
        IntervalTrigger(seconds=1),
        id="worker_heartbeat",
        name="Worker heartbeat",
        max_instances=1,
        coalesce=True,
    )
    if "massive" in groups:
        sched.add_job(
            _spot_refresh,
            IntervalTrigger(seconds=settings.spot_refresh_seconds),
            id="spot_refresh",
            name="Spot refresh",
        )
        sched.add_job(
            _ohlc_pull,
            CronTrigger.from_crontab(settings.ohlc_pull_cron, timezone=settings.rth_tz),
            id="ohlc_pull",
            name="Daily OHLC pull",
        )
        if _is_primary_worker(settings):
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

    if "uw" in groups:
        sched.add_job(
            _full_scan,
            CronTrigger.from_crontab(settings.full_scan_cron, timezone=settings.rth_tz),
            id="full_scan",
            name="Full UW scan",
        )
        sched.add_job(
            _rescan,
            IntervalTrigger(seconds=1),
            id="rescan_tick",
            name="Ad-hoc rescan poll",
            max_instances=_rescan_worker_concurrency(settings),
        )
        sched.add_job(
            _flow_data_refresh,
            CronTrigger.from_crontab("15 18 * * 1-5", timezone=settings.rth_tz),
            id="nightly_flow_data_refresh",
            name="Nightly Flow tab data refresh",
        )
        if _is_primary_worker(settings):
            # Cockpit nightly snapshot — UW-bound (greeks/IV/RV/skew) and
            # single-flight via pg_try_advisory_lock; only the primary uw
            # worker schedules it to avoid duplicate UW spend.
            sched.add_job(
                _cockpit_daily_snapshot,
                CronTrigger.from_crontab(
                    settings.cockpit_snapshot_cron, timezone=settings.rth_tz
                ),
                id="cockpit_daily_snapshot",
                name="Cockpit 6-dim matrix daily snapshot",
            )
            # Regime / GEX scan — refreshes gex_snapshots every N minutes.
            # Primary-uw-only to avoid duplicate UW spend across shards.
            sched.add_job(
                _regime_gex_scan,
                IntervalTrigger(minutes=settings.gex_scan_interval_minutes),
                id="regime_gex_scan",
                name="Regime GEX scan (UW)",
                max_instances=1,
                coalesce=True,
            )

    if "ai" in groups and settings.trade_insights_ai_enabled:
        sched.add_job(
            _trade_insights_ai_tick,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick",
            name="Trade Insights AI analysis poll",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )

    if _is_primary_worker(settings):
        # Vol-complex parquet lake sync — nightly, 03:15 ET. Local I/O only,
        # no provider role required. Idempotent (UPSERT) so safe to re-run.
        sched.add_job(
            _vol_index_lake_sync,
            CronTrigger(hour=3, minute=15, timezone=settings.rth_tz),
            id="vol_index_lake_sync",
            name="Vol-complex parquet lake sync",
            max_instances=1,
            coalesce=True,
        )
        # CRI scan — refreshes cri_snapshots on the hour. Pure DB-read math,
        # no provider spend. Append-only; safe to re-run.
        sched.add_job(
            _regime_cri_scan,
            CronTrigger(minute=20, timezone=settings.rth_tz),
            id="regime_cri_scan",
            name="Regime CRI scan",
            max_instances=1,
            coalesce=True,
        )

    stopping = False

    def _stop(_sig, _frame):
        nonlocal stopping
        if stopping:
            sys.exit(0)
        stopping = True
        logger.info("received signal, shutting down scheduler")
        try:
            sched.shutdown(wait=False)
        except SchedulerNotRunningError as exc:
            logger.debug("scheduler already stopped during shutdown: %s", repr(exc))
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("scheduler started role=%s groups=%s", _worker_label(settings), groups)
    sched.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
