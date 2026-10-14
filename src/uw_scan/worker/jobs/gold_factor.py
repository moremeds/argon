"""Nightly gold factor: IB prices via xenon -> macro_series_daily -> gold_factor_daily.

1. With a xenon key, fetch the last month of IB 1-day MIDPOINT closes for XAUUSD (CMDTY) and the
   six dollar-index pairs (CASH, IDEALPRO) and store them in macro_series_daily, source 'IB'.
   A month, not a day, so a missed night or a revised bar heals on the next run.
2. Recompute the whole history from macro_series_daily (with FRED DFII10/DGS10) and upsert it:
   the rolling fit is cheap and a revised input converges at once. The synthetic dollar index
   (dxy_synthetic_daily) is upserted from the same levels first; it needs only the six pairs.
A leg xenon could not fetch still lets the compute run on what is stored; the job then raises
naming the legs, so the failure reaches job_failures.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import psycopg

from uw_scan.macro import gold_factor as gf
from uw_scan.sources.xenon_query import fetch_ib_daily_midpoints
from uw_scan.storage import gold_factor as store
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


def _ib_contract(leg: str) -> tuple[str, str, str]:
    return ("CMDTY", leg, "USD") if leg == "XAUUSD" else ("CASH", leg[:3], leg[3:])


def fetch_ib_legs(
    conn: psycopg.Connection,
    *,
    base_url: str,
    api_key: str,
    duration: str = "1 M",
    end_date_time: str = "",
) -> list[str]:
    """Store the IB closes of every price leg; returns the failures as 'LEG: error'."""
    repo = Repository(conn, schema="uw_scan")
    now = datetime.now(UTC)
    failures = []
    for leg in gf.PRICE_LEGS:
        sec_type, symbol, currency = _ib_contract(leg)
        try:
            bars = fetch_ib_daily_midpoints(
                base_url=base_url, api_key=api_key, sec_type=sec_type, symbol=symbol,
                currency=currency, duration=duration, end_date_time=end_date_time,
            )  # fmt: skip
        except Exception as exc:
            logger.exception("gold_factor: xenon fetch %s failed: %r", leg, exc)
            failures.append(f"{leg}: {repr(exc)[:200]}")
            continue
        repo.insert_macro_series_daily_rows(
            ({"series_id": leg, "obs_date": date.fromisoformat(d), "value": v} for d, v in bars),
            as_of=now,
            source="IB",
        )
    conn.commit()
    return failures


def gold_factor_compute_job(
    *, dsn: str, xenon_url: str | None = None, xenon_key: str | None = None
) -> int:
    failures: list[str] = []
    with psycopg.connect(dsn) as conn:
        if xenon_key and xenon_url:
            failures = fetch_ib_legs(conn, base_url=xenon_url, api_key=xenon_key)
        levels = store.fetch_inputs(conn)
        store.upsert_dxy_rows(conn, gf.dxy_daily(levels), datetime.now(UTC))
        chg = gf.changes(levels)
        if len(chg) < gf.W + 2:
            raise RuntimeError(
                f"gold_factor: {len(chg)} complete rows, need {gf.W + 2}; "
                "seed with scripts/backfill/gold_factor_seed.py"
            )
        n = store.upsert_rows(conn, gf.compute(chg), datetime.now(UTC))
    logger.info("gold_factor: upserted %d rows through %s", n, chg.index[-1].date())
    if failures:
        raise RuntimeError(f"gold_factor: computed, but xenon fetch failed for {failures}")
    return n
