"""Macro / rates family: official policy evidence, FRED series, the market layer,
macro gold evidence, the domain-state compute, the rates FRED refresh and the
regime NFCI/ANFCI/USREC refresh.

Registered by ``scheduler.main()`` on every process; each block keeps its own
single-owner guard (rates: uw-0; everything else: the global daily owner).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from uw_scan.config import Settings
from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesPathProvider
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.jobs.macro_context_snapshot import macro_context_snapshot_job
from uw_scan.worker.jobs.macro_gold_ingest import macro_gold_ingest_job
from uw_scan.worker.jobs.macro_market_layer_ingest import macro_market_layer_ingest_job
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_market_implied_ingest_job,
    macro_sep_ingest_job,
    macro_sme_ingest_job,
)
from uw_scan.worker.jobs.macro_series_ingest import macro_fred_series_ingest_job
from uw_scan.worker.jobs.macro_state_jobs import (
    macro_gold_state_job,
    macro_inflation_state_job,
    macro_rates_state_job,
    macro_usd_state_job,
)
from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job
from uw_scan.worker.jobs.regime_jobs import regime_fred_ingest_job
from uw_scan.worker.schedule.roles import _owns_global_daily_jobs, _pinned

logger = logging.getLogger(__name__)


def _should_schedule_rates_fred_ingest(settings: Settings) -> bool:
    return _pinned(settings, "uw")


def _should_schedule_macro_policy_ingest(settings: Settings) -> bool:
    """One network/data worker owns free official macro evidence polling."""
    return _pinned(settings, "massive")


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


def register(sched: BaseScheduler, settings: Settings) -> None:
    def _rates_fred_ingest() -> None:
        _run_rates_fred_ingest(settings)

    def _regime_fred_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            regime_fred_ingest_job(
                dsn=settings.db_dsn(),
                schema=settings.db_schema,
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _macro_fomc_ingest() -> None:
        macro_fomc_statement_ingest_job(dsn=settings.db_dsn())

    def _macro_sep_ingest() -> None:
        macro_sep_ingest_job(dsn=settings.db_dsn())

    def _macro_sme_ingest() -> None:
        macro_sme_ingest_job(dsn=settings.db_dsn())

    def _macro_market_shadow_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            macro_market_implied_ingest_job(
                dsn=settings.db_dsn(),
                current_target_range=None,
                provider_factory=lambda: FedFundsFuturesPathProvider(
                    base_url=settings.rates_policy_path_url,
                    record_request=lambda _provider, event: recorder.record(event),
                ),
            )

    def _macro_series_ingest() -> None:
        key = settings.fred_api_key
        if key is None:
            logger.warning("macro series ingest skipped: FRED_API_KEY is not set")
            return
        with _external_api_recorder(settings) as recorder:
            macro_fred_series_ingest_job(
                dsn=settings.db_dsn(),
                api_key=key.get_secret_value(),
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _macro_market_layer_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            result = macro_market_layer_ingest_job(
                dsn=settings.db_dsn(),
                record_request=lambda _provider, event: recorder.record(event),
            )
        logger.info(
            "macro market layer ingest: %s feeds=%d/%d created=%d unchanged=%d%s",
            result.status,
            result.feeds_succeeded,
            result.feeds_attempted,
            result.observations_created,
            result.observations_unchanged,
            f" failed={','.join(result.failed_feeds)}" if result.failed_feeds else "",
        )

    def _macro_gold_ingest() -> None:
        if settings.massive_api_key is None:
            logger.info("macro gold ingest skipped: no massive api key configured")
            return
        with _external_api_recorder(settings) as recorder:
            result = macro_gold_ingest_job(
                dsn=settings.db_dsn(),
                massive_api_key=settings.massive_api_key.get_secret_value(),
                schema=settings.db_schema,
                telemetry_recorder=recorder,
            )
        logger.info(
            "macro gold ingest: %d/%d feeds, %d artifacts, %d created, %d unchanged%s",
            result.feeds_succeeded,
            result.feeds_attempted,
            result.artifacts_seen,
            result.observations_created,
            result.observations_unchanged,
            f", errors={result.errors}" if result.errors else "",
        )

    def _macro_state_compute() -> None:
        # One connection, all FOUR domains, IN ORDER -- and the order is a dependency,
        # not a nicety. USD reads the stored rates ANSWER, so rates must have been
        # computed for this instant first or USD runs with no upstream and the policy
        # contradiction cannot fire. Gold is the terminal node and reads all three, so it
        # runs last: put it earlier and it records zero dependency edges every night while
        # looking perfectly healthy.
        #
        # ONE as_of for all four, stamped once rather than per job. Letting each call
        # now() gives three instants seconds apart, and then "the inflation state and
        # the rates state" are answers to two slightly different questions -- which is
        # exactly the comparison this pass exists to make safe. It also makes USD's
        # upstream lookup exact: rates is stored at the same instant USD asks about,
        # and `available_at <= as_of` admits equality.
        instant = datetime.now(UTC)
        with _repo(settings) as repo:
            for job in (
                macro_inflation_state_job,
                macro_rates_state_job,
                macro_usd_state_job,
                macro_gold_state_job,
            ):
                result = job(repo, as_of=instant)
                logger.info(
                    "macro state %s: %s state=%s confidence=%s evidence=%d",
                    result.domain,
                    result.status,
                    result.state,
                    result.confidence,
                    result.evidence_count,
                )
            # Assemble LAST and under the SAME instant. Every domain above catches its
            # own exception so the loop reaches here after a partial failure -- which is
            # the case the snapshot exists to name. It reads the stored dependency edges
            # rather than anything this pass holds in memory, so tonight's assembly and a
            # replay of a past instant run the identical code.
            macro_context_snapshot_job(
                repo, as_of=instant, assembled_at=datetime.now(UTC)
            )

    # Rates FRED is pinned to uw-0 by its own gate, so it lives outside the
    # single-owner block below.
    if _should_schedule_rates_fred_ingest(settings):
        sched.add_job(
            _rates_fred_ingest,
            CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
            id="rates_fred_ingest",
            name="Rates: FRED curve and macro refresh",
            max_instances=1,
            coalesce=True,
        )
    if _owns_global_daily_jobs(settings):
        if _should_schedule_macro_policy_ingest(settings):
            if settings.macro_fomc_ingest_enabled:
                sched.add_job(
                    _macro_fomc_ingest,
                    CronTrigger.from_crontab("0 19 * * *", timezone=settings.rth_tz),
                    id="macro_fomc_ingest",
                    name="Macro: official FOMC statement evidence",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_sep_ingest_enabled:
                sched.add_job(
                    _macro_sep_ingest,
                    CronTrigger.from_crontab("5 19 * * *", timezone=settings.rth_tz),
                    id="macro_sep_ingest",
                    name="Macro: official SEP evidence",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_sme_ingest_enabled:
                sched.add_job(
                    _macro_sme_ingest,
                    CronTrigger.from_crontab("10 19 * * *", timezone=settings.rth_tz),
                    id="macro_sme_ingest",
                    name="Macro: NY Fed dealer expectations",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_market_shadow_ingest_enabled:
                sched.add_job(
                    _macro_market_shadow_ingest,
                    CronTrigger.from_crontab("15 19 * * *", timezone=settings.rth_tz),
                    id="macro_market_shadow_ingest",
                    name="Macro: delayed third-party market policy shadow",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_series_ingest_enabled:
                sched.add_job(
                    _macro_series_ingest,
                    CronTrigger.from_crontab("20 19 * * *", timezone=settings.rth_tz),
                    id="macro_series_ingest",
                    name="Macro: vintage-bearing FRED series evidence",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_market_layer_ingest_enabled:
                # Inside the macro block rather than clear of it, deliberately: the state
                # compute at 19:40 is the only consumer, and scheduling the layer after it
                # would make every supply announcement and positioning release a full day
                # stale to the state that reads it.  19:25 is the block's free slot.
                sched.add_job(
                    _macro_market_layer_ingest,
                    CronTrigger.from_crontab("25 19 * * *", timezone=settings.rth_tz),
                    id="macro_market_layer_ingest",
                    name="Macro: Treasury supply and CFTC positioning evidence",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_gold_ingest_enabled:
                # 19:30, the last free slot before the 19:40 compute. Ordering matters
                # the same way the market layer's does: gold's REQUIRED anchor is
                # GLD_CLOSE, so an ingest scheduled AFTER the compute would leave every
                # state standing on yesterday's last price -- or, on the first night,
                # abstaining.
                sched.add_job(
                    _macro_gold_ingest,
                    CronTrigger.from_crontab("30 19 * * *", timezone=settings.rth_tz),
                    id="macro_gold_ingest",
                    name="Macro: gold price and ETF tonnage evidence",
                    max_instances=1,
                    coalesce=True,
                )
            if settings.macro_state_compute_enabled:
                # After every ingest above, and after them by enough that a slow SEP
                # fetch cannot make tonight's state answer from yesterday's evidence.
                sched.add_job(
                    _macro_state_compute,
                    CronTrigger.from_crontab("40 19 * * *", timezone=settings.rth_tz),
                    id="macro_state_compute",
                    name="Macro: inflation, policy/rates, USD and gold domain states",
                    max_instances=1,
                    coalesce=True,
                )
        # NFCI / ANFCI / USREC for the regime label gates and trade insights. Same
        # single owner as the official macro evidence polling (massive-0 or 'all').
        # Unscheduled until 2026-10: the series sat frozen at 2026-05-26.
        if _should_schedule_macro_policy_ingest(settings):
            sched.add_job(
                _regime_fred_ingest,
                CronTrigger.from_crontab("22 19 * * *", timezone=settings.rth_tz),
                id="regime_fred_ingest",
                name="Regime: FRED NFCI/ANFCI/USREC refresh",
                max_instances=1,
                coalesce=True,
            )
