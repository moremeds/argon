"""Daily UW positioning refresh (M4 trade-framework).

For every active watchlist ticker in this worker's shard, fetch the five UW
positioning endpoints, aggregate them into one uw_positioning snapshot row, and
upsert. Daily cadence, uw-role — NOT folded into full_scan (keeps scan-loop UW
QPS flat). Mirrors jobs/ohlc_pull.py::ohlc_pull_once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from uw_scan.sources import uw

logger = logging.getLogger(__name__)


def _json_safe(data: dict) -> dict:
    """Decimal→str, date/datetime→isoformat so the summary fits a jsonb column."""
    out: dict = {}
    for key, value in data.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, (date, datetime)):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def positioning_refresh_once(
    repo,
    client,
    *,
    ticker_filter: Callable[[str], bool] | None = None,
) -> int:
    completed = 0
    today = date.today()
    for w in repo.list_active_watchlist():
        if ticker_filter is not None and not ticker_filter(w.ticker):
            logger.debug(
                "positioning_refresh skipped %s outside this worker shard", w.ticker
            )
            continue
        run_id = repo.insert_scan_run(ticker=w.ticker, notes="positioning_refresh")
        try:
            si = uw.fetch_short_interest_float(client, repo, run_id, w.ticker)
            analyst = uw.fetch_analyst_ratings(client, repo, run_id, w.ticker)
            inst = uw.fetch_institution_ownership(client, repo, run_id, w.ticker)
            insider = uw.fetch_insider_ticker_flow(client, repo, run_id, w.ticker)
            earn = uw.fetch_earnings_history(client, repo, run_id, w.ticker)
            raw = {
                "short_interest_float": _json_safe(si),
                "analyst_ratings": _json_safe(analyst),
                "institution_ownership": _json_safe(inst),
                "insider_ticker_flow": _json_safe(insider),
                "earnings_history": _json_safe(earn),
            }
            repo.upsert_uw_positioning(
                ticker=w.ticker,
                snapshot_date=today,
                **si,
                **analyst,
                **inst,
                **insider,
                **earn,
                raw_jsonb=raw,
            )
            repo.finish_scan_run(run_id, status="ok")
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "positioning_refresh failed for %s: %s", w.ticker, repr(exc)
            )
            repo.finish_scan_run(run_id, status="error")
    return completed
