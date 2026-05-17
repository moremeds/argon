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

    steps: list[tuple[str, Callable[[], None]]] = [
        ("FRED daily + monthly series", lambda: gold_fred_ingest_job(dsn=dsn)),
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
        ("GPR daily", lambda: gold_gpr_ingest_job(dsn=dsn)),
        (
            "ETF holdings (GLD/IAU/GLDM/PHYS — best-effort)",
            lambda: gold_etf_holdings_ingest_job(dsn=dsn),
        ),
        ("COMEX vault daily", lambda: gold_comex_vault_ingest_job(dsn=dsn)),
        ("CFTC COT weekly", lambda: gold_cftc_cot_ingest_job(dsn=dsn)),
        ("LBMA vault monthly", lambda: gold_lbma_vault_ingest_job(dsn=dsn)),
        ("WGC CB reserves monthly (deferred)", lambda: gold_wgc_cb_ingest_job(dsn=dsn)),
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
