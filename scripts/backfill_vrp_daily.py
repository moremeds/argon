"""One-shot backfill: re-derive vrp_daily (+ stock_analytics_daily) for the
active watchlist by invoking the fixed nightly vol-analytics rollup once.

Recovers the 2026-05-22+ vrp_daily freeze: UW's realized_volatility column went
null, which made vrp = iv - rv NaN, so persist_vrp_daily wrote nothing for ~90%
of the watchlist. The rollup now derives trailing RV from daily_ohlc closes
(cards/vol_series.trailing_rv) — UW's own value is forward RV. This runner calls the rollup; it reads
realized_volatility_history + daily_ohlc from the DB and upserts vrp_daily.

2026-09-24: also the lookahead repair — deletes every vrp_daily row, then rebuilds
all history with trailing RV.

Pure DB->DB: ZERO UW/massive calls. Idempotent (delete + rebuild) — safe to re-run, and
the nightly 18:00 ET cron will keep it fresh going forward.

Reproduce (targets whatever .env.local points at — for the mini that is
100.66.147.98/option_wizard, the allowed prodlike combo):
  cd /Users/chenxi/projects/argon
  set -a; source .env.local; set +a
  uv run python scripts/backfill_vrp_daily.py
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.volatility_jobs import nightly_vol_analytics_rollup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        # Full rebuild, one transaction (the rollup commits once at the end): rows
        # the rollup cannot re-derive — the first 21 sessions of each series, and
        # tickers no longer on the watchlist — would otherwise keep the old
        # forward-RV values.
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {settings.db_schema}.vrp_daily")
        nightly_vol_analytics_rollup(repo=repo, days=3650)


if __name__ == "__main__":
    main()
