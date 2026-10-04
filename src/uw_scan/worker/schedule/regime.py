"""Regime family: the vol-complex and credit-ETF lake syncs, the CRI / VCG /
Canary EOD scans, the live CRI/VCG snapshot and its validation, and the UW-bound
GEX / market-tide / top-net-impact / GRG captures.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (uw-0 primary, the regime-live owner, the global daily owner).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import resolve_lake_root
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import research_budget_ok as _research_budget_ok
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.credit_etf_lake_sync import run_credit_etf_lake_sync
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _owns_global_daily_jobs,
    _pinned,
    _worker_groups,
)

logger = logging.getLogger(__name__)


# Each regime scan tick checks the last N CALENDAR days for missing snapshots
# and fills them (the scanners compute `latest - timedelta(days=N)` and then
# intersect with the trading days actually present — see scanners/cri.py:338,
# vcg.py:276, canary.py:322). At 30 calendar days that is ~21 trading days.
# The window must exceed realistic TIME-TO-DETECT, not typical outage length:
# the 2026-07-08 lake outage ran 13 days, so at the previous value of 7 the
# 07-08..07-13 span would never have healed even after the mount was repaired
# — leaving a permanent hole mid-series while the recent tail looked correct.
# Per-tick cost is a set-membership check per candidate date and a scanner run
# only for dates genuinely missing a snapshot (normally zero).
REGIME_RECOVERY_LOOKBACK_DAYS = 30


def _should_schedule_market_tide_capture(settings: Settings) -> bool:
    """Exactly one process owns the 5-min market-tide capture.

    UW-bound + appends a row per bar with no advisory lock; scheduling on every
    role's index-0 (_is_primary_worker matches uw-0/massive-0/ai-0) would
    multiply UW spend + race upserts. Pin to uw-0, gated by the capture flag —
    follows the option-surface / skew-swing precedent.
    """
    if not settings.market_tide_capture_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_top_net_impact_capture(settings: Settings) -> bool:
    """Exactly one process owns the 15-min top-net-impact capture. Same uw-0
    pin + kill-switch as market-tide (one UW call/tick, idempotent upsert)."""
    if not settings.top_net_impact_capture_enabled:
        return False
    return _pinned(settings, "uw")


def _gex_cron_trigger(settings: Settings) -> OrTrigger:
    """Intraday GEX cadence: tight during RTH (9-16 ET), slow off-hours; weekdays
    only. US options don't trade off-hours (GEX ~static) or on weekends, so the
    append-only intraday series is captured densely only where dealer positioning
    actually moves. Research budget pool."""
    rth = settings.gex_scan_rth_interval_minutes
    off = settings.gex_scan_offhours_interval_minutes
    return OrTrigger(
        [
            CronTrigger(
                minute=f"*/{rth}",
                hour="9-16",
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
            CronTrigger(
                minute=f"*/{off}",
                hour="0-8,17-23",
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
        ]
    )


def _market_tide_cron_trigger(settings: Settings) -> OrTrigger:
    """09:30-16:10 ET at 5-min cadence, matching UW's useful tide bars."""
    return OrTrigger(
        [
            CronTrigger(
                minute="30-55/5",
                hour=9,
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
            CronTrigger(
                minute="*/5",
                hour="10-15",
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
            CronTrigger(
                minute="0,5,10",
                hour=16,
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
        ]
    )


def _top_net_impact_cron_trigger(settings: Settings) -> OrTrigger:
    """09:30-16:15 ET at 15-min cadence, skipping pre-open noise."""
    return OrTrigger(
        [
            CronTrigger(
                minute="30,45",
                hour=9,
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
            CronTrigger(
                minute="*/15",
                hour="10-15",
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
            CronTrigger(
                minute="0,15",
                hour=16,
                day_of_week="mon-fri",
                timezone=settings.rth_tz,
            ),
        ]
    )


def _should_schedule_regime_live(settings: Settings) -> bool:
    """Exactly one process owns the 5-min live snapshot writes.

    _is_primary_worker is true for index-0 of EVERY role (uw-0, massive-0,
    ai-*-0 all match) — fine for the idempotent gap-recovery scans that
    share its block, but regime_live_scan appends a row per tick, so a
    multi-role stack would write N duplicates. Pin to massive-0 (market-
    data role) following the rates-FRED precedent.
    """
    return _pinned(settings, "massive")


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

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
                    if not _research_budget_ok(settings, repo):
                        logger.info(
                            "regime_gex_scan skipped: research UW budget exhausted"
                        )
                        return
                    # Unit = one ticker. gex_scanner.run commits each ticker's
                    # snapshot and scan_run on its own, so a bad ticker never
                    # costs the others; only a run where EVERY ticker failed
                    # raises, so the job listener records it.
                    succeeded = 0
                    last_exc: Exception | None = None
                    for ticker in settings.gex_scan_tickers:
                        try:
                            gex_scanner.run(uw, repo, ticker=ticker)
                            succeeded += 1
                        except Exception as exc:
                            logger.warning(
                                "regime_gex_scan_failed ticker=%s err=%s",
                                ticker,
                                repr(exc),
                            )
                            last_exc = exc
                    if succeeded == 0 and last_exc is not None:
                        raise RuntimeError(
                            f"regime_gex_scan: all {len(settings.gex_scan_tickers)}"
                            f" tickers failed; last err={last_exc!r}"
                        ) from last_exc

    def _regime_market_tide_scan() -> None:
        # Weekday gate — UW market-tide is only published during sessions.
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            logger.info("regime_market_tide_scan_skipped_weekend")
            return
        from uw_scan.scanners import market_tide as market_tide_scanner

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="regime_market_tide_scan",
            ) as uw:
                with _repo(settings) as repo:
                    # NOT budget-gated: one UW call per 5-min tick (~78/day) —
                    # spot comes from the WS DB table, not UW. Matches its
                    # identical-cost sibling _regime_top_net_impact_scan. Gating
                    # it behind the account-wide total_guard froze the whole
                    # Market Tide tab whenever the shared UW key crossed 105k
                    # mid-session; the ~78 calls it saves aren't worth that.
                    # One unit (one UW call): an exception is a failed run and
                    # re-raises so the job listener records it; 0 bars is a
                    # normal outcome (pre-open tick), not a failure.
                    try:
                        n = market_tide_scanner.run(
                            uw, repo, spot_ticker=settings.market_tide_spot_ticker
                        )
                        logger.info("regime_market_tide_scan_tick bars=%s", n)
                    except Exception as exc:
                        logger.warning(
                            "regime_market_tide_scan_failed err=%s", repr(exc)
                        )
                        repo.conn.rollback()
                        raise

    def _regime_top_net_impact_scan() -> None:
        # Weekday gate — UW top-net-impact is only published during sessions.
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            logger.info("regime_top_net_impact_scan_skipped_weekend")
            return
        from uw_scan.scanners import top_net_impact as top_net_impact_scanner

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="regime_top_net_impact_scan",
            ) as uw:
                with _repo(settings) as repo:
                    # One unit (one UW call): the scanner commits its scan_run as
                    # 'error' and re-raises; re-raise here too so the job
                    # listener records the failure. 0 rows is a normal outcome.
                    try:
                        n = top_net_impact_scanner.run(uw, repo)
                        logger.info("regime_top_net_impact_scan_tick rows=%s", n)
                    except Exception as exc:
                        logger.warning(
                            "regime_top_net_impact_scan_failed err=%s", repr(exc)
                        )
                        repo.conn.rollback()
                        raise

    def _market_tide_sentiment_eod() -> None:
        # EOD slope/sentiment for the latest session — pure DB→DB reshape of
        # the captured tide bars (no UW). Persists market_tide_sentiment_daily
        # for the backtest history.
        from uw_scan.worker.jobs.market_tide_sentiment import refresh_eod_sentiment

        # One unit (sessions=1): an exception is a failed run and re-raises so
        # the job listener records it; 0 sessions (no tide bars yet) is normal.
        with _repo(settings) as repo:
            try:
                n = refresh_eod_sentiment(repo, sessions=1)
                logger.info("market_tide_sentiment_eod_tick sessions=%s", n)
            except Exception as exc:
                logger.warning("market_tide_sentiment_eod_failed err=%s", repr(exc))
                repo.conn.rollback()
                raise

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
                    # One unit (one SPY/TLT snapshot): the scanner commits its
                    # scan_run as 'error' and re-raises; re-raise here too so the
                    # job listener records the failure.
                    try:
                        row_id = grg_scanner.run(uw, repo, schema=settings.db_schema)
                        logger.info("regime_grg_scan_tick row_id=%s", row_id)
                    except Exception as exc:
                        logger.warning("regime_grg_scan_failed err=%s", repr(exc))
                        repo.conn.rollback()
                        raise

    if "uw" in groups:
        if _is_primary_worker(settings):
            # Regime / GEX scan — append-only intraday GEX/DEX series over the
            # expanded ticker set. Split RTH-fast / off-hours-slow cadence
            # (weekdays only). Primary-uw-only; research budget pool.
            sched.add_job(
                _regime_gex_scan,
                _gex_cron_trigger(settings),
                id="regime_gex_scan",
                name="Regime GEX scan (UW)",
                max_instances=1,
                coalesce=True,
            )
            # Market-tide capture — market-wide net call/put premium, 5-min
            # bars through RTH. UW-bound + per-tick row writes; pinned to uw-0
            # via its own helper (NOT the looser _is_primary_worker gate) to
            # avoid duplicate UW spend, and behind the capture kill switch.
            if _should_schedule_market_tide_capture(settings):
                sched.add_job(
                    _regime_market_tide_scan,
                    _market_tide_cron_trigger(settings),
                    id="regime_market_tide_scan",
                    name="Regime market-tide capture (UW)",
                    max_instances=1,
                    coalesce=True,
                )
                # EOD tide sentiment — persist the day's slope/sentiment after
                # the close (last bar ~16:10 ET). DB→DB, no UW. Same uw-0 pin,
                # gated with the tide capture it depends on.
                sched.add_job(
                    _market_tide_sentiment_eod,
                    CronTrigger(
                        minute=25,
                        hour=16,
                        day_of_week="mon-fri",
                        timezone=settings.rth_tz,
                    ),
                    id="market_tide_sentiment_eod",
                    name="Market-tide EOD sentiment (DB)",
                    max_instances=1,
                    coalesce=True,
                )
            # Top-net-impact capture — market-wide net-premium ranking, 15-min
            # through RTH. One UW call/tick; pinned uw-0 + kill switch, slower
            # cadence than tide to respect UW budget (ranking barely moves in
            # 15 min). Tracks per-update rank movement via prev_rank.
            if _should_schedule_top_net_impact_capture(settings):
                sched.add_job(
                    _regime_top_net_impact_scan,
                    _top_net_impact_cron_trigger(settings),
                    id="regime_top_net_impact_scan",
                    name="Regime top-net-impact capture (UW)",
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
    if _owns_global_daily_jobs(settings):
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
