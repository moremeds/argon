"""One-shot backfill for option_intraday_buckets tickers missed by the #180
shard bug (primary-only job wrongly shard-filtered). UW-bound — gated behind
--confirm so it never runs by accident.

Two modes:

* Latest session (default): re-runs the daily job
  (refresh_intraday_for_top_oi_movers) for the chosen tickers — one session,
  the latest OI-mover run. Cheap.
* Historical sweep (--since YYYY-MM-DD): walks EVERY recorded mover session in
  [since, until] via backfill_intraday_history. Recovers the tape the shard bug
  never captured. Bounded by our own oi_change_events history (we can only fetch
  sessions whose movers we recorded) and UW's intraday retention.

option_intraday_buckets has no ticker/underlying column (only option_symbol),
so coverage can't be computed from it without OCC-root parsing — --missing does
exactly that parse to target the active tickers with no recent buckets (the
#180 gap). The job's advisory lock + upsert make every path safe to re-run.

Reproduce (full history for the #180-missed set):
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/backfill/intraday_buckets_backfill.py \
      --missing --since 2026-05-12 --confirm
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_intraday_jobs import (
    backfill_intraday_history,
    refresh_intraday_for_top_oi_movers,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intraday_backfill")


def _client(settings: Settings) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        job_name="intraday_buckets_backfill",
    )


def _compute_missing_tickers(repo: Repository) -> list[str]:
    """Active watchlist tickers with NO intraday buckets in the most recent
    ~week of capture — the set the #180 shard bug left blank. Self-calibrating
    on the latest bucket session so it doesn't hard-code a date."""
    s = repo._schema
    sql = (
        f"WITH active AS (SELECT ticker FROM {s}.watchlist WHERE removed_at IS NULL), "
        f"maxd AS (SELECT max(trade_date) AS d FROM {s}.option_intraday_buckets), "
        f"covered AS ("
        f"  SELECT DISTINCT regexp_replace(option_symbol, '[0-9].*$', '') AS root "
        f"  FROM {s}.option_intraday_buckets, maxd "
        f"  WHERE trade_date >= maxd.d - 7) "
        "SELECT a.ticker FROM active a LEFT JOIN covered c ON a.ticker = c.root "
        "WHERE c.root IS NULL ORDER BY a.ticker"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument("--tickers", default="", help="comma list of underlyings")
    ap.add_argument("--all", action="store_true", help="full active watchlist")
    ap.add_argument(
        "--missing", action="store_true", help="active tickers with no recent buckets"
    )
    ap.add_argument(
        "--since",
        default="",
        help="YYYY-MM-DD; enables historical sweep from this date",
    )
    ap.add_argument("--until", default="", help="YYYY-MM-DD; sweep end (default today)")
    args = ap.parse_args()

    settings = (
        Settings.from_env()
    )  # plain BaseModel: bare Settings() lacks required api_key
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    try:
        if args.all:
            target = sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})
        elif args.missing:
            target = _compute_missing_tickers(repo)
        else:
            target = sorted(
                {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
            )
        if not target:
            logger.error("no tickers: pass --tickers T1,T2 | --missing | --all")
            return 2

        if args.since:
            since = date.fromisoformat(args.since)
            until = date.fromisoformat(args.until) if args.until else date.today()
            if not args.confirm:
                logger.info(
                    "DRY RUN — historical sweep %s..%s for %d tickers: %s",
                    since,
                    until,
                    len(target),
                    target,
                )
                return 0
            summary = backfill_intraday_history(
                repo=repo,
                client=_client(settings),
                settings=settings,
                tickers=target,
                since=since,
                until=until,
            )
            logger.info("backfill complete: %s", summary)
            return 0

        if not args.confirm:
            logger.info(
                "DRY RUN — latest-session backfill for %d tickers: %s",
                len(target),
                target,
            )
            return 0
        target_set = set(target)
        summary = refresh_intraday_for_top_oi_movers(
            repo=repo,
            client=_client(settings),
            settings=settings,
            ticker_filter=lambda t: t.strip().upper() in target_set,
        )
        logger.info("backfill complete: %s", summary)
        return 0
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
