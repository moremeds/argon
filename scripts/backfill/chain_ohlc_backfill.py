"""Backfill daily OHLC for every `watchlist_chain` ticker, deep enough to test returns.

    uv run python scripts/backfill/chain_ohlc_backfill.py [--start=2018-01-01] [--dry-run]

Argon's warm store holds ~15 months of prices for ~112 names, which is the
active watchlist's operational window and is far too shallow for any
cross-sectional study: the capex demand ledger's returns leg needs the whole
industry chain, not the tickers that happen to be on the watchlist today.

Cost is the reason this is worth doing rather than deferring. `fetch_daily` maps
to a Polygon-shaped `/v2/aggs/ticker/{t}/range/1/day/{from}/{to}`, so ONE call
returns a ticker's entire history -- ~283 calls total, against **massive, not
UW**, so it spends nothing from the UW daily budget the rest of the stack
competes for.

Deliberately not a scheduler job. It is a one-off widening of history; the
nightly `ohlc_pull` keeps the active watchlist current from here.

Notes that matter when reading the result:

* Writes land in `uw_scan.daily_ohlc` with `source='massive.com'`, the same
  source tag the nightly job writes, because they are the same provider and
  endpoint. Re-running is a no-op -- `upsert_daily_ohlc` is keyed (ticker, date).
* Tickers outside the active watchlist are written too. They are invisible to
  the freshness monitor, which scopes coverage to the ACTIVE list, so this adds
  no false staleness alarms.
* Prices are **as massive returns them**. Whether they are split/dividend
  adjusted is the provider's business and is not verified here; the returns
  study has to sanity-check its own inputs for corporate-action seams rather
  than assume this backfill fixed them.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402

from uw_scan.config import Settings  # noqa: E402
from uw_scan.sources.ohlc import MassiveOhlcProvider  # noqa: E402
from uw_scan.storage.repository import Repository  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("chain_ohlc_backfill")


def chain_tickers(conn, schema: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT ticker FROM {schema}.watchlist_chain ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def main() -> int:
    argv = sys.argv[1:]
    start = next(
        (
            datetime.strptime(a.split("=", 1)[1], "%Y-%m-%d").date()
            for a in argv
            if a.startswith("--start=")
        ),
        date(2018, 1, 1),
    )
    dry = "--dry-run" in argv
    end = date.today()

    settings = Settings.from_env()
    if settings.massive_api_key is None:
        logger.error("MASSIVE_API_KEY not set — nothing to do")
        return 1

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        tickers = chain_tickers(conn, settings.db_schema)
        logger.info(
            "%d chain tickers, %s..%s%s",
            len(tickers),
            start,
            end,
            " (DRY RUN)" if dry else "",
        )
        if dry:
            return 0

        provider = MassiveOhlcProvider(
            api_key=settings.massive_api_key.get_secret_value(),
            base_url=settings.massive_base_url,
            timeout=60.0,
        )
        ok = empty = failed = 0
        total_bars = 0
        try:
            for i, ticker in enumerate(tickers, 1):
                try:
                    bars = provider.fetch_daily(ticker, start, end)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.warning(
                        "[%3d/%d] %-6s FAILED %s", i, len(tickers), ticker, repr(exc)
                    )
                    continue
                if not bars:
                    empty += 1
                    logger.info("[%3d/%d] %-6s no bars", i, len(tickers), ticker)
                    continue
                for bar in bars:
                    repo.upsert_daily_ohlc(
                        ticker=bar.ticker,
                        date=bar.date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        source="massive.com",
                    )
                ok += 1
                total_bars += len(bars)
                logger.info(
                    "[%3d/%d] %-6s %5d bars  %s..%s",
                    i,
                    len(tickers),
                    ticker,
                    len(bars),
                    bars[0].date,
                    bars[-1].date,
                )
        finally:
            provider.close()

        logger.info(
            "done: %d ok / %d empty / %d failed — %d bars",
            ok,
            empty,
            failed,
            total_bars,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
