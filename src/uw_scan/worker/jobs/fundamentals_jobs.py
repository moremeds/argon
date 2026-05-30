"""Nightly massive fundamentals refresh (M5 trade-framework).

For every active watchlist ticker in this worker's shard, fetch the most recent
quarters of financials (+ latest dividend/split summary), derive margins,
fcf, and YoY diluted-share change, and upsert one row per (ticker, period_end).
Nightly cadence, massive role. Mirrors jobs/ohlc_pull.py::ohlc_pull_once.

If ``provider is None`` (no MASSIVE_API_KEY) the job no-ops + warns — never
crashes the scheduler (worker/CLAUDE.md rule).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

logger = logging.getLogger(__name__)


def _margin(numerator: Decimal | None, revenue: Decimal | None) -> Decimal | None:
    if numerator is None or revenue is None or revenue == 0:
        return None
    return numerator / revenue


def _fcf(operating_cf: Decimal | None, investing_cf: Decimal | None) -> Decimal | None:
    """Free cash flow ≈ operating CF + investing CF (investing is negative for
    capex). vX has no direct FCF leaf, so we derive it from the two cash-flow
    leaves; None if either is missing."""
    if operating_cf is None or investing_cf is None:
        return None
    return operating_cf + investing_cf


def _share_count_delta(
    current: Decimal | None, year_ago: Decimal | None
) -> Decimal | None:
    if current is None or year_ago is None or year_ago == 0:
        return None
    return current / year_ago - Decimal(1)


def fundamentals_refresh_once(
    repo,
    provider,
    *,
    ticker_filter: Callable[[str], bool] | None = None,
) -> int:
    if provider is None:
        logger.warning(
            "fundamentals_refresh: no massive provider (MASSIVE_API_KEY unset); "
            "skipping"
        )
        return 0
    completed = 0
    for w in repo.list_active_watchlist():
        if ticker_filter is not None and not ticker_filter(w.ticker):
            logger.debug(
                "fundamentals_refresh skipped %s outside this worker shard", w.ticker
            )
            continue
        try:
            rows = provider.fetch_financials(w.ticker, limit=8)
            if not rows:
                logger.debug("fundamentals_refresh: no financials for %s", w.ticker)
                continue
            by_period = sorted(rows, key=lambda r: r["period_end"])
            dividends = provider.fetch_dividends(w.ticker, limit=4)
            splits = provider.fetch_splits(w.ticker, limit=4)
            latest_div = dividends[0] if dividends else {}
            latest_split = splits[0] if splits else {}
            last_idx = len(by_period) - 1
            for idx, r in enumerate(by_period):
                year_ago = by_period[idx - 4]["diluted_shares"] if idx >= 4 else None
                is_latest = idx == last_idx
                repo.upsert_massive_fundamentals(
                    ticker=w.ticker,
                    period_end=r["period_end"],
                    fiscal_period=r["fiscal_period"],
                    filing_date=r["filing_date"],
                    revenue=r["revenue"],
                    gross_profit=r["gross_profit"],
                    operating_income=r["operating_income"],
                    net_income=r["net_income"],
                    gross_margin=_margin(r["gross_profit"], r["revenue"]),
                    op_margin=_margin(r["operating_income"], r["revenue"]),
                    net_margin=_margin(r["net_income"], r["revenue"]),
                    total_assets=r["total_assets"],
                    total_debt=r["total_debt"],
                    shareholders_equity=r["shareholders_equity"],
                    diluted_shares=r["diluted_shares"],
                    operating_cash_flow=r["operating_cash_flow"],
                    investing_cash_flow=r["investing_cash_flow"],
                    fcf=_fcf(r["operating_cash_flow"], r["investing_cash_flow"]),
                    share_count_delta=_share_count_delta(r["diluted_shares"], year_ago),
                    # corporate-action summary only on the most recent period row
                    last_split_date=(
                        latest_split.get("execution_date") if is_latest else None
                    ),
                    last_split_ratio=(
                        _split_ratio(latest_split) if is_latest else None
                    ),
                    latest_dividend_amount=(
                        latest_div.get("cash_amount") if is_latest else None
                    ),
                    latest_dividend_ex_date=(
                        latest_div.get("ex_dividend_date") if is_latest else None
                    ),
                    raw_jsonb=r.get("raw"),
                )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "fundamentals_refresh failed for %s: %s", w.ticker, repr(exc)
            )
    return completed


def _split_ratio(split: dict) -> Decimal | None:
    """split_to / split_from (e.g. 4-for-1 → 4.0); None if either missing/zero."""
    to = split.get("split_to")
    frm = split.get("split_from")
    if to is None or frm is None or frm == 0:
        return None
    return to / frm
