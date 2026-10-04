"""Gold family: the daily ingest cascade, the posture compute, weekly/monthly feeds.

Registered by scheduler.main() on the single owner of the global daily jobs
(``_owns_global_daily_jobs``: massive-0, or ``all``).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.jobs.gold_jobs import (
    gold_cftc_cot_ingest_job,
    gold_etf_holdings_ingest_job,
    gold_fred_ingest_job,
    gold_gpr_ingest_job,
    gold_lbma_vault_ingest_job,
    gold_posture_compute_job,
    gold_spot_ingest_job,
    gold_uw_options_ingest_job,
    gold_wgc_cb_ingest_job,
)

logger = logging.getLogger(__name__)


def register(sched: BaseScheduler, settings: Settings) -> None:
    def _gold_fred_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_fred_ingest_job(
                dsn=settings.db_dsn(),
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_spot_ingest() -> None:
        if settings.massive_api_key is None:
            logger.warning("MASSIVE_API_KEY not set; skipping gold_spot_ingest")
            return
        with _external_api_recorder(settings) as recorder:
            gold_spot_ingest_job(
                dsn=settings.db_dsn(),
                api_key=settings.massive_api_key.get_secret_value(),
                base_url=settings.massive_base_url,
                telemetry_recorder=recorder,
            )

    def _gold_gpr_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_gpr_ingest_job(
                dsn=settings.db_dsn(),
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_etf_holdings_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_etf_holdings_ingest_job(
                dsn=settings.db_dsn(),
                uw_api_key=settings.api_key.get_secret_value(),
                wgc_goldhub_cookie=(
                    settings.wgc_goldhub_cookie.get_secret_value()
                    if settings.wgc_goldhub_cookie is not None
                    else None
                ),
                wgc_workbook_path=settings.wgc_etf_flows_workbook_path or None,
                rth_tz=settings.rth_tz,
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_uw_options_ingest() -> None:
        gold_uw_options_ingest_job(
            dsn=settings.db_dsn(),
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            request_timeout=settings.request_timeout_seconds,
        )

    def _gold_cftc_cot_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_cftc_cot_ingest_job(
                dsn=settings.db_dsn(),
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_lbma_vault_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_lbma_vault_ingest_job(
                dsn=settings.db_dsn(),
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_wgc_cb_ingest() -> None:
        with _external_api_recorder(settings) as recorder:
            gold_wgc_cb_ingest_job(
                dsn=settings.db_dsn(),
                wgc_goldhub_cookie=(
                    settings.wgc_goldhub_cookie.get_secret_value()
                    if settings.wgc_goldhub_cookie is not None
                    else None
                ),
                wgc_workbook_path=settings.wgc_cb_reserves_workbook_path or None,
                record_request=lambda _provider, event: recorder.record(event),
            )

    def _gold_posture_compute() -> None:
        gold_posture_compute_job(dsn=settings.db_dsn())

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
        _gold_etf_holdings_ingest,
        CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
        id="gold_etf_holdings_ingest",
        name="Gold: ETF holdings daily (GLD/IAU/GLDM/PHYS)",
    )
    # 18:35, moved up from 20:00. The posture below must land before the
    # 19:40 macro state compute, and GPRD is the only daily input that was
    # scheduled after 18:30. Nothing is lost by fetching earlier: the
    # publisher's file is a static academic .xls that already runs 2-3 days
    # behind the fetch (an ingest at 19:00 ET on 2026-08-19 returned an
    # observation dated 2026-08-17), so the fetch clock was never binding.
    sched.add_job(
        _gold_gpr_ingest,
        CronTrigger.from_crontab("35 18 * * 0-4", timezone=settings.rth_tz),
        id="gold_gpr_ingest",
        name="Gold: GPR daily refresh",
    )
    # 19:10, moved up from 21:00 -- the defect this fixes.
    #
    # The gold domain state reads `fetch_gold_posture_as_of(as_of.date())`, and
    # `gold_posture_compute` stamps its row with the latest GLD_CLOSE date, so an
    # evening run on day D writes obs_date D. At 21:00 that row did not exist when
    # the 19:40 state asked for it, so gold stood on the PREVIOUS day's gauge every
    # night -- not on a bad night, every night. `gauge_age_days` reported the lag
    # honestly while the schedule itself was creating it.
    #
    # 19:10 sits 40 minutes after the last upstream ingest (etf_holdings, 18:30) and
    # 30 minutes before the state that consumes it. Mon-Fri is kept deliberately:
    # there is no gold close to compute on a weekend, so the Saturday and Sunday
    # states legitimately read Friday's gauge and say so.
    sched.add_job(
        _gold_posture_compute,
        CronTrigger.from_crontab("10 19 * * 0-4", timezone=settings.rth_tz),
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
