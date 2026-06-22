"""Ingest full split/dividend history into corporate_actions (item 1 support).

massive_fundamentals keeps only the LATEST split/dividend; split-adjusting a
multi-month price series needs every event, so this pulls deeper history into a
dedicated event table. Null-object safe (no MASSIVE_API_KEY → no-op + warn).
Mirrors jobs/fundamentals_jobs.py.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

logger = logging.getLogger(__name__)


def _split_ratio(split: dict) -> Decimal | None:
    to, frm = split.get("split_to"), split.get("split_from")
    if to is None or frm is None or frm == 0:
        return None
    return to / frm


def corporate_actions_refresh_once(
    repo,
    provider,
    *,
    ticker_filter: Callable[[str], bool] | None = None,
    split_limit: int = 12,
    dividend_limit: int = 24,
) -> int:
    if provider is None:
        logger.warning(
            "corporate_actions_refresh: no massive provider (MASSIVE_API_KEY unset); "
            "skipping"
        )
        return 0
    completed = 0
    # ISSUE-9: cover the SCORING universe, not just the active watchlist.
    watch = {w.ticker for w in repo.list_active_watchlist()}
    tickers = sorted(watch | set(repo.fetch_distinct_vrp_tickers()))
    for ticker in tickers:
        if ticker_filter is not None and not ticker_filter(ticker):
            continue
        try:
            for s in provider.fetch_splits(ticker, limit=split_limit):
                if s.get("execution_date") is None:
                    continue
                repo.upsert_corporate_action(
                    ticker=ticker,
                    event_type="split",
                    event_date=s["execution_date"],
                    split_ratio=_split_ratio(s),
                )
            for d in provider.fetch_dividends(ticker, limit=dividend_limit):
                if d.get("ex_dividend_date") is None:
                    continue
                repo.upsert_corporate_action(
                    ticker=ticker,
                    event_type="dividend",
                    event_date=d["ex_dividend_date"],
                    cash_amount=d.get("cash_amount"),
                )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "corporate_actions_refresh failed for %s: %s", ticker, repr(exc)
            )
    return completed
