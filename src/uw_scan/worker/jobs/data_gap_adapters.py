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

from uw_scan.worker.jobs.data_gap_heal_context import HealContext, HealSpec
from uw_scan.worker.jobs.data_gap_heal_runners import (
    _eventlog_heal,
    _run_canary_recover,
    _run_corporate_actions,
    _run_cri_recover,
    _run_daily_ohlc,
    _run_flow_chain_replay,
    _run_fundamental_refresh,
    _run_gex_levels,
    _run_gold_cot,
    _run_gold_lbma,
    _run_gold_posture,
    _run_gold_uw_options,
    _run_greek_exposure,
    _run_grg,
    _run_index_ohlc,
    _run_macro_fred,
    _run_market_tide,
    _run_massive_fundamentals,
    _run_option_surface,
    _run_pipeline_replay,
    _run_rates_fred,
    _run_realized_volatility,
    _run_sentiment,
    _run_short_pressure,
    _run_spx_density_reconstruct,
    _run_technical_daily,
    _run_top_net_impact,
    _run_vcg_recover,
    _run_vol_index_lake,
    _run_vol_rollup,
    _run_volatility_signal,
    _run_volatility_stats,
)
from uw_scan.worker.jobs.data_gap_telemetry import (
    STAGE_ADAPTER,
    STAGE_MARKED,
)
from uw_scan.worker.jobs.uw_alpha_capture import (
    capture_dark_lit_for,
    capture_intraday_flow_for,
)

logger = logging.getLogger(__name__)


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
        "flow_chain_replay",
        "uw",
        "per_ticker_date",
        _run_flow_chain_replay,
        est_per_item=1,
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
    # Writes origin='reconstructed' only, and never over a prospective row — the
    # selection rule that guarantees it lives with the cone, in
    # spx_density_forecast.select_sessions.
    "spx_density_reconstruct": HealSpec(
        "spx_density_reconstruct",
        "db",
        "run_once_lookback",
        _run_spx_density_reconstruct,
        est_per_item=0,
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
    "gold_lbma": HealSpec(
        "gold_lbma", "external", "run_once", _run_gold_lbma, est_per_item=0
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
        if ctx.heartbeat is not None:
            # The refresh phase runs AFTER execute_run in the nightly job, so
            # without a beat here a run that got that far and then hung would
            # leave a last-known stage that points at the wrong phase entirely.
            ctx.heartbeat.stage(
                STAGE_ADAPTER,
                dataset=dataset,
                phase="refresh",
                uw_est_spent=ctx.budget.spent.get("uw"),
            )
        try:
            if spec.granularity == "run_once_lookback":
                spec.run(ctx, lookback_days)
            else:
                spec.run(ctx)
            ctx.budget.record(spec.provider, spec.est_per_item)
            out[dataset] = "refreshed"
            if ctx.heartbeat is not None:
                ctx.heartbeat.stage(
                    STAGE_MARKED,
                    dataset=dataset,
                    phase="refresh",
                    uw_est_spent=ctx.budget.spent.get("uw"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("refresh failed %s: %s", dataset, repr(exc))
            out[dataset] = "failed"
    return out
