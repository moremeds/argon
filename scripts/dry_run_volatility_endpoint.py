"""End-to-end dry-run for the Volatility Tab v2 endpoint.

Seeds a single test ticker with synthetic IV/RV history, SPY OHLC, an
iv_smile snapshot, and greeks → runs assemble_volatility_series directly
(no FastAPI, no UW) → asserts critical invariants about the response shape.

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test \
      uv run python scripts/dry_run_volatility_endpoint.py`

The script REFUSES to run unless UW_SCAN_TEST_DB_NAME is set.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from uw_scan.config import Settings
from uw_scan.models import GreeksRow, RealizedVolRow, VolStatsRow
from uw_scan.reports.volatility_series import assemble_volatility_series
from uw_scan.sources.ohlc import OhlcBar
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("dry_run_vol")

TICKER = "DRYRUN"


def _seed(repo: Repository) -> int:
    base = date.today() - timedelta(days=120)
    run_id = repo.insert_scan_run(TICKER, notes="dry_run")

    rv_rows: list[RealizedVolRow] = []
    spy_bars: list[OhlcBar] = []
    for i in range(120):
        d = base + timedelta(days=i)
        iv = 0.50 + 0.05 * math.sin(i / 5)
        rv_val = 0.40 + 0.04 * math.cos(i / 6)
        rv_rows.append(
            RealizedVolRow(
                date=d,
                price=Decimal(str(100 + i * 0.3 + math.sin(i / 4) * 2)),
                implied_volatility=Decimal(str(round(iv, 4))),
                realized_volatility=Decimal(str(round(rv_val, 4))),
            )
        )
        spy_bars.append(
            OhlcBar(
                ticker="SPY",
                date=d,
                open=None,
                high=None,
                low=None,
                close=Decimal(str(500 + i * 1.5 + math.cos(i / 4) * 5)),
                volume=None,
            )
        )
    repo.upsert_realized_vol_rows(TICKER, rv_rows)
    repo.upsert_index_ohlc_rows(spy_bars)

    # Seed today's volatility_stats row so the header builder finds an IV/rank.
    today_iv = rv_rows[-1].implied_volatility
    today_rv = rv_rows[-1].realized_volatility
    repo.upsert_volatility_stats_rows(
        [
            VolStatsRow(
                ticker=TICKER,
                date=date.today(),
                iv=today_iv,
                iv_low=Decimal("0.40"),
                iv_high=Decimal("0.60"),
                iv_rank=Decimal("50"),
                rv=today_rv,
                rv_low=Decimal("0.30"),
                rv_high=Decimal("0.50"),
            )
        ]
    )

    expiry = date.today() + timedelta(days=7)
    last_price = float(rv_rows[-1].price)
    smile_strikes = [
        last_price - 4,
        last_price - 2,
        last_price,
        last_price + 2,
        last_price + 4,
    ]
    repo.upsert_iv_smile_rows(
        [
            {
                "ticker": TICKER,
                "market_date": date.today(),
                "expiry": expiry,
                "strike": Decimal(str(round(s, 2))),
                "iv": Decimal(str(round(0.55 + 0.01 * abs(s - last_price), 4))),
            }
            for s in smile_strikes
        ]
    )

    repo.insert_greeks_rows(
        run_id,
        TICKER,
        [
            GreeksRow(
                date=date.today(),
                expiry=expiry,
                strike=Decimal(str(round(s, 2))),
                call_volatility=Decimal("0.55"),
                put_volatility=Decimal("0.57"),
            )
            for s in smile_strikes
        ],
    )
    repo.conn.commit()
    return run_id


def _assert(condition: bool, message: str) -> None:
    if not condition:
        log.error("FAIL: %s", message)
        sys.exit(1)
    log.info("OK   %s", message)


def main() -> int:
    if not os.environ.get("UW_SCAN_TEST_DB_NAME"):
        log.error(
            "UW_SCAN_TEST_DB_NAME must be set — refusing to write into the working DB."
        )
        return 2
    settings = Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )
    with closing(psycopg.connect(settings.db_dsn())) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        _seed(repo)
        resp = assemble_volatility_series(ticker=TICKER, repo=repo)

    log.info("=== response shape ===")
    log.info(
        "ticker=%s as_of=%s backfill_status=%s",
        resp.ticker,
        resp.as_of,
        resp.backfill_status,
    )
    log.info(
        "header: iv=%s rv=%s vrp=%s signal=%s",
        resp.header.iv,
        resp.header.rv,
        resp.header.vrp,
        resp.header.vrp_signal,
    )
    log.info("hv_iv_history rows=%d", len(resp.hv_iv_history))
    log.info(
        "term_structure expiries=%d (first ladder=%s)",
        len(resp.term_structure),
        resp.term_structure[0].by_strike if resp.term_structure else {},
    )
    log.info("smile expiries=%d", len(resp.smile))
    log.info(
        "iv_of_iv rows=%d  rv_spy_corr rows=%d",
        len(resp.iv_of_iv),
        len(resp.rv_spy_corr),
    )
    log.info(
        "regime_quadrant points=%d latest=%s",
        len(resp.regime_quadrant.points),
        resp.regime_quadrant.latest.state if resp.regime_quadrant.latest else "(none)",
    )
    log.info(
        "divergence rows=%d headline=%s",
        len(resp.divergence),
        resp.divergence_headline,
    )
    log.info(
        "vrp_spread rows=%d headline=%s",
        len(resp.vrp_spread),
        resp.vrp_spread_headline,
    )

    _assert(resp.header.iv is not None, "header.iv populated")
    _assert(resp.header.vrp is not None, "header.vrp populated")
    _assert(len(resp.hv_iv_history) >= 90, "hv_iv_history ≥ 90 rows")
    _assert(len(resp.term_structure) >= 1, "term_structure has ≥ 1 expiry")
    _assert(
        "ATM" in resp.term_structure[0].by_strike,
        "term_structure[0] has an ATM strike",
    )
    _assert(len(resp.smile) >= 1, "smile has ≥ 1 expiry curve")
    _assert(len(resp.iv_of_iv) > 0, "iv_of_iv populated")
    _assert(len(resp.rv_spy_corr) > 0, "rv_spy_corr populated")
    _assert(
        resp.regime_quadrant.latest is not None,
        "regime_quadrant.latest populated",
    )
    _assert(len(resp.divergence) > 0, "divergence populated")
    _assert(
        resp.divergence_headline.endswith("σ"),
        "divergence_headline ends with σ",
    )
    _assert(len(resp.vrp_spread) > 0, "vrp_spread populated")

    log.info("=== ALL ASSERTIONS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
