"""Heal dispatch for the data gap healer.

One dispatch table over EXISTING production jobs, not bespoke adapter classes.
Each healable dataset maps (via registry.healer_adapter) to a `HealSpec` whose
`run` calls a production writer; the executor dispatches on `granularity` and
verifies every item against the dataset's own table before marking it healed.

Granularity contracts for `HealSpec.run`:
  run_once          : run(ctx) -> int                       (whole-dataset job)
  run_once_lookback : run(ctx, lookback_days) -> int        (idempotent ingest w/ window)
  per_ticker_range  : run(ctx, ticker, lo, hi) -> int       (one fetch per ticker)
  per_ticker_date   : run(ctx, ticker, market_date) -> int  (one cell; UW-budget gated)

Only the `uw` provider bucket is capped (the scarce resource); massive/external/
db are unbounded. A heal that the underlying job cannot reconstruct (old date,
provider has no history) verifies false and is recorded as honest `no_data`.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from psycopg import sql as psql

from uw_scan.worker.jobs.uw_alpha_capture import (
    capture_dark_lit_for,
    capture_intraday_flow_for,
)
from uw_scan.reports.data_gap_healer import (
    _DATE_COL_PREFERENCE,
    Caveat,
    _TICKER_COL_PREFERENCE,
    REGISTRY,
    DatasetRegistryEntry,
    _detect_col,
)

logger = logging.getLogger(__name__)

_BUCKETS = ("uw", "massive", "external", "db")


class RequestBudget:
    """Per-provider spend tracker. Only UW is capped; the rest are unbounded.

    `dataset_share` additionally caps any SINGLE dataset at that fraction of the
    UW cap, so one large backlog cannot drain the whole night and leave every
    other dataset on `skipped_budget`. None/1.0 reproduces the original
    drain-it-all behaviour exactly.
    """

    def __init__(
        self, uw_cap: int | None, *, dataset_share: float | None = None
    ) -> None:
        self.uw_cap = uw_cap
        self.dataset_share = dataset_share
        self.spent: dict[str, int] = {b: 0 for b in _BUCKETS}
        self.by_dataset: dict[str, int] = {}
        self._current: str | None = None

    def begin_dataset(self, dataset: str) -> None:
        self._current = dataset
        self.by_dataset.setdefault(dataset, 0)

    def _slice(self) -> int | None:
        if self.uw_cap is None or not self.dataset_share or self.dataset_share >= 1:
            return None
        return max(1, int(self.uw_cap * self.dataset_share))

    def can_spend(self, provider: str, n: int) -> bool:
        if provider != "uw" or self.uw_cap is None:
            return True
        if self.spent["uw"] + n > self.uw_cap:
            return False
        cap = self._slice()
        if cap is not None and self._current is not None:
            if self.by_dataset.get(self._current, 0) + n > cap:
                return False
        return True

    def record(self, provider: str, n: int) -> None:
        if provider in self.spent:
            self.spent[provider] += n
        if provider == "uw" and self._current is not None:
            self.by_dataset[self._current] = self.by_dataset.get(self._current, 0) + n

    def as_dict(self) -> dict[str, int]:
        return dict(self.spent)


@dataclass
class HealContext:
    repo: object  # uw_scan.storage.repository.Repository
    gap: object  # DataGapHealerRepository
    schema: str
    today: date
    budget: RequestBudget
    settings: object | None = None  # uw_scan.config.Settings (real adapters only)
    registry_by_table: dict[str, DatasetRegistryEntry] = field(default_factory=dict)
    _uw: object | None = field(default=None, repr=False)
    # (ticker, date) pairs already replayed in THIS heal run. One
    # run_single_stock call writes ~11 tables, so the ~11 datasets wired to
    # the replay adapter must fan in to a single UW spend per pair.
    _replayed: set = field(default_factory=set, repr=False)
    _massive: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.registry_by_table:
            self.registry_by_table = {e.table_name: e for e in REGISTRY}

    def uw_client(self):
        if self._uw is None:
            from uw_scan.api.client import UwClient

            self._uw = UwClient(
                api_key=self.settings.api_key.get_secret_value(),
                base_url=self.settings.base_url,
                timeout=self.settings.request_timeout_seconds,
                job_name="data_gap_healer",
            )
        return self._uw

    def massive_provider(self):
        if self._massive is None:
            from uw_scan.sources.ohlc import MassiveOhlcProvider

            if self.settings.massive_api_key is None:
                raise RuntimeError(
                    "MASSIVE_API_KEY not set; daily_ohlc heal unavailable"
                )
            self._massive = MassiveOhlcProvider(
                api_key=self.settings.massive_api_key.get_secret_value(),
                base_url=self.settings.massive_base_url,
                timeout=self.settings.request_timeout_seconds,
                job_name="data_gap_healer",
            )
        return self._massive


@dataclass(frozen=True)
class HealSpec:
    adapter: str
    provider: str
    granularity: str
    run: Callable
    est_per_item: int = 1  # estimated provider calls; charged to the budget bucket


# --- real adapters (thin wrappers over production writers) -----------------


def _run_option_surface(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.option_surface_capture import _build_ticker_rows

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:option_surface")
    rows = _build_ticker_rows(
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
        ctx.repo,
        provider,
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

    return refresh_eod_sentiment(ctx.repo, sessions=max(1, lookback_days))


# macro/FRED/rates/gold: re-run an idempotent ingest over a lookback window.
# These are free external sources (uncapped) except gold UW options.


def _run_macro_fred(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_fred_ingest_job

    gold_fred_ingest_job(dsn=ctx.settings.db_dsn(), lookback_days=lookback_days)
    return 0


def _run_rates_fred(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job

    key = (
        ctx.settings.fred_api_key.get_secret_value()
        if ctx.settings.fred_api_key
        else None
    )
    rates_fred_ingest_job(
        dsn=ctx.settings.db_dsn(), fred_api_key=key, lookback_days=lookback_days
    )
    return 0


def _run_gold_posture(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_posture_compute_job

    gold_posture_compute_job(dsn=ctx.settings.db_dsn())
    return 0


def _run_gold_comex(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_comex_vault_ingest_job

    gold_comex_vault_ingest_job(dsn=ctx.settings.db_dsn())
    return 0


def _run_gold_cot(ctx: HealContext) -> int:
    from uw_scan.worker.jobs.gold_jobs import gold_cftc_cot_ingest_job

    gold_cftc_cot_ingest_job(dsn=ctx.settings.db_dsn())
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

    return fundamentals_refresh_once(ctx.repo, ctx.massive_provider())


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
        ctx.repo.conn,
        root=resolve_lake_root(ctx.settings, asset_class="volatility"),
    )
    credit = credit_etf_lake_sync.run_credit_etf_lake_sync(
        ctx.repo.conn,
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
    _replay_run_single_stock(
        ticker, ctx.uw_client(), ctx.repo, market_date=market_date
    )
    ctx._replayed.add(key)
    return 1


HEAL_SPECS: dict[str, HealSpec] = {
    # --- pipeline replay: ONE run_single_stock(market_date=...) writes all nine
    # datasets that name this adapter, so it fans in per (ticker, date) and the
    # eight sibling items cost nothing. est_per_item=2 x 9 items = ~18 estimated
    # against ~15 actual calls; over-estimating is the safe direction for a
    # budget governor, which is why this is not tuned down to 15/9.
    "pipeline_replay": HealSpec(
        "pipeline_replay", "uw", "per_ticker_date", _run_pipeline_replay, est_per_item=2
    ),
    "flow_chain_replay": HealSpec(
        "flow_chain_replay", "uw", "per_ticker_date", _run_flow_chain_replay, est_per_item=1
    ),

    "fundamental_refresh": HealSpec(
        "fundamental_refresh",
        "db",
        "run_once",
        _run_fundamental_refresh,
        est_per_item=0,
    ),
    "vol_index_lake": HealSpec(
        "vol_index_lake",
        "db",
        "run_once_lookback",
        _run_vol_index_lake,
        est_per_item=0,
    ),
    "index_ohlc": HealSpec(
        "index_ohlc", "massive", "run_once_lookback", _run_index_ohlc, est_per_item=1
    ),
    "uw_alpha_intraday_flow": HealSpec(
        "uw_alpha_intraday_flow",
        "uw",
        "per_ticker_date",
        _eventlog_heal(capture_intraday_flow_for),
        est_per_item=2,
    ),
    "uw_alpha_dark_lit": HealSpec(
        "uw_alpha_dark_lit",
        "uw",
        "per_ticker_date",
        _eventlog_heal(capture_dark_lit_for),
        est_per_item=2,
    ),
    "grg_as_of": HealSpec(
        "grg_as_of", "uw", "per_ticker_date", _run_grg, est_per_item=2
    ),
    "cri_recover": HealSpec(
        "cri_recover", "db", "run_once_lookback", _run_cri_recover, est_per_item=0
    ),
    "vcg_recover": HealSpec(
        "vcg_recover", "db", "run_once_lookback", _run_vcg_recover, est_per_item=0
    ),
    "canary_recover": HealSpec(
        "canary_recover", "db", "run_once_lookback", _run_canary_recover, est_per_item=0
    ),
    "market_tide": HealSpec(
        "market_tide", "uw", "per_ticker_date", _run_market_tide, est_per_item=1
    ),
    "top_net_impact": HealSpec(
        "top_net_impact", "uw", "per_ticker_date", _run_top_net_impact, est_per_item=1
    ),
    "technical_daily": HealSpec(
        "technical_daily",
        "db",
        "run_once_lookback",
        _run_technical_daily,
        est_per_item=0,
    ),
    "corporate_actions": HealSpec(
        "corporate_actions",
        "massive",
        "run_once_lookback",
        _run_corporate_actions,
        est_per_item=0,
    ),
    "massive_fundamentals": HealSpec(
        "massive_fundamentals",
        "massive",
        "run_once_lookback",
        _run_massive_fundamentals,
        est_per_item=0,
    ),
    "option_surface": HealSpec(
        "option_surface", "uw", "per_ticker_date", _run_option_surface, est_per_item=20
    ),
    "daily_ohlc": HealSpec(
        "daily_ohlc", "massive", "per_ticker_range", _run_daily_ohlc, est_per_item=1
    ),
    "greek_exposure_daily": HealSpec(
        "greek_exposure_daily",
        "uw",
        # One call returns the whole ~250-row series, so per-DATE would re-fetch
        # it once per missing day (11 tickers x 4 dates = 44 calls where 11 do).
        "per_ticker_range",
        _run_greek_exposure,
        est_per_item=1,
    ),
    "gex_levels": HealSpec(
        "gex_levels", "uw", "per_ticker_date", _run_gex_levels, est_per_item=1
    ),
    "volatility_signal": HealSpec(
        "volatility_signal",
        "uw",
        "per_ticker_date",
        _run_volatility_signal,
        est_per_item=3,  # anomaly + character + vrp
    ),
    "short_pressure": HealSpec(
        "short_pressure",
        "uw",
        "per_ticker_date",
        _run_short_pressure,
        est_per_item=3,  # interest-float + ftds + volumes-by-exchange
    ),
    "vol_analytics_rollup": HealSpec(
        "vol_analytics_rollup", "db", "run_once", _run_vol_rollup, est_per_item=0
    ),
    "realized_volatility": HealSpec(
        "realized_volatility",
        "uw",
        "per_ticker_range",
        _run_realized_volatility,
        est_per_item=1,
    ),
    "volatility_stats": HealSpec(
        "volatility_stats",
        "uw",
        "per_ticker_date",
        _run_volatility_stats,
        est_per_item=1,
    ),
    "market_tide_sentiment": HealSpec(
        "market_tide_sentiment",
        "db",
        "run_once_lookback",
        _run_sentiment,
        est_per_item=0,
    ),
    "macro_fred": HealSpec(
        "macro_fred", "external", "run_once_lookback", _run_macro_fred, est_per_item=0
    ),
    "rates_fred": HealSpec(
        "rates_fred", "external", "run_once_lookback", _run_rates_fred, est_per_item=0
    ),
    "gold_posture": HealSpec(
        "gold_posture", "db", "run_once", _run_gold_posture, est_per_item=0
    ),
    "gold_comex": HealSpec(
        "gold_comex", "external", "run_once", _run_gold_comex, est_per_item=0
    ),
    "gold_cot": HealSpec(
        "gold_cot", "external", "run_once", _run_gold_cot, est_per_item=0
    ),
    "gold_uw_options": HealSpec(
        "gold_uw_options", "uw", "run_once", _run_gold_uw_options, est_per_item=50
    ),
}


def run_refresh_adapters(
    ctx: HealContext,
    datasets: list[str],
    *,
    lookback_days: int,
    specs: dict[str, HealSpec] | None = None,
) -> dict[str, str]:
    """Heal re-runnable (run_once/run_once_lookback) datasets by invoking their
    ingest job directly, independent of gap items. Used by the nightly scheduler
    for macro/FRED/rates/gold + DB-to-DB rollups (freshness_only-but-healable).

    Returns {dataset: 'refreshed'|'skipped_budget'|'failed'|'no_adapter'}.
    """
    specs = specs if specs is not None else HEAL_SPECS
    out: dict[str, str] = {}
    for dataset in datasets:
        entry = ctx.registry_by_table.get(dataset)
        spec = (
            specs.get(entry.healer_adapter) if entry and entry.healer_adapter else None
        )
        if spec is None or spec.granularity not in ("run_once", "run_once_lookback"):
            out[dataset] = "no_adapter"
            continue
        if not ctx.budget.can_spend(spec.provider, spec.est_per_item):
            out[dataset] = "skipped_budget"
            continue
        try:
            if spec.granularity == "run_once_lookback":
                spec.run(ctx, lookback_days)
            else:
                spec.run(ctx)
            ctx.budget.record(spec.provider, spec.est_per_item)
            out[dataset] = "refreshed"
        except Exception as exc:  # noqa: BLE001
            logger.exception("refresh failed %s: %s", dataset, repr(exc))
            out[dataset] = "failed"
    return out


# --- generic verifier ------------------------------------------------------


def _verify_covered(
    ctx: HealContext, entry: DatasetRegistryEntry, ticker: str | None, data_date: date
) -> bool:
    table = entry.table_name
    date_col = entry.date_col or _detect_col(
        ctx.repo.conn, ctx.schema, table, _DATE_COL_PREFERENCE
    )
    if date_col is None:
        return False
    tcol = None
    if ticker:
        tcol = entry.ticker_col or _detect_col(
            ctx.repo.conn, ctx.schema, table, _TICKER_COL_PREFERENCE
        )
    parts = [
        psql.SQL("SELECT 1 FROM {tbl} WHERE {dcol} = %s").format(
            tbl=psql.Identifier(ctx.schema, table),
            dcol=psql.Identifier(date_col),
        )
    ]
    args: list[object] = [data_date]
    if tcol and ticker:
        parts.append(
            psql.SQL("AND UPPER({tcol}) = %s").format(tcol=psql.Identifier(tcol))
        )
        args.append(ticker.upper())
    parts.append(psql.SQL("LIMIT 1"))
    query = psql.SQL(" ").join(parts)
    with ctx.repo.conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchone() is not None


# --- executor --------------------------------------------------------------


def _dispatch_per_ticker_date(ctx, entry, spec, items, outcome) -> None:
    exhausted = False
    for it in items:
        if exhausted or not ctx.budget.can_spend(spec.provider, spec.est_per_item):
            ctx.gap.mark_item_skipped_budget(it["id"])
            outcome["skipped_budget"] += 1
            exhausted = True
            continue
        try:
            spec.run(ctx, it["ticker"], it["data_date"])
            ctx.budget.record(spec.provider, spec.est_per_item)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "heal failed %s %s: %s", entry.table_name, it["scope_key"], repr(exc)
            )
            ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
            outcome["failed"] += 1
            continue
        _verify_and_mark(ctx, entry, spec, it, outcome)


def _dispatch_per_ticker_range(ctx, entry, spec, items, outcome) -> None:
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_ticker[it["ticker"]].append(it)
    for ticker, tk_items in by_ticker.items():
        dates = [it["data_date"] for it in tk_items if it["data_date"]]
        if not dates or not ctx.budget.can_spend(spec.provider, spec.est_per_item):
            for it in tk_items:
                ctx.gap.mark_item_skipped_budget(it["id"])
                outcome["skipped_budget"] += 1
            continue
        try:
            spec.run(ctx, ticker, min(dates), max(dates))
            ctx.budget.record(spec.provider, spec.est_per_item)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "heal failed %s %s: %s", entry.table_name, ticker, repr(exc)
            )
            for it in tk_items:
                ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
                outcome["failed"] += 1
            continue
        for it in tk_items:
            _verify_and_mark(ctx, entry, spec, it, outcome)


def _dispatch_run_once(ctx, entry, spec, items, outcome) -> None:
    dates = [it["data_date"] for it in items if it["data_date"]]
    try:
        if spec.granularity == "run_once_lookback":
            lookback = max(1, (ctx.today - min(dates)).days + 2) if dates else 45
            spec.run(ctx, lookback)
        else:
            spec.run(ctx)
        ctx.budget.record(spec.provider, spec.est_per_item)
    except Exception as exc:  # noqa: BLE001
        logger.exception("heal failed %s (run_once): %s", entry.table_name, repr(exc))
        for it in items:
            ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
            outcome["failed"] += 1
        return
    for it in items:
        _verify_and_mark(ctx, entry, spec, it, outcome, no_data_reason="not_recomputed")


def _verify_and_mark(
    ctx, entry, spec, it, outcome, *, no_data_reason: str = "provider_no_data"
) -> None:
    if _verify_covered(ctx, entry, it["ticker"], it["data_date"]):
        ctx.gap.mark_item_healed(it["id"], actual_requests=spec.est_per_item)
        outcome["healed"] += 1
    else:
        ctx.gap.mark_item_no_data(
            it["id"], reason=no_data_reason, actual_requests=spec.est_per_item
        )
        outcome["no_data"] += 1
        # Only `provider_no_data` qualifies — NEVER no_adapter /
        # unsupported_granularity / not_recomputed, which are OUR bugs, not the
        # provider's answer. Caveating those would hide exactly the class of
        # silent no-op this plan exists to surface.
        after = getattr(ctx.settings, "data_gap_healer_no_data_caveat_after", 0)
        if after and no_data_reason == "provider_no_data" and it["data_date"]:
            prior = ctx.gap.count_recent_no_data(
                entry.table_name, it["ticker"], it["data_date"], runs=after
            )
            if prior >= after:
                ctx.gap.upsert_caveat(
                    Caveat(
                        dataset=entry.table_name,
                        ticker=it["ticker"],
                        start_date=it["data_date"],
                        end_date=it["data_date"],
                        reason=f"provider returned no data {prior}x consecutively",
                        source="auto",
                    )
                )
                outcome["auto_caveated"] += 1


_DISPATCH = {
    "per_ticker_date": _dispatch_per_ticker_date,
    "per_ticker_range": _dispatch_per_ticker_range,
    "run_once": _dispatch_run_once,
    "run_once_lookback": _dispatch_run_once,
}


def execute_run(
    ctx: HealContext,
    run_id: int,
    *,
    datasets: list[str] | None = None,
    max_items: int | None = None,
    specs: dict[str, HealSpec] | None = None,
) -> dict[str, int]:
    """Claim resumable items for a run and heal them. Returns an outcome counter.

    Items the healer cannot map to an adapter, or whose provider verify still
    fails, are recorded (no_data) rather than silently dropped.
    """
    specs = specs if specs is not None else HEAL_SPECS
    claimed = ctx.gap.claim_next_items(
        run_id,
        limit=max_items if max_items is not None else 10_000_000,
        datasets=datasets,
    )
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in claimed:
        groups[it["dataset"]].append(it)

    outcome: Counter[str] = Counter()
    for dataset, items in groups.items():
        # Reset the per-dataset slice BEFORE the entry/spec lookups, so a
        # dataset that falls through to no_data still gets its own budget.
        ctx.budget.begin_dataset(dataset)
        entry = ctx.registry_by_table.get(dataset)
        spec = (
            specs.get(entry.healer_adapter) if entry and entry.healer_adapter else None
        )
        if entry is None or spec is None:
            for it in items:
                ctx.gap.mark_item_no_data(it["id"], reason="no_adapter")
                outcome["no_data"] += 1
            continue
        dispatcher = _DISPATCH.get(spec.granularity)
        if dispatcher is None:
            for it in items:
                ctx.gap.mark_item_no_data(it["id"], reason="unsupported_granularity")
                outcome["no_data"] += 1
            continue
        dispatcher(ctx, entry, spec, items, outcome)
    return dict(outcome)
