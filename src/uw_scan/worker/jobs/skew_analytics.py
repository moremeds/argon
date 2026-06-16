"""Skew analytics worker jobs: nightly rollup + historical backfill."""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta

from uw_scan.reports.skew_analytics import build_skew_snapshot_row
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _build_for_date(
    repo: Repository,
    ticker: str,
    market_date: _date,
    today: _date,
    full_rr: list[dict],
    full_rv: list[dict],
    spy_rv: list[dict],
    sector: str | None,
    next_earnings_date: _date | None,
    positioning: dict | None,
    exposure_rows: list[dict] | None = None,
) -> dict | None:
    # positioning is passed in (fetched once per ticker by the caller) — it is the
    # latest snapshot regardless of market_date (current-borrow limitation, spec §11),
    # so re-fetching per date would be wasteful and identical.
    rr = [r for r in full_rr if r["market_date"] <= market_date]
    rv = [r for r in full_rv if r["market_date"] <= market_date]
    spy = [r for r in spy_rv if r["market_date"] <= market_date]
    if not rr or not rv:
        return None
    expiry_rows = repo.fetch_matrix_skew_expiry_rows(
        ticker=ticker, market_date=rr[-1]["market_date"]
    )
    pre = build_skew_snapshot_row(
        ticker=ticker,
        market_date=market_date,
        rr_series=rr,
        expiry_rows=expiry_rows,
        rv_series=rv,
        spy_rv_series=spy,
        positioning=positioning,
        next_earnings_date=next_earnings_date,
        verdict=None,
        sector=sector,
        today=today,
    )
    verdict = repo.get_skew_directional_verdict(
        asset_class=pre["asset_class"],
        deviation_class=pre["deviation_class"],
        drive_class=pre["drive_class"],
        regime=pre["regime"],
    )
    return build_skew_snapshot_row(
        ticker=ticker,
        market_date=market_date,
        rr_series=rr,
        expiry_rows=expiry_rows,
        rv_series=rv,
        spy_rv_series=spy,
        positioning=positioning,
        next_earnings_date=next_earnings_date,
        verdict=verdict,
        sector=sector,
        today=today,
        exposure_rows=exposure_rows,
    )


def nightly_skew_analytics_rollup(*, repo: Repository) -> None:
    """One basis='eod' snapshot per watchlist ticker for the latest RR date.

    Uses the current earnings date + current borrow (live snapshot). Run AFTER
    run_skew_markout so the persisted directional_lean reflects fresh verdicts;
    the endpoint recomputes the lean live, so the snapshot lean is only a cache.
    """
    cards = repo.list_watchlist_cards()
    today = _date.today()
    spy_rv = repo.fetch_realized_vol_history("SPY", days=400)
    written = 0
    for card in cards:
        ticker = card.ticker
        rr = repo.fetch_matrix_skew_history(ticker=ticker, market_date=today, days=400)
        rv = repo.fetch_realized_vol_history(ticker, days=400)
        if not rr or not rv:
            continue
        next_er = repo.fetch_latest_next_earnings_date(ticker)
        positioning = repo.get_uw_positioning(ticker)
        exposures = repo.fetch_latest_exposures_by_strike(ticker, dte_max=70)
        row = _build_for_date(
            repo,
            ticker,
            rr[-1]["market_date"],
            today,
            rr,
            rv,
            spy_rv,
            card.sector,
            next_er,
            positioning,
            exposures,
        )
        if row is not None:
            repo.upsert_skew_analytics_snapshots([row])
            written += 1
    repo.conn.commit()
    log.info("nightly_skew_analytics_rollup wrote %d snapshots", written)


def skew_analytics_backfill(
    *, repo: Repository, start: _date, end: _date, tickers: list[str] | None = None
) -> int:
    """Compute snapshots across [start, end] (inclusive) for the Tier-1 set.

    Historical rows have NO point-in-time earnings (next_earnings_date=None ->
    earnings_gate='unknown') and reuse CURRENT borrow (documented limitation,
    spec §11). Neither feeds the markout's directional separation (which buckets
    on deviation/drive/regime/asset_class and the current borrow_flag), so the
    Tier-1 verdicts are not corrupted by the absence of PIT earnings.
    """
    if tickers is None:
        tickers = [c.ticker for c in repo.list_watchlist_cards()]
    spy_rv = repo.fetch_realized_vol_history("SPY", days=4000)
    written = 0
    for ticker in tickers:
        rr = repo.fetch_matrix_skew_history(ticker=ticker, market_date=end, days=4000)
        rv = repo.fetch_realized_vol_history(ticker, days=4000)
        if not rr or not rv:
            continue
        sector = repo.fetch_watchlist_sector(ticker)
        positioning = repo.get_uw_positioning(ticker)  # once per ticker, not per date
        rr_dates = {r["market_date"] for r in rr}
        d = start
        rows = []
        while d <= end:
            if d in rr_dates:
                row = _build_for_date(
                    repo, ticker, d, d, rr, rv, spy_rv, sector, None, positioning
                )
                if row is not None:
                    rows.append(row)
            d += timedelta(days=1)
        if rows:
            repo.upsert_skew_analytics_snapshots(rows)
            written += len(rows)
    repo.conn.commit()
    log.info("skew_analytics_backfill wrote %d snapshots", written)
    return written
