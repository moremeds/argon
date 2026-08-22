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
    # Both limits lean on massive returning NEWEST-FIRST, which it does: probed
    # 2026-08-22, AAPL's 5 splits come back 2020-08-31 ... 1987-06-16 descending.
    # Ascending would truncate away the RECENT events, the only ones the band's
    # 20-quarter window can contain. The margin is wide anyway — the widest
    # lifetime split history in the sample was AAPL's 5 against a limit of 12 —
    # so this is a note on a dependency, not a live risk.
    if provider is None:
        logger.warning(
            "corporate_actions_refresh: no massive provider (MASSIVE_API_KEY unset); "
            "skipping"
        )
        return 0
    completed = 0
    # ISSUE-9: cover the SCORING universe, not just the active watchlist.
    # The fundamental universe joined that union on 2026-08-21, when this covered
    # 137 of its 450 names. The band job prices from livewire's adjusted silver
    # tier and does not adjust anything with these rows — it reads them to decide
    # whether a name silver has NO series for may be priced from raw bronze
    # anyway (see `fetch_fundamental_universe_tickers`). Absent a row it cannot
    # tell "never split" from "not ingested", and bands the name either way.
    watch = {w.ticker for w in repo.list_active_watchlist()}
    tickers = sorted(
        watch
        | set(repo.fetch_distinct_vrp_tickers())
        | set(repo.fetch_fundamental_universe_tickers())
    )
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
            # Persist per-ticker: the scheduler's _repo() closes the connection
            # without committing (psycopg rolls back on close), so an uncommitted
            # ingest would silently leave corporate_actions empty.
            repo.conn.commit()
            completed += 1
        except Exception as exc:  # noqa: BLE001
            # Recover the aborted transaction so one bad ticker does not poison
            # every subsequent ticker (InFailedSqlTransaction).
            repo.conn.rollback()
            logger.exception(
                "corporate_actions_refresh failed for %s: %s", ticker, repr(exc)
            )
    return completed
