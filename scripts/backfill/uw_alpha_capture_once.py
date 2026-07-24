"""Run one UW historical-alpha nightly capture immediately (not on the cron).

Runs the SAME production wrapper the 18:35-18:55 ET crons run — no side-channel
write path. UW-bound → gated behind --confirm. Idempotent (upsert / insert-ignore).

Reproduce (local, deterministic smoke against a populated past session):
  UW_SCAN_UW_ALPHA_CAPTURE_ENABLED=1 uv run python \
      scripts/backfill/uw_alpha_capture_once.py \
      --dataset uw_gex_levels_daily --tickers AAPL \
      --market-date 2026-07-22 --confirm

Omit --market-date to capture today (what the 18:35 ET nightly cron does —
valid only after close, once UW has populated today's snapshots).
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.uw_alpha_capture import (
    dark_lit_capture,
    gex_levels_capture,
    intraday_flow_capture,
    short_pressure_capture,
    volatility_signal_capture,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uw_alpha_capture_once")

_WRAPPERS = {
    "uw_gex_levels_daily": gex_levels_capture,
    "uw_volatility_signal_daily": volatility_signal_capture,
    "uw_short_pressure_daily": short_pressure_capture,
    "uw_intraday_option_flow_bars": intraday_flow_capture,
    "uw_dark_lit_flow_prints": dark_lit_capture,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=sorted(_WRAPPERS))
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument("--tickers", default="", help="optional comma list; default = all")
    ap.add_argument(
        "--market-date",
        default="",
        help="YYYY-MM-DD to capture as-of; default = today (ET). UW populates "
        "today's snapshots after close, so a live-day smoke should pass a "
        "recent past trading date.",
    )
    args = ap.parse_args()

    market_date = date.fromisoformat(args.market_date) if args.market_date else None

    settings = Settings.from_env()  # bare Settings() lacks required api_key
    if not args.confirm:
        logger.info("DRY RUN — pass --confirm to call UW. No requests made.")
        return 0

    keep = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
    ticker_filter = (lambda t: t.strip().upper() in keep) if keep else None
    wrapper = _WRAPPERS[args.dataset]

    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    try:
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            telemetry_recorder=recorder,
            job_name=f"uw_alpha_capture_once:{args.dataset}",
        )
        summary = wrapper(
            repo=repo,
            client=client,
            settings=settings,
            ticker_filter=ticker_filter,
            market_date=market_date,
        )
        logger.info("capture complete (%s): %s", args.dataset, summary)
        return 0
    finally:
        recorder.close()
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
