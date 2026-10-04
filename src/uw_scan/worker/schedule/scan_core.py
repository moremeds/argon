"""Scan-core family: the per-ticker watchlist scan (sharded full_scan, the
hot-subset fast lane, the ad-hoc rescan poll), the daily OHLC pull, positioning
and Flow-tab refreshes, the intraday OI-mover refresh, and the market-wide
discovery scan.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (uw group, massive group, uw-0, its own flag).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.sources.uw_budget import limits_from_settings, may_spend, read_snapshot
from uw_scan.storage.advisory_locks import worker_key
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.full_scan_hot import full_scan_hot_once
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.jobs.option_intraday_jobs import refresh_intraday_for_top_oi_movers
from uw_scan.worker.jobs.positioning_jobs import positioning_refresh_once
from uw_scan.worker.jobs.rescan_loop import rescan_tick
from uw_scan.worker.schedule.roles import _is_primary_worker, _worker_groups

logger = logging.getLogger(__name__)


RESCAN_WORKER_CONCURRENCY = 2

# Measured full_scan fan-out: ~17 UW endpoints per ticker per refresh. Used to
# translate remaining live budget into a per-pass ticker cap.
FULL_SCAN_CALLS_PER_TICKER = 17


def _live_max_tickers(
    settings: Settings, repo, *, shard_divisor: int = 1
) -> int | None:
    """Per-pass ticker cap from the UW budget governor's remaining live budget.

    Returns None when the governor is disabled (no cap). Returns 0 when the live
    pool or the account-wide guard is exhausted (scan nothing). ``shard_divisor``
    splits the remaining budget across sharded uw workers so N workers don't each
    spend the full remainder (the account guard is the hard backstop regardless).
    """
    if not settings.uw_budget_governor_enabled:
        return None
    snap = read_snapshot(repo.conn, settings.db_schema)
    limits = limits_from_settings(settings)
    if not may_spend("live", snap, limits):
        return 0
    remaining = limits.live_ceiling - snap.live_spent
    if snap.account_count is not None:
        remaining = min(remaining, limits.total_guard - snap.account_count)
    remaining = max(0, remaining)
    divisor = max(1, shard_divisor)
    return remaining // FULL_SCAN_CALLS_PER_TICKER // divisor


def _uw_auto_request_allowed(now: datetime) -> bool:
    """Return True during the weekday ET window where scheduled flow refresh may run."""
    local = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    if local.weekday() >= 5:
        return False
    current = local.time()
    return time(5, 0) <= current < time(20, 0)


def _rescan_worker_concurrency(settings: Settings) -> int:
    if settings.worker_role.lower() == "uw" and settings.worker_count > 1:
        return 1
    return RESCAN_WORKER_CONCURRENCY


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
    """Null-object OhlcProvider for runs without a Massive key.

    Only fetch_daily remains after Phase 7 deleted REST spot polling — the
    WS consumer (uw_scan.worker.massive_ws_consumer) is the sole intraday
    spot writer.
    """

    def fetch_daily(self, *_a, **_k):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def close(self):
        pass


def register(
    sched: BaseScheduler,
    settings: Settings,
    *,
    ticker_filter: Callable[[str], bool],
) -> None:
    groups = _worker_groups(settings)

    def _full_scan() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="full_scan"
            ) as uw:
                with _repo(settings) as repo:
                    # _NoOhlc() is intentional: daily OHLC fetches are owned
                    # by _ohlc_pull and intraday spot by the WS consumer
                    # (uw_scan.worker.massive_ws_consumer). See worker/CLAUDE.md
                    # "Provider concurrency model".
                    # preserve_spot: when the WS consumer is the authoritative
                    # spot writer (any WS feed — MASSIVE_WS_ENABLED or
                    # XENON_WS_ENABLED) we tell the storage layer to gate the
                    # spot triple + return triple in the ON CONFLICT branch so
                    # full_scan can't clobber WS values.
                    # Budget governor: cap this pass at the remaining live
                    # budget (divided across sharded uw workers), hot-first.
                    max_tickers = _live_max_tickers(
                        settings, repo, shard_divisor=settings.worker_count
                    )
                    if max_tickers == 0:
                        logger.info("full_scan skipped: live UW budget exhausted")
                        return
                    n = full_scan_once(
                        repo=repo,
                        client=uw,
                        ohlc_provider=_NoOhlc(),
                        ticker_filter=ticker_filter,
                        stale_after=timedelta(
                            hours=settings.full_scan_stale_after_hours
                        ),
                        preserve_spot=settings.ws_spot_enabled,
                        max_tickers=max_tickers,
                    )
                    logger.info("full_scan completed %d tickers", n)

    def _full_scan_hot() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="full_scan_hot"
            ) as uw:
                with _repo(settings) as repo:
                    # Primary-uw-only singleton (no shard divisor). Hot tickers
                    # arrive hot-first; cap at the configured hot-slot count
                    # (the UI meter's "N / max") AND the governor's remaining
                    # live budget, whichever is tighter. If a user flags more
                    # than full_scan_hot_max_tickers, only the top slots (by
                    # sort_rank) get the fast lane.
                    budget_cap = _live_max_tickers(settings, repo)
                    hot_max = settings.full_scan_hot_max_tickers
                    max_tickers = (
                        hot_max if budget_cap is None else min(budget_cap, hot_max)
                    )
                    full_scan_hot_once(
                        repo=repo,
                        client=uw,
                        ohlc_provider=_NoOhlc(),
                        stale_minutes=settings.full_scan_hot_stale_minutes,
                        preserve_spot=settings.ws_spot_enabled,
                        max_tickers=max_tickers,
                    )

    def _positioning_refresh() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="positioning_refresh"
            ) as uw:
                with _repo(settings) as repo:
                    n = positioning_refresh_once(
                        repo=repo, client=uw, ticker_filter=ticker_filter
                    )
                    logger.info("positioning_refresh refreshed %d tickers", n)

    def _ohlc_pull() -> None:
        with _external_api_recorder(settings) as recorder:
            provider = _ohlc_provider(
                settings, telemetry_recorder=recorder, job_name="ohlc_pull"
            )
            if provider is None:
                return
            try:
                with _repo(settings) as repo:
                    n = ohlc_pull_once(
                        repo=repo, provider=provider, ticker_filter=ticker_filter
                    )
                    logger.info("ohlc_pull refreshed %d tickers", n)
            finally:
                provider.close()

    def _rescan() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="rescan_tick"
            ) as uw:
                with _repo(settings) as repo:
                    # _NoOhlc() is intentional: daily OHLC fetches are owned
                    # by _ohlc_pull and intraday spot by the WS consumer
                    # (uw_scan.worker.massive_ws_consumer). See worker/CLAUDE.md
                    # "Provider concurrency model".
                    rescan_tick(
                        repo=repo,
                        client=uw,
                        ohlc_provider=_NoOhlc(),
                        preserve_spot=settings.ws_spot_enabled,
                    )

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
                        lock_key=worker_key("flow_data_refresh", settings.worker_index),
                    )

    def _intraday_oi_refresh() -> None:
        # UW publishes the OI delta premarket (~6:45 ET). At 9 ET we fetch
        # the previous session's per-minute bars for each ticker's top
        # OI movers so the API can derive the TAPE column (peak window /
        # sparkline / first-last trade) without hitting UW at request time.
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="intraday_oi_refresh",
            ) as uw:
                with _repo(settings) as repo:
                    # This job is registered ONLY on the primary worker (see the
                    # _is_primary_worker guard at its add_job). A primary-only
                    # singleton must NOT shard-filter: ticker_filter would drop
                    # every ticker outside shard 0, so half the watchlist
                    # (TSLA/NVDA/MSFT/GOOGL/META/AVGO ...) would be fetched by
                    # nobody. Single-flight is already enforced by the advisory
                    # lock inside the job — issue #180.
                    refresh_intraday_for_top_oi_movers(
                        repo=repo,
                        client=uw,
                        settings=settings,
                        ticker_filter=None,
                    )

    def _discovery_scan() -> None:
        # Market-wide discovery — UW-bound (flow alerts + per-ticker dark pool),
        # single-flight via advisory lock, primary-uw-only to avoid duplicate UW
        # spend across shards. Mirrors _regime_grg_scan's external-API bracket.
        from uw_scan.worker.jobs.discovery_scan import discovery_scan_once

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="discovery_scan"
            ) as uw:
                with _repo(settings) as repo:
                    try:
                        summary = discovery_scan_once(
                            repo=repo, client=uw, settings=settings
                        )
                        logger.info("discovery_scan_tick %s", summary)
                    except Exception as exc:  # noqa: BLE001
                        # discovery_scan_once already committed its scan_run as
                        # 'fail'; re-raise so the job listener records it.
                        logger.warning("discovery_scan_failed err=%s", repr(exc))
                        repo.conn.rollback()
                        raise

    if "massive" in groups:
        # spot_refresh deleted in Phase 7 — WS consumer
        # (uw_scan.worker.massive_ws_consumer) is the sole intraday spot
        # writer now. Massive workers retain ownership of the daily OHLC pull.
        sched.add_job(
            _ohlc_pull,
            CronTrigger.from_crontab(settings.ohlc_pull_cron, timezone=settings.rth_tz),
            id="ohlc_pull",
            name="Daily OHLC pull",
        )
    if "uw" in groups:
        for idx, cron_expr in enumerate(settings.full_scan_crons):
            sched.add_job(
                _full_scan,
                CronTrigger.from_crontab(cron_expr, timezone=settings.rth_tz),
                id=f"full_scan_{idx}",
                name=f"Full UW scan ({cron_expr})",
                max_instances=1,
                coalesce=True,
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
            CronTrigger.from_crontab("15 18 * * 0-4", timezone=settings.rth_tz),
            id="nightly_flow_data_refresh",
            name="Nightly Flow tab data refresh",
        )
        sched.add_job(
            _positioning_refresh,
            CronTrigger.from_crontab(
                settings.positioning_refresh_cron, timezone=settings.rth_tz
            ),
            id="positioning_refresh",
            name="Daily UW positioning refresh",
            max_instances=1,
            coalesce=True,
        )
    if "uw" in groups:
        if _is_primary_worker(settings):
            # Intraday OI refresh — UW-bound, single-flight advisory lock,
            # primary-uw-only to avoid duplicate UW spend across shards. Runs
            # at 9 ET so UW's premarket OI publish has settled.
            sched.add_job(
                _intraday_oi_refresh,
                CronTrigger.from_crontab("0 9 * * 0-4", timezone=settings.rth_tz),
                id="intraday_oi_refresh",
                name="Intraday OI mover refresh",
                max_instances=1,
                coalesce=True,
            )
            # Hot-subset full_scan — tight-freshness intraday refresh of the
            # UI-flagged `hot` tickers. Primary-uw-only (no shard) so ≤25 hot
            # names aren't scanned N times; live budget pool, governor-capped.
            if settings.full_scan_hot_enabled:
                sched.add_job(
                    _full_scan_hot,
                    CronTrigger.from_crontab(
                        settings.full_scan_hot_cron, timezone=settings.rth_tz
                    ),
                    id="full_scan_hot",
                    name="Hot-subset full_scan (fast lane)",
                    max_instances=1,
                    coalesce=True,
                )
            # Market-wide discovery scan — edge-quality candidates + DP
            # enrichment. Primary-uw-only; gated by the discovery kill switch.
            if settings.scanner_discover_scan_enabled:
                sched.add_job(
                    _discovery_scan,
                    CronTrigger.from_crontab(
                        settings.scanner_discover_scan_cron, timezone=settings.rth_tz
                    ),
                    id="discovery_scan",
                    name="Market-wide discovery scan (UW)",
                    max_instances=1,
                    coalesce=True,
                )
