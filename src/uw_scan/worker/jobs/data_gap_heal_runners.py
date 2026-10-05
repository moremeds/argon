"""Heal runners: thin wrappers over the production writers.

Each `_run_*` re-runs an existing production job for one gap item (or one
whole dataset); `data_gap_adapters.HEAL_SPECS` maps datasets onto them.
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.worker.jobs.data_gap_heal_context import HealContext

logger = logging.getLogger(__name__)


# --- real adapters (thin wrappers over production writers) -----------------


def _recorder_hook(ctx: HealContext):
    """The ``record_request`` hook bound to the healer's recorder, or None.

    The healer's recorder fails open (``data_gap_healer._make_recorder``
    returns None when it cannot connect), so the adapters pass None rather
    than a hook that would raise on first use.
    """
    recorder = ctx.recorder
    if recorder is None:
        return None
    return lambda _provider, event: recorder.record(event)


def _run_option_surface(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.option_surface_capture import build_ticker_rows

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:option_surface")
    rows = build_ticker_rows(
        client=client,
        repo=ctx.repo,
        run_id=run_id,
        ticker=ticker,
        market_date=market_date,
        date_iso=market_date.isoformat(),
    )
    return ctx.repo.upsert_option_surface_grid(ticker, market_date, None, rows)


def _run_daily_ohlc(ctx: HealContext, ticker: str, lo: date, hi: date) -> int:
    from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once

    provider = ctx.massive_provider()
    lookback = max(1, (ctx.today - lo).days + 2)
    return ohlc_pull_once(
        repo=ctx.repo,
        provider=provider,
        lookback_days=lookback,
        ticker_filter=lambda t: t.upper() == ticker.upper(),
    )


def _run_greek_exposure(ctx: HealContext, ticker: str, lo: date, hi: date) -> int:
    """Heal a ticker's whole range from UW's aggregate greek-exposure series.

    `lo`/`hi` are accepted for the per_ticker_range contract and intentionally
    unused: one call returns the full series, so the upsert covers every
    missing date at once.

    Measured 2026-08-16: `/greek-exposure/{ticker}` returns the FULL ~250-row
    date series, so PAST dates heal from the same single call — the previous
    "current-snapshot only" comment here was wrong.

    The nightly `greek_exposure_daily_refresh` job is deliberately NOT reused:
    it skips `settings.gex_scan_tickers` (11 mega-caps + ETFs) to avoid
    double-fetching with the regime GEX scan, which made exactly those names
    unhealable while `skipped_index` made the skip look intentional.
    """
    from uw_scan.scanners.gex import fetch_aggregate_gex
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:greek_exposure")
    try:
        rows = fetch_aggregate_gex(client, ctx.repo, run_id, ticker)
        # KEY MISMATCH, verified 2026-08-16: parse_greek_exposure_history emits
        # `date` (cards/greek_exposure_history.py) but upsert_rows does a bare
        # r["trade_date"] (storage/greek_exposure_repository.py). Passing the
        # parser's rows straight through raises KeyError on the first real call.
        # Map it here — do NOT "fix" the parser, the chart read-path reads `date`.
        rows = [{**r, "trade_date": r["date"]} for r in rows if r.get("date")]
        written = GreekExposureDailyRepository(
            ctx.repo.conn, schema=ctx.schema
        ).upsert_rows(ticker, rows)
        ctx.repo.finish_scan_run(run_id, status="ok")
        return written
    except Exception as exc:  # noqa: BLE001
        ctx.repo.finish_scan_run(run_id, status="error")
        logger.warning("gex heal failed for %s: %s", ticker, repr(exc))
        raise


def _uw_alpha_repo(ctx: HealContext):
    from uw_scan.storage.uw_historical_alpha_repository import (
        UwHistoricalAlphaRepository,
    )

    return UwHistoricalAlphaRepository(ctx.repo.conn, schema=ctx.schema)


def _run_gex_levels(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.uw_alpha_capture import capture_gex_levels_for

    # No commit here: the heal write stays in ctx.repo.conn's tx and is flushed
    # atomically with the item status by mark_item_healed (see _run_option_surface).
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:gex_levels")
    n = capture_gex_levels_for(
        ctx.uw_client(), ctx.repo, _uw_alpha_repo(ctx), run_id, ticker, market_date
    )
    ctx.repo.finish_scan_run(run_id, status="ok")
    return n


def _run_volatility_signal(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.uw_alpha_capture import capture_volatility_signal_for

    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:volatility_signal")
    n = capture_volatility_signal_for(
        ctx.uw_client(), ctx.repo, _uw_alpha_repo(ctx), run_id, ticker, market_date
    )
    ctx.repo.finish_scan_run(run_id, status="ok")
    return n


def _run_short_pressure(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.uw_alpha_capture import capture_short_pressure_for

    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:short_pressure")
    n = capture_short_pressure_for(
        ctx.uw_client(), ctx.repo, _uw_alpha_repo(ctx), run_id, ticker, market_date
    )
    ctx.repo.finish_scan_run(run_id, status="ok")
    return n


def _run_vol_rollup(ctx: HealContext) -> int:
    from uw_scan.worker.volatility_jobs import nightly_vol_analytics_rollup

    nightly_vol_analytics_rollup(repo=ctx.repo)
    return 0


def _run_realized_volatility(ctx: HealContext, ticker: str, lo: date, hi: date) -> int:
    # UW's /volatility/realized returns the full ~1y series in ONE call (lo/hi
    # ignored — UW picks its own trailing window), so one call heals every
    # date-gap for the ticker. realized_volatility_history is the foundational
    # series the vol rollup derives vrp/stock_analytics from.
    from uw_scan.sources.uw import fetch_realized_volatility

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:realized_vol")
    rows = fetch_realized_volatility(client, ctx.repo, run_id, ticker)
    return ctx.repo.upsert_realized_vol_rows(ticker, rows)


def _run_volatility_stats(ctx: HealContext, ticker: str, market_date: date) -> int:
    # UW's /volatility/stats returns ONE row per (ticker, date) via ?date=, so
    # this is one UW call per cell — the YTD vol-stats backfill. A past date UW
    # no longer serves verifies false and is recorded honest no_data.
    from uw_scan.sources.uw import fetch_volatility_stats

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:vol_stats")
    rows = fetch_volatility_stats(
        client, ctx.repo, run_id, ticker, market_date=market_date
    )
    return ctx.repo.upsert_volatility_stats_rows(rows)


def _run_sentiment(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.market_tide_sentiment import refresh_eod_sentiment

    return refresh_eod_sentiment(repo=ctx.repo, sessions=max(1, lookback_days))


# macro/FRED/rates/gold: re-run an idempotent ingest over a lookback window.
# These are free external sources (uncapped) except gold UW options.


def _run_macro_fred(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_fred_ingest_job

    gold_fred_ingest_job(
        dsn=ctx.settings.db_dsn(),
        lookback_days=lookback_days,
        record_request=_recorder_hook(ctx),
    )
    return 0


def _run_rates_fred(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job

    key = (
        ctx.settings.fred_api_key.get_secret_value()
        if ctx.settings.fred_api_key
        else None
    )
    rates_fred_ingest_job(
        dsn=ctx.settings.db_dsn(),
        fred_api_key=key,
        lookback_days=lookback_days,
        record_request=_recorder_hook(ctx),
    )
    return 0


def _run_gold_posture(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import (
        _latest_gold_market_date,
        gold_posture_compute_job,
    )

    # Fill a missing day only. Readers take the FIRST active row per obs_date, so a
    # recompute beside an existing row is never read -- it only made a 4th row a day.
    target = _latest_gold_market_date(ctx.repo)
    if ctx.repo.fetch_gold_posture_for_obs_date(target) is not None:
        return 0
    gold_posture_compute_job(dsn=ctx.settings.db_dsn(), as_of=target)
    return 0


def _run_gold_lbma(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_lbma_vault_ingest_job

    gold_lbma_vault_ingest_job(
        dsn=ctx.settings.db_dsn(), record_request=_recorder_hook(ctx)
    )
    return 0


def _run_gold_cot(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_cftc_cot_ingest_job

    gold_cftc_cot_ingest_job(
        dsn=ctx.settings.db_dsn(), record_request=_recorder_hook(ctx)
    )
    return 0


def _run_gold_uw_options(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_uw_options_ingest_job

    gold_uw_options_ingest_job(
        dsn=ctx.settings.db_dsn(),
        api_key=ctx.settings.api_key.get_secret_value(),
        base_url=ctx.settings.base_url,
    )
    return 0


# --- entrypoints that were already date-aware -------------------------------
# Every adapter below wraps a production writer that ALREADY accepts the date
# (or already recomputes its full history). The registry refused all of them on
# an assumption that round 1 measured false on 2026-08-16.


def _run_cri_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import cri

    out = cri.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_spx_density_reconstruct(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.spx_density_forecast import reconstruct_recent_gaps

    out = reconstruct_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_vcg_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import vcg

    out = vcg.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_canary_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import canary

    out = canary.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_market_tide(ctx: HealContext, ticker: str | None, market_date: date) -> int:
    """Sessionwide dataset — `ticker` is None (strict_session items carry no
    ticker); accepted and ignored to satisfy the per_ticker_date contract.

    capture_spot=False is REQUIRED: the live spot stamp is meaningless against a
    past bar, and writing it would be fabricated history, not a backfill.
    """
    from uw_scan.scanners import market_tide

    return market_tide.run(
        ctx.uw_client(), ctx.repo, trading_date=market_date, capture_spot=False
    )


def _run_top_net_impact(ctx: HealContext, ticker: str | None, market_date: date) -> int:
    """Sessionwide — `ticker` is None in production. See _run_market_tide."""
    from uw_scan.scanners import top_net_impact

    return top_net_impact.run(ctx.uw_client(), ctx.repo, trading_date=market_date)


def _run_technical_daily(ctx: HealContext, lookback_days: int) -> int:
    """Recomputes the FULL series per ticker from apex bars, so one run heals
    every historical hole at once — no per-date plumbing needed or wanted."""
    from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

    out = technical_daily_refresh(repo=ctx.repo, settings=ctx.settings)
    return int(out.get("ok", 0))  # {"ok","skipped_thin","failed","tickers"}


def _run_corporate_actions(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.corporate_actions_jobs import (
        corporate_actions_refresh_once,
    )

    return corporate_actions_refresh_once(ctx.repo, ctx.massive_provider())


def _run_massive_fundamentals(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once

    return fundamentals_refresh_once(repo=ctx.repo, provider=ctx.massive_provider())


def _run_grg(ctx: HealContext, ticker: str | None, market_date: date) -> int:
    """Marketwide — `ticker` is None (strict_session items carry no ticker).

    Returns 0 for an as_of the series cannot support: grg.run needs 70 aligned
    observations, so an as_of near the start of the fetched 1Y window
    legitimately has too little history. The item is then recorded as honest
    no_data — that is the correct answer, not a window to widen.
    """
    from uw_scan.scanners import grg

    row_id = grg.run(ctx.uw_client(), ctx.repo, ctx.schema, as_of=market_date)
    return 1 if row_id is not None else 0


# --- lake + UW event-log adapters -------------------------------------------


def _run_vol_index_lake(ctx: HealContext, lookback_days: int) -> int:
    """BOTH lake syncs write vol_index_daily — a registry entry names exactly one
    adapter, so one adapter must run both. Idempotent and full-range;
    lookback_days is unused.

    Roots come from resolve_lake_root(asset_class=...), NOT
    settings.market_warehouse_lake_root — config.py documents that field as the
    root of the WHOLE lake, distinct from the two asset-class roots, which point
    at specific bronze partitions. Mirrors the scheduler's own call sites.
    """
    from uw_scan.sources.lake_resolver import resolve_lake_root
    from uw_scan.worker.jobs import credit_etf_lake_sync, vol_index_lake_sync

    vol = vol_index_lake_sync.run_vol_index_lake_sync(
        conn=ctx.repo.conn,
        root=resolve_lake_root(ctx.settings, asset_class="volatility"),
    )
    credit = credit_etf_lake_sync.run_credit_etf_lake_sync(
        conn=ctx.repo.conn,
        root=resolve_lake_root(ctx.settings, asset_class="equity"),
        symbols=ctx.settings.credit_etf_symbols,
    )
    return int(vol.get("rows", 0)) + int(credit.get("rows", 0))


def _run_index_ohlc(ctx: HealContext, lookback_days: int) -> int:
    """index_ohlc_daily comes from daily_spy_ohlc_refresh, NOT the lake syncs.

    Returns 0 because the writer returns None; verification is by row presence,
    which is what _verify_covered checks anyway.
    """
    from uw_scan.worker.volatility_jobs import daily_spy_ohlc_refresh

    if ctx.settings.massive_api_key is None:
        raise RuntimeError("MASSIVE_API_KEY not set; index_ohlc heal unavailable")
    daily_spy_ohlc_refresh(
        repo=ctx.repo,
        api_key=ctx.settings.massive_api_key.get_secret_value(),
        lookback_days=max(2, lookback_days),
        telemetry_recorder=ctx.recorder,
    )
    return 0


def _eventlog_heal(capture_fn):
    """Both UW event logs share one shape: (ticker, date) -> one capture call.

    `scripts/backfill/uw_alpha_catchup.py` already maps dataset -> capture fn in
    its own table; these adapters call the SAME production functions, so there
    is still exactly one writer and the CLI needs no change.
    """

    def _run(ctx: HealContext, ticker: str, market_date: date) -> int:
        run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:eventlog")
        try:
            written = capture_fn(
                ctx.uw_client(),
                ctx.repo,
                _uw_alpha_repo(ctx),
                run_id,
                ticker,
                market_date,
            )
            ctx.repo.finish_scan_run(run_id, status="ok")
            return int(written)
        except Exception as exc:  # noqa: BLE001
            ctx.repo.finish_scan_run(run_id, status="error")
            logger.warning(
                "eventlog heal failed %s %s: %s", ticker, market_date, repr(exc)
            )
            raise

    return _run


def _run_fundamental_refresh(ctx: HealContext) -> int:
    """Routing -> subscores -> anchor bands. Zero UW/IB spend: every stage reads
    fundamental_statement_obs and the lake, so this heals fundamental_scores and
    valuation_anchors without touching a provider.

    It deliberately does NOT ingest — new filings come from
    scripts/backfill/fundamental_ingest_backfill.py, which is why
    fundamental_statement_obs keeps its own separate disposition.

    Counter names verified 2026-08-16: fundamental_scoring returns `inserted`,
    fundamental_anchors returns `written`.
    """
    from uw_scan.worker.jobs.fundamental_refresh import fundamental_refresh

    out = fundamental_refresh(conn=ctx.repo.conn, settings=ctx.settings)
    scoring = out.get("scoring") or {}
    anchors = out.get("anchors") or {}
    return int(scoring.get("inserted", 0)) + int(anchors.get("written", 0))


def _run_flow_chain_replay(ctx: HealContext, ticker: str, market_date: date) -> int:
    """Replay one ticker's option_chain_per_strike snapshot for a past session.

    Separate from `pipeline_replay` because a different job owns this table
    (flow_data_refresh, not run_single_stock) and it needs that session's close
    to pick the strike band. Returns 0 when the lake has no close for the date —
    the healer records no_data rather than substituting a live quote, which
    would select the wrong strikes.
    """
    from uw_scan.worker.jobs.flow_data_refresh import (
        historical_close,
        refresh_ticker_chain,
    )

    spot = historical_close(ctx.repo, ticker, market_date)
    if spot is None or spot <= 0:
        logger.info(
            "flow_chain_replay: %s %s has no daily_ohlc close — skipped",
            ticker,
            market_date.isoformat(),
        )
        return 0
    return refresh_ticker_chain(
        repo=ctx.repo,
        client=ctx.uw_client(),
        ticker=ticker,
        spot=spot,
        market_date=market_date,
    )


def _replay_run_single_stock(ticker, client, repo, market_date=None):
    """Seam for tests; the real callable is the production pipeline entrypoint."""
    from uw_scan.pipeline import run_single_stock

    return run_single_stock(ticker, client, repo, market_date=market_date)


def _run_pipeline_replay(ctx: HealContext, ticker: str, market_date: date) -> int:
    """Re-run the nightly deep scan for one past session.

    ``run_single_stock(market_date=...)`` re-fetches every date-honouring UW
    endpoint at its true date and writes ~11 tables in one pass, so this single
    adapter is registered for all of them. Datasets whose endpoint ignores
    ``date`` are NOT wired here — the pipeline itself refuses to write them under
    a historical stamp (``uw_scan.pipeline_replay_policy``).

    Returns 1 rather than a row count: the pipeline writes many tables and does
    not report per-table totals, and the healer only needs "did this item get
    covered". The verify pass re-reads the table to confirm rows actually landed,
    so a lie here would be caught there.
    """
    key = (ticker.upper(), market_date)
    if key in ctx._replayed:
        return 1  # already healed by a sibling dataset in this run
    _replay_run_single_stock(ticker, ctx.uw_client(), ctx.repo, market_date=market_date)
    ctx._replayed.add(key)
    return 1
