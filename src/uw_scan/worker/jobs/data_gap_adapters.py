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

from uw_scan.reports.data_gap_healer import (
    _DATE_COL_PREFERENCE,
    _TICKER_COL_PREFERENCE,
    REGISTRY,
    DatasetRegistryEntry,
    _detect_col,
)

logger = logging.getLogger(__name__)

_BUCKETS = ("uw", "massive", "external", "db")


class RequestBudget:
    """Per-provider spend tracker. Only UW is capped; the rest are unbounded."""

    def __init__(self, uw_cap: int | None) -> None:
        self.uw_cap = uw_cap
        self.spent: dict[str, int] = {b: 0 for b in _BUCKETS}

    def can_spend(self, provider: str, n: int) -> bool:
        if provider == "uw" and self.uw_cap is not None:
            return self.spent["uw"] + n <= self.uw_cap
        return True

    def record(self, provider: str, n: int) -> None:
        if provider in self.spent:
            self.spent[provider] += n

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


def _run_greek_exposure(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.greek_exposure_daily_refresh import (
        greek_exposure_daily_refresh,
    )

    # UW aggregate is current-snapshot only -> heals a same-day gap; a past date
    # verifies false and is recorded no_data (provider_no_history).
    client = ctx.uw_client()
    greek_exposure_daily_refresh(
        repo=ctx.repo,
        client=client,
        settings=ctx.settings,
        ticker_filter=lambda t: t.upper() == ticker.upper(),
    )
    return 0


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


HEAL_SPECS: dict[str, HealSpec] = {
    "option_surface": HealSpec(
        "option_surface", "uw", "per_ticker_date", _run_option_surface, est_per_item=20
    ),
    "daily_ohlc": HealSpec(
        "daily_ohlc", "massive", "per_ticker_range", _run_daily_ohlc, est_per_item=1
    ),
    "greek_exposure_daily": HealSpec(
        "greek_exposure_daily",
        "uw",
        "per_ticker_date",
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
