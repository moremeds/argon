"""APScheduler driver: registers the three cron jobs + the ad-hoc rescan poll."""

from __future__ import annotations

import logging
import signal
import sys
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import psycopg
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import resolve_lake_root
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once
from uw_scan.worker.jobs.credit_etf_lake_sync import run_credit_etf_lake_sync
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once
from uw_scan.worker.jobs.gold_jobs import (
    gold_cftc_cot_ingest_job,
    gold_comex_vault_ingest_job,
    gold_etf_holdings_ingest_job,
    gold_fred_ingest_job,
    gold_gpr_ingest_job,
    gold_lbma_vault_ingest_job,
    gold_posture_compute_job,
    gold_spot_ingest_job,
    gold_uw_options_ingest_job,
    gold_wgc_cb_ingest_job,
)
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.jobs.option_intraday_jobs import (
    refresh_intraday_for_top_oi_movers,
)
from uw_scan.worker.jobs.pipeline_benchmark import pipeline_benchmark_snapshot_job
from uw_scan.worker.jobs.positioning_jobs import positioning_refresh_once
from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job
from uw_scan.worker.jobs.rescan_loop import rescan_tick
from uw_scan.worker.jobs.skew_analytics import (
    nightly_skew_analytics_rollup,
    skew_markout_refresh,
)
from uw_scan.worker.jobs.skew_swing_greeks import skew_swing_greeks_refresh
from uw_scan.worker.jobs.trade_insight_outcome_backfill import (
    trade_insight_outcome_backfill_once,
)
from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
from uw_scan.worker.jobs.vrp_macro_signal import vrp_macro_signal_refresh
from uw_scan.worker.jobs.vrp_markout import vrp_markout_refresh
from uw_scan.worker.jobs.vrp_research_jobs import vrp_research_refresh
from uw_scan.worker.jobs.vrp_trading_jobs import (
    vrp_backtest_refresh,
    vrp_candidates_refresh,
    vrp_paper_mark,
    vrp_paper_open,
)
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
# Each regime scan tick checks the last N trading days for missing snapshots
# and fills them. 7 days is enough to ride out a long-weekend outage on the
# primary worker without growing the per-tick work unboundedly. Match this
# value if you change the cron interval — too-short means missed gaps
# linger; too-long is wasted set-membership checks per tick (cheap, but
# pointless).
REGIME_RECOVERY_LOOKBACK_DAYS = 7
WorkerGroup = Literal["uw", "massive", "ai", "ai-codex", "ai-claude", "ai-deepseek"]
WORKER_ROLES: set[str] = {
    "all",
    "uw",
    "massive",
    "ai",
    "ai-codex",
    "ai-claude",
    "ai-deepseek",
}


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
            "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive, ai, "
            "ai-codex, ai-claude, ai-deepseek "
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
    if role == "ai":
        return {"ai"}
    if role == "ai-codex":
        return {"ai-codex"}
    if role == "ai-claude":
        return {"ai-claude"}
    if role == "ai-deepseek":
        return {"ai-deepseek"}
    raise RuntimeError(
        "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive, ai, "
        "ai-codex, ai-claude "
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


def _should_schedule_rates_fred_ingest(settings: Settings) -> bool:
    role = settings.worker_role.lower()
    return role == "all" or (role == "uw" and settings.worker_index == 0)


def _should_schedule_pipeline_benchmark(settings: Settings) -> bool:
    role = settings.worker_role.lower()
    return role == "all" or (role == "uw" and settings.worker_index == 0)


def _should_schedule_skew_swing_greeks(settings: Settings) -> bool:
    """Exactly one process owns the swing-greeks refresh.

    It is a UW-bound watchlist loop with no advisory lock (unlike the cockpit
    snapshot, which single-flights via pg_try_advisory_lock). _is_primary_worker is
    true for index-0 of EVERY role (uw-0, massive-0, ai-*-0), so scheduling it there
    would run it N times -> duplicate UW /greeks spend (429 risk) + racing
    delete-then-insert on skew_swing_greeks. Pin to uw-0 (the UW role), following the
    rates-FRED / pipeline-benchmark precedent.
    """
    role = settings.worker_role.lower()
    return role == "all" or (role == "uw" and settings.worker_index == 0)


def _should_schedule_regime_live(settings: Settings) -> bool:
    """Exactly one process owns the 5-min live snapshot writes.

    _is_primary_worker is true for index-0 of EVERY role (uw-0, massive-0,
    ai-*-0 all match) — fine for the idempotent gap-recovery scans that
    share its block, but regime_live_scan appends a row per tick, so a
    multi-role stack would write N duplicates. Pin to massive-0 (market-
    data role) following the rates-FRED precedent.
    """
    role = settings.worker_role.lower()
    return role == "all" or (role == "massive" and settings.worker_index == 0)


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


def _run_rates_fred_ingest(settings: Settings) -> None:
    if settings.fred_api_key is None:
        logger.warning("FRED_API_KEY not set; skipping rates_fred_ingest")
        return
    with _external_api_recorder(settings) as recorder:
        rates_fred_ingest_job(
            dsn=settings.db_dsn(),
            schema=settings.db_schema,
            fred_api_key=settings.fred_api_key.get_secret_value(),
            policy_path_url=settings.rates_policy_path_url,
            record_request=lambda _provider, event: recorder.record(event),
        )


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


def _fundamentals_provider(settings: Settings):
    from uw_scan.sources.massive_fundamentals import MassiveFundamentalsProvider

    if settings.massive_api_key is None:
        return None
    return MassiveFundamentalsProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
        timeout=settings.request_timeout_seconds,
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


def main() -> int:
    settings = Settings.from_env()
    _validate_worker_settings(settings)
    groups = _worker_groups(settings)
    ticker_filter = _ticker_shard_filter(settings)
    sched = BlockingScheduler(timezone=settings.rth_tz)

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
                    n = full_scan_once(
                        repo,
                        uw,
                        _NoOhlc(),
                        ticker_filter=ticker_filter,
                        stale_after=timedelta(
                            hours=settings.full_scan_stale_after_hours
                        ),
                        preserve_spot=settings.ws_spot_enabled,
                    )
                    logger.info("full_scan completed %d tickers", n)

    def _positioning_refresh() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="positioning_refresh"
            ) as uw:
                with _repo(settings) as repo:
                    n = positioning_refresh_once(repo, uw, ticker_filter=ticker_filter)
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
                    n = ohlc_pull_once(repo, provider, ticker_filter=ticker_filter)
                    logger.info("ohlc_pull refreshed %d tickers", n)
            finally:
                provider.close()

    def _fundamentals_refresh() -> None:
        provider = _fundamentals_provider(settings)
        if provider is None:
            logger.warning("MASSIVE_API_KEY not set; skipping fundamentals refresh")
            return
        try:
            with _repo(settings) as repo:
                n = fundamentals_refresh_once(
                    repo, provider, ticker_filter=ticker_filter
                )
                logger.info("fundamentals_refresh refreshed %d tickers", n)
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
                        repo,
                        uw,
                        _NoOhlc(),
                        preserve_spot=settings.ws_spot_enabled,
                    )

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

    def _skew_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_skew_analytics_rollup(repo=repo)

    def _skew_markout_refresh() -> None:
        with _repo(settings) as repo:
            skew_markout_refresh(repo=repo)

    def _vrp_markout_refresh() -> None:
        with _repo(settings) as repo:
            vrp_markout_refresh(repo=repo)

    def _vrp_macro_signal_refresh() -> None:
        with _repo(settings) as repo:
            vrp_macro_signal_refresh(repo=repo, settings=settings)

    def _corporate_actions_refresh() -> None:
        provider = _fundamentals_provider(settings)
        if provider is None:
            logger.warning(
                "MASSIVE_API_KEY not set; skipping corporate-actions refresh"
            )
            return
        try:
            with _repo(settings) as repo:
                n = corporate_actions_refresh_once(repo, provider)
                logger.info("corporate_actions_refresh ingested %d tickers", n)
        finally:
            provider.close()

    def _vrp_research_refresh() -> None:
        with _repo(settings) as repo:
            vrp_research_refresh(repo=repo)

    def _vrp_candidates_refresh() -> None:
        with _repo(settings) as repo:
            vrp_candidates_refresh(repo=repo, settings=settings)

    def _vrp_paper_open() -> None:
        with _repo(settings) as repo:
            vrp_paper_open(repo=repo, settings=settings)

    def _vrp_paper_mark() -> None:
        with _repo(settings) as repo:
            vrp_paper_mark(repo=repo, settings=settings)

    def _vrp_backtest_refresh() -> None:
        with _repo(settings) as repo:
            vrp_backtest_refresh(repo=repo, settings=settings)

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
                    refresh_intraday_for_top_oi_movers(
                        repo=repo,
                        client=uw,
                        settings=settings,
                        ticker_filter=ticker_filter,
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

    def _skew_swing_greeks_refresh() -> None:
        # ET market date (not host-local) so a non-ET host doesn't stamp +1 day.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="skew_swing_greeks",
            ) as uw:
                with _repo(settings) as repo:
                    skew_swing_greeks_refresh(repo=repo, client=uw, today=market_date)

    def _trade_insights_ai_tick_any() -> None:
        trade_insights_ai_tick(settings, provider_filter=None)

    def _trade_insights_ai_tick_codex() -> None:
        trade_insights_ai_tick(settings, provider_filter="codex")

    def _trade_insights_ai_tick_claude() -> None:
        trade_insights_ai_tick(settings, provider_filter="claude")

    def _trade_insights_ai_tick_deepseek() -> None:
        trade_insights_ai_tick(settings, provider_filter="deepseek")

    def _trade_insight_outcome_backfill() -> None:
        """Nightly outcome scorer — runs at 17:00 ET (after the daily
        OHLC pull at 17:30 has at least one cron tick ahead of it the
        following business day, so forward closes have a chance to
        accumulate before each scan). Primary worker only — the upsert
        is idempotent but running on every worker wastes Postgres roundtrips.
        """
        with _repo(settings) as repo:
            counts = trade_insight_outcome_backfill_once(repo.conn)
            logger.info(
                "trade_insight_outcome_backfill bootstrapped=%d scored=%d",
                counts["bootstrapped"],
                counts["scored"],
            )

    def _vol_index_lake_sync() -> None:
        # Parquet lake → vol_index_daily. Source is R2 when all four R2_*
        # settings are present (per the 2026-05-25 standing rule), else the
        # local mirror under ~/market-warehouse/.../volatility. No external
        # API spend in either case (R2 = our own object storage, not UW/Massive).
        # Primary worker runs it to avoid duplicate upserts.
        root = resolve_lake_root(settings, asset_class="volatility")
        with _repo(settings) as repo:
            run_vol_index_lake_sync(repo.conn, root=root)

    def _credit_etf_lake_sync() -> None:
        # Equity asset_class lake → vol_index_daily for the VCG credit proxies
        # (HYG / JNK / LQD). Source is R2 when configured, else the local
        # mirror — same idempotency guarantees apply to both backends.
        # Primary worker only.
        root = resolve_lake_root(settings, asset_class="equity")
        with _repo(settings) as repo:
            run_credit_etf_lake_sync(
                repo.conn,
                root=root,
                symbols=settings.credit_etf_symbols,
            )

    def _regime_vcg_scan() -> None:
        # Reads vol_index_daily (VIX/VVIX + the credit proxies); writes
        # vcg_snapshots. No external API spend. Self-healing via
        # ``recover_recent_gaps`` — fills any missing day in the last
        # ``REGIME_RECOVERY_LOOKBACK_DAYS``, including today. Idempotent;
        # repeated ticks with no new lake data are a no-op.
        from uw_scan.scanners import vcg as vcg_scanner

        proxy = settings.credit_etf_symbols[0] if settings.credit_etf_symbols else "HYG"
        with _repo(settings) as repo:
            summary = vcg_scanner.recover_recent_gaps(
                repo.conn,
                schema=settings.db_schema,
                proxy=proxy,
                lookback_days=REGIME_RECOVERY_LOOKBACK_DAYS,
            )
        logger.info(
            "regime_vcg_scan_tick proxy=%s checked=%d filled=%d skipped=%d",
            proxy,
            summary["checked"],
            summary["filled"],
            summary["skipped"],
        )

    def _regime_cri_scan() -> None:
        # Reads vol_index_daily + daily_ohlc; writes cri_snapshots. No external
        # API spend. Self-healing — see _regime_vcg_scan comment.
        from uw_scan.scanners import cri as cri_scanner

        with _repo(settings) as repo:
            summary = cri_scanner.recover_recent_gaps(
                repo.conn,
                schema=settings.db_schema,
                lookback_days=REGIME_RECOVERY_LOOKBACK_DAYS,
            )
        logger.info(
            "regime_cri_scan_tick checked=%d filled=%d skipped=%d",
            summary["checked"],
            summary["filled"],
            summary["skipped"],
        )

    def _regime_live_scan() -> None:
        # Weekday gate — quotes only flow Mon-Fri (xenon streams 24h but the
        # market session is what makes a provisional close meaningful).
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            return
        from uw_scan.worker.jobs.regime_live import regime_live_scan_once

        with _repo(settings) as repo:
            summary = regime_live_scan_once(repo, settings)
        logger.info("regime_live_scan_tick %s", summary)

    def _regime_live_validation() -> None:
        from uw_scan.worker.jobs.regime_live import validate_live_close_vs_lake

        with _repo(settings) as repo:
            rows = validate_live_close_vs_lake(repo, settings)
        logger.info("regime_live_validation_done symbols=%d", len(rows))

    def _regime_canary_scan() -> None:
        # Reads vol_index_daily (VIX/VVIX/VIX3M/COR1M/SPX); writes
        # canary_snapshots. composite_version is part of the dedup key, so
        # bumping the calibration version automatically triggers fresh
        # snapshots on the next tick. Self-healing — see _regime_vcg_scan.
        from uw_scan.scanners import canary as canary_scanner

        with _repo(settings) as repo:
            summary = canary_scanner.recover_recent_gaps(
                repo.conn,
                schema=settings.db_schema,
                lookback_days=REGIME_RECOVERY_LOOKBACK_DAYS,
            )
        logger.info(
            "regime_canary_scan_tick checked=%d filled=%d skipped=%d",
            summary["checked"],
            summary["filled"],
            summary["skipped"],
        )

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

    def _regime_grg_scan() -> None:
        # Gamma Rotation Gap. UW-bound: fetches SPY/TLT greek-exposure history,
        # reads SPY/TLT flip+spot from gex_snapshots, persists grg_snapshots.
        # Mirrors _regime_gex_scan's external-API bracket.
        from uw_scan.scanners import grg as grg_scanner

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="regime_grg_scan"
            ) as uw:
                with _repo(settings) as repo:
                    try:
                        row_id = grg_scanner.run(uw, repo, schema=settings.db_schema)
                        logger.info("regime_grg_scan_tick row_id=%s", row_id)
                    except Exception as exc:
                        logger.warning("regime_grg_scan_failed err=%s", repr(exc))
                        repo.conn.rollback()

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
                        logger.exception("discovery_scan_failed err=%r", exc)
                        repo.conn.rollback()

    def _gold_fred_ingest() -> None:
        gold_fred_ingest_job(dsn=settings.db_dsn())

    def _gold_spot_ingest() -> None:
        if settings.massive_api_key is None:
            logger.warning("MASSIVE_API_KEY not set; skipping gold_spot_ingest")
            return
        gold_spot_ingest_job(
            dsn=settings.db_dsn(),
            api_key=settings.massive_api_key.get_secret_value(),
            base_url=settings.massive_base_url,
        )

    def _gold_gpr_ingest() -> None:
        gold_gpr_ingest_job(dsn=settings.db_dsn())

    def _gold_etf_holdings_ingest() -> None:
        gold_etf_holdings_ingest_job(
            dsn=settings.db_dsn(),
            uw_api_key=settings.api_key.get_secret_value(),
            wgc_goldhub_cookie=(
                settings.wgc_goldhub_cookie.get_secret_value()
                if settings.wgc_goldhub_cookie is not None
                else None
            ),
            wgc_workbook_path=settings.wgc_etf_flows_workbook_path or None,
        )

    def _gold_comex_vault_ingest() -> None:
        gold_comex_vault_ingest_job(dsn=settings.db_dsn())

    def _gold_uw_options_ingest() -> None:
        gold_uw_options_ingest_job(
            dsn=settings.db_dsn(),
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            request_timeout=settings.request_timeout_seconds,
        )

    def _gold_cftc_cot_ingest() -> None:
        gold_cftc_cot_ingest_job(dsn=settings.db_dsn())

    def _gold_lbma_vault_ingest() -> None:
        gold_lbma_vault_ingest_job(dsn=settings.db_dsn())

    def _gold_wgc_cb_ingest() -> None:
        gold_wgc_cb_ingest_job(
            dsn=settings.db_dsn(),
            wgc_goldhub_cookie=(
                settings.wgc_goldhub_cookie.get_secret_value()
                if settings.wgc_goldhub_cookie is not None
                else None
            ),
            wgc_workbook_path=settings.wgc_cb_reserves_workbook_path or None,
        )

    def _gold_posture_compute() -> None:
        gold_posture_compute_job(dsn=settings.db_dsn())

    def _rates_fred_ingest() -> None:
        _run_rates_fred_ingest(settings)

    def _pipeline_benchmark_snapshot() -> None:
        pipeline_benchmark_snapshot_job(settings)

    sched.add_job(
        lambda: _record_worker_heartbeat(settings),
        IntervalTrigger(seconds=1),
        id="worker_heartbeat",
        name="Worker heartbeat",
        max_instances=1,
        coalesce=True,
    )
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
        sched.add_job(
            _fundamentals_refresh,
            CronTrigger.from_crontab(
                settings.fundamentals_refresh_cron, timezone=settings.rth_tz
            ),
            id="fundamentals_refresh",
            name="Nightly massive fundamentals refresh",
            max_instances=1,
            coalesce=True,
        )
        if _is_primary_worker(settings):
            # Volatility tab v2 jobs — ET-anchored via from_crontab (review I9).
            sched.add_job(
                _spy_ohlc_refresh,
                CronTrigger.from_crontab("30 16 * * 0-4", timezone=settings.rth_tz),
                id="daily_spy_ohlc_refresh",
                name="Daily SPY OHLC refresh",
            )
            sched.add_job(
                _vol_analytics_rollup,
                CronTrigger.from_crontab("0 18 * * 0-4", timezone=settings.rth_tz),
                id="nightly_vol_analytics_rollup",
                name="Nightly vol analytics rollup",
            )
            # Skew rollup at 18:30 ET — after the 18:00 vol rollup so the
            # per-day skew snapshots build on fresh RV/IV. Idempotent upsert.
            sched.add_job(
                _skew_analytics_rollup,
                CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
                id="nightly_skew_analytics_rollup",
                name="Nightly skew analytics rollup",
                max_instances=1,
                coalesce=True,
            )
            # Skew markout at 18:45 ET — after the 18:30 rollup so it scores the day's
            # fresh snapshot. This is the job that was missing: it re-scores all skew
            # snapshots and (re)writes skew_directional_verdicts / RV-reversion verdicts.
            # Without it the verdict store stayed empty and every directional lean was
            # NEUTRAL. Pure compute over the warm store (no external calls); idempotent.
            sched.add_job(
                _skew_markout_refresh,
                CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
                id="skew_markout_refresh",
                name="Skew markout verdict refresh",
                max_instances=1,
                coalesce=True,
            )
            # VRP harvest markout at 18:50 ET — aligned with the skew markout
            # (18:45). Pure compute over vrp_daily; idempotent. Scores whether
            # selling rich vol earns a reliable premium per bucket (Spec B).
            sched.add_job(
                _vrp_markout_refresh,
                CronTrigger.from_crontab("50 18 * * 0-4", timezone=settings.rth_tz),
                id="vrp_markout_refresh",
                name="VRP harvest markout verdict refresh",
                max_instances=1,
                coalesce=True,
            )
            # Corporate-actions ingestion at 17:35 ET — after the 17:30 OHLC pull,
            # before the research compute. Ingests split/dividend history (massive)
            # over the vrp_daily ∪ watchlist universe for exact-RV adjustment.
            sched.add_job(
                _corporate_actions_refresh,
                CronTrigger.from_crontab("35 17 * * 0-4", timezone=settings.rth_tz),
                id="corporate_actions_refresh",
                name="Corporate-actions ingestion",
                max_instances=1,
                coalesce=True,
            )
            # VRP research expansion at 19:10 ET — AFTER the 19:00 fundamentals
            # refresh (the filing_date earnings leg) so the calendar is fresh.
            # Pure compute over the warm store; idempotent (full-rewrite per run).
            sched.add_job(
                _vrp_research_refresh,
                CronTrigger.from_crontab("10 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_research_refresh",
                name="VRP research expansion (validation/sector/horizon/directional/ΔVRP)",
                max_instances=1,
                coalesce=True,
            )
            # VRP tradable layer (plan 2026-06-22) — all AFTER vrp_research (19:10)
            # so the SELLABLE-sector gate is fresh. massive-0 / primary, weekdays ET.
            sched.add_job(
                _vrp_candidates_refresh,
                CronTrigger.from_crontab("25 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_candidates_refresh",
                name="VRP iron-condor candidate emit",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_paper_open,
                CronTrigger.from_crontab("30 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_open",
                name="VRP paper-ledger open",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_paper_mark,
                CronTrigger.from_crontab("40 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_mark",
                name="VRP paper-ledger mark/close",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_backtest_refresh,
                CronTrigger.from_crontab("0 20 * * 6", timezone=settings.rth_tz),
                id="vrp_backtest_refresh",
                name="VRP condor backtest (weekly)",
                max_instances=1,
                coalesce=True,
            )
            # M9 v5.3 outcome ledger — runs nightly at 17:00 ET, right after
            # the 17:30 OHLC pull would have updated daily_ohlc. Scores
            # outcomes from forward-looking closes; idempotent re-runs are
            # bounded by the partial pending-index in migration 054.
            sched.add_job(
                _trade_insight_outcome_backfill,
                CronTrigger.from_crontab("0 17 * * 0-4", timezone=settings.rth_tz),
                id="trade_insight_outcome_backfill",
                name="Trade insight outcome backfill",
                max_instances=1,
                coalesce=True,
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
            # Skew swing-DTE greeks at 17:30 ET — UW-bound watchlist loop, before the
            # 18:30 skew rollup so the strike-by-delta structure detail has a fresh swing
            # chain. Pinned to uw-0 (NOT _is_primary_worker, which is true for index-0 of
            # every role) because it has no advisory lock: scheduling it per role-0 would
            # run N copies -> duplicate UW spend + racing delete-then-insert.
            if _should_schedule_skew_swing_greeks(settings):
                sched.add_job(
                    _skew_swing_greeks_refresh,
                    CronTrigger.from_crontab("30 17 * * 0-4", timezone=settings.rth_tz),
                    id="skew_swing_greeks_refresh",
                    name="Skew swing-DTE greeks refresh",
                    max_instances=1,
                    coalesce=True,
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
            # Regime / GRG scan — SPY/TLT cross-asset gamma divergence.
            # UW-bound; every 15 min through RTH + post-close settlement
            # (UW greek-exposure updates after the close). Primary-uw-only.
            sched.add_job(
                _regime_grg_scan,
                CronTrigger(
                    minute="*/15",
                    hour="9-18",
                    day_of_week="mon-fri",
                    timezone=settings.rth_tz,
                ),
                id="regime_grg_scan",
                name="Regime GRG scan (UW)",
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

    if _should_schedule_pipeline_benchmark(settings):
        sched.add_job(
            _pipeline_benchmark_snapshot,
            IntervalTrigger(minutes=5),
            id="pipeline_benchmark_snapshot",
            name="Pipeline benchmark snapshot",
            max_instances=1,
            coalesce=True,
        )

    if _should_schedule_regime_live(settings):
        # Live regime snapshot — basis='live' CRI/VCG rows every N minutes.
        # Pure DB-read math off intraday_quote + vol_index_daily; no provider
        # spend. Append-only writes, so exactly ONE process may own this.
        sched.add_job(
            _regime_live_scan,
            IntervalTrigger(minutes=settings.regime_live_scan_interval_minutes),
            id="regime_live_scan",
            name="Regime live CRI/VCG snapshot",
            max_instances=1,
            coalesce=True,
        )
        # Live-vs-lake close validation — after both lake syncs (03:15/03:20).
        sched.add_job(
            _regime_live_validation,
            CronTrigger(hour=3, minute=40, timezone=settings.rth_tz),
            id="regime_live_validation",
            name="Regime live close vs lake validation",
            max_instances=1,
            coalesce=True,
        )

    # Legacy single-pool role (claims any provider's row).
    if "ai" in groups and (
        settings.trade_insights_ai_enabled
        or settings.trade_insights_ai_claude_enabled
        or settings.trade_insights_ai_deepseek_enabled
    ):
        sched.add_job(
            _trade_insights_ai_tick_any,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick",
            name="Trade Insights AI analysis poll (any provider)",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )
    # Provider-pinned codex pool.
    if "ai-codex" in groups and settings.trade_insights_ai_enabled:
        sched.add_job(
            _trade_insights_ai_tick_codex,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick_codex",
            name="Trade Insights AI analysis poll (codex)",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )
    # Provider-pinned claude pool.
    if "ai-claude" in groups and settings.trade_insights_ai_claude_enabled:
        sched.add_job(
            _trade_insights_ai_tick_claude,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick_claude",
            name="Trade Insights AI analysis poll (claude)",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )
    # Provider-pinned deepseek pool.
    if "ai-deepseek" in groups and settings.trade_insights_ai_deepseek_enabled:
        sched.add_job(
            _trade_insights_ai_tick_deepseek,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick_deepseek",
            name="Trade Insights AI analysis poll (deepseek)",
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
        # VRP macro short-vol signal at 03:45 ET — AFTER vol_index_lake_sync
        # (03:15) so it reads the freshest synced EOD vol. Computes the weekly
        # bull-put-spread readout + full-history backtest headline per name and
        # persists the daily snapshot. Pure DB-read math; idempotent.
        sched.add_job(
            _vrp_macro_signal_refresh,
            CronTrigger.from_crontab("45 3 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_signal_refresh",
            name="VRP macro short-vol signal refresh",
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
        # Credit ETF parquet lake sync — nightly, 03:20 ET. Mirrors the
        # vol-complex sync but pulls HYG/JNK/LQD from asset_class=equity.
        sched.add_job(
            _credit_etf_lake_sync,
            CronTrigger(hour=3, minute=20, timezone=settings.rth_tz),
            id="credit_etf_lake_sync",
            name="Credit-ETF parquet lake sync",
            max_instances=1,
            coalesce=True,
        )
        # VCG scan — refreshes vcg_snapshots on :25. Reads VIX/VVIX/<proxy>
        # from vol_index_daily. Append-only.
        sched.add_job(
            _regime_vcg_scan,
            CronTrigger(minute=25, timezone=settings.rth_tz),
            id="regime_vcg_scan",
            name="Regime VCG scan",
            max_instances=1,
            coalesce=True,
        )
        # 5% Canary scan — refreshes canary_snapshots on :30. Reads
        # VIX/VVIX/VIX3M/COR1M/SPX from vol_index_daily. Append-only,
        # idempotent (ON CONFLICT DO NOTHING in CanarySnapshotRepository).
        sched.add_job(
            _regime_canary_scan,
            CronTrigger(minute=30, timezone=settings.rth_tz),
            id="regime_canary_scan",
            name="Regime 5% Canary scan",
            max_instances=1,
            coalesce=True,
        )
        # Phase A1 (Gold) — ET-anchored ingestion cascade then posture compute.
        # All gold jobs run on the primary worker only: load is light, no
        # sharding needed, and the UW options ingest (sole UW-bound job in
        # this group) avoids duplicate UW spend.
        sched.add_job(
            _gold_fred_ingest,
            CronTrigger.from_crontab("0 17 * * 0-4", timezone=settings.rth_tz),
            id="gold_fred_ingest",
            name="Gold: FRED daily refresh",
        )
        sched.add_job(
            _gold_spot_ingest,
            CronTrigger.from_crontab("5 17 * * 0-4", timezone=settings.rth_tz),
            id="gold_spot_ingest",
            name="Gold: spot price (GLD daily bars via massive)",
        )
        sched.add_job(
            _gold_uw_options_ingest,
            CronTrigger.from_crontab("15 17 * * 0-4", timezone=settings.rth_tz),
            id="gold_uw_options_ingest",
            name="Gold: UW options snapshot (GLD/GDX/IAU)",
        )
        sched.add_job(
            _gold_comex_vault_ingest,
            CronTrigger.from_crontab("30 17 * * 0-4", timezone=settings.rth_tz),
            id="gold_comex_vault_ingest",
            name="Gold: COMEX vault daily",
        )
        sched.add_job(
            _gold_etf_holdings_ingest,
            CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
            id="gold_etf_holdings_ingest",
            name="Gold: ETF holdings daily (GLD/IAU/GLDM/PHYS)",
        )
        if _should_schedule_rates_fred_ingest(settings):
            sched.add_job(
                _rates_fred_ingest,
                CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
                id="rates_fred_ingest",
                name="Rates: FRED curve and macro refresh",
                max_instances=1,
                coalesce=True,
            )
        sched.add_job(
            _gold_gpr_ingest,
            CronTrigger.from_crontab("0 20 * * 0-4", timezone=settings.rth_tz),
            id="gold_gpr_ingest",
            name="Gold: GPR daily refresh",
        )
        sched.add_job(
            _gold_posture_compute,
            CronTrigger.from_crontab("0 21 * * 0-4", timezone=settings.rth_tz),
            id="gold_posture_compute",
            name="Gold: posture row compute (post-ingest)",
        )
        sched.add_job(
            _gold_cftc_cot_ingest,
            CronTrigger.from_crontab("0 17 * * 4", timezone=settings.rth_tz),
            id="gold_cftc_cot_ingest",
            name="Gold: CFTC COT weekly (Fridays)",
        )
        sched.add_job(
            _gold_lbma_vault_ingest,
            CronTrigger.from_crontab("0 17 8 * *", timezone=settings.rth_tz),
            id="gold_lbma_vault_ingest",
            name="Gold: LBMA vault monthly",
        )
        sched.add_job(
            _gold_wgc_cb_ingest,
            CronTrigger.from_crontab("0 17 10 * *", timezone=settings.rth_tz),
            id="gold_wgc_cb_ingest",
            name="Gold: WGC CB reserves monthly",
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
