"""One-shot warmup: run all 9 gold ingest jobs + posture compute against the configured DB.

Usage:
    uv run python -m uw_scan.worker.gold_warmup

Idempotent: safe to re-run. Lets the GOLD COMPASS page render immediately
without waiting for the next ET cron firing. Doubles as the local demo
seeder. Per-step exceptions are logged but do not abort the warmup; only
a failed posture compute returns a non-zero exit code.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import date

from uw_scan.config import Settings
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("uw_scan.gold_warmup")


def main() -> int:
    settings = Settings.from_env()
    dsn = settings.db_dsn()

    logger.info("gold_warmup: starting (db=%s)", settings.db_name)

    # Warmup pulls 5y of FRED/GPR history so correlations (60/126/252/504D)
    # have enough overlap with GLD_CLOSE. WGC ETF workbooks preserve history
    # back to 2003, so warmup uses a deeper holdings window than daily refresh.
    LONG_LOOKBACK_DAYS = 1825
    ETF_HOLDINGS_FULL_HISTORY_DAYS = 365 * 30

    steps: list[tuple[str, Callable[[], None]]] = [
        (
            "FRED daily + monthly series (5y backfill)",
            lambda: gold_fred_ingest_job(
                dsn=dsn,
                lookback_days=LONG_LOOKBACK_DAYS,
                monthly_lookback_days=LONG_LOOKBACK_DAYS,
            ),
        ),
        (
            "Gold spot via massive (GLD daily bars)",
            lambda: (
                gold_spot_ingest_job(
                    dsn=dsn,
                    api_key=(
                        settings.massive_api_key.get_secret_value()
                        if settings.massive_api_key
                        else ""
                    ),
                    base_url=settings.massive_base_url,
                )
                if settings.massive_api_key
                else logger.warning(
                    "MASSIVE_API_KEY not set — skipping gold_spot_ingest"
                )
            ),
        ),
        (
            "GPR daily (5y backfill)",
            lambda: gold_gpr_ingest_job(dsn=dsn, lookback_days=LONG_LOOKBACK_DAYS),
        ),
        (
            "ETF holdings (GLD/IAU/GLDM/PHYS — best-effort)",
            lambda: gold_etf_holdings_ingest_job(
                dsn=dsn,
                uw_api_key=settings.api_key.get_secret_value(),
                wgc_goldhub_cookie=(
                    settings.wgc_goldhub_cookie.get_secret_value()
                    if settings.wgc_goldhub_cookie is not None
                    else None
                ),
                wgc_workbook_path=settings.wgc_etf_flows_workbook_path or None,
                lookback_days=45,
                holdings_lookback_days=ETF_HOLDINGS_FULL_HISTORY_DAYS,
            ),
        ),
        ("COMEX vault daily", lambda: gold_comex_vault_ingest_job(dsn=dsn)),
        ("CFTC COT weekly", lambda: gold_cftc_cot_ingest_job(dsn=dsn)),
        ("LBMA vault monthly", lambda: gold_lbma_vault_ingest_job(dsn=dsn)),
        (
            "WGC CB reserves monthly",
            lambda: gold_wgc_cb_ingest_job(
                dsn=dsn,
                wgc_goldhub_cookie=(
                    settings.wgc_goldhub_cookie.get_secret_value()
                    if settings.wgc_goldhub_cookie is not None
                    else None
                ),
                wgc_workbook_path=settings.wgc_cb_reserves_workbook_path or None,
                lookback_days=None,
            ),
        ),
        (
            "UW options snapshot (GLD/GDX/IAU)",
            lambda: gold_uw_options_ingest_job(
                dsn=dsn,
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                request_timeout=settings.request_timeout_seconds,
            ),
        ),
    ]

    for label, fn in steps:
        logger.info("→ %s", label)
        try:
            fn()
            logger.info("  ok")
        except Exception as exc:
            logger.exception("  failed: %r", exc)

    logger.info("→ Posture compute (as_of=%s)", date.today())
    try:
        gold_posture_compute_job(dsn=dsn)
        logger.info("  ok — refresh http://localhost:3001/gold")
        return 0
    except Exception as exc:
        logger.exception("  failed: %r", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
