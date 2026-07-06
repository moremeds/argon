# Backtesting Plan: US Short-Dated Swing Strategies

Checked at: `2026-07-02`

Goal: validate whether `trend_exhaustion_fade_1w` and
`momentum_continuation_2w` are strong enough to become Argon strategy modules for
1-3 week US stock option swings.

## Current State

Completed:

- Built a US-stock-native strategy scan using Apex daily bars and Argon
  watchlist data.
- Tested 5d, 10d, and 15d stock-return outcomes.
- Identified two promising strategies:
  - Champion: `trend_exhaustion_fade_1w`
  - Runner-up: `momentum_continuation_2w`

Not yet completed:

- No full options PnL backtest.
- No historical option-chain reconstruction.
- No earnings/event filter.
- No bid/ask spread, OI, volume, or execution model.
- No walk-forward parameter search with locked validation windows.
- No comparison to simple baselines such as pure 10d momentum, equal-weighted
  watchlist, or sector-neutral variants.

## Stage 1: Stock Alpha Validation

Purpose: confirm the stock-return edge is not a one-window artifact.

Tests:

- Run 5d, 10d, and 15d horizons.
- Test long-only, short-only, and long-short legs separately.
- Add sector-neutral ranking.
- Add liquidity buckets.
- Add volatility buckets.
- Add subperiod splits:
  - 2023 full year
  - 2024 full year
  - 2025 full year
  - 2026 year-to-date
- Add rolling monthly performance attribution.

Acceptance gate:

- Champion must keep positive mean return and hit rate above 55% in at least
  two of 5d/10d/15d.
- Runner-up must keep positive long-leg performance in 10d and 15d.
- Reject any variant that only works because of one sector or one month.

Evidence:

- CSV of all trades.
- CSV of monthly returns.
- Markdown report with summary tables.
- Reproduce command saved in the report.

## Stage 2: Event And Tradeability Filters

Purpose: remove setups that are not tradable with short-dated options.

Filters:

- Exclude earnings inside the holding window.
- Exclude known major event dates where available.
- Require minimum stock price, default `spot >= 20`.
- Require minimum dollar volume.
- Require option chain availability.
- Require option spread quality:
  - max spread percentage
  - minimum open interest
  - minimum option volume
- Add IV rank buckets:
  - low IV
  - normal IV
  - high IV
  - extreme IV

Acceptance gate:

- Strategy remains positive after excluding earnings and poor-liquidity names.
- Trade count remains large enough for evaluation.
- Edge is not concentrated only in impossible-to-fill contracts.

Evidence:

- Filtered trade log.
- Rejection reason counts.
- Before/after performance table.

## Stage 3: Options Expression Backtest

Purpose: estimate whether the stock alpha can survive option decay and spreads.

Expressions:

- `trend_exhaustion_fade_1w`
  - put debit spread, 1-3 week expiry
  - optional long put only when IV and spread are favorable
- `momentum_continuation_2w`
  - call debit spread, 2-4 week expiry
  - optional long call only when IV is favorable

Contract selection:

- Use 25-45 delta long leg where available.
- Debit spread short leg target: 10-25 delta.
- Expiry target:
  - 7-21 DTE for trend exhaustion
  - 14-35 DTE for momentum continuation
- Skip contracts with missing bid/ask or stale quote.

PnL model:

- Conservative entry at ask and exit at bid.
- Include spread cost.
- Include commission placeholder.
- Mark unresolved exits at modeled mid only as a separate optimistic column.

Acceptance gate:

- Conservative bid/ask PnL must remain positive.
- Profit factor must exceed 1.15 before considering production.
- Median loss must be bounded and compatible with defined-risk sizing.

Evidence:

- Per-contract trade log.
- Per-strategy PnL summary.
- Drawdown and loss-streak summary.

## Stage 4: Walk-Forward Robustness

Purpose: avoid overfitting.

Process:

- Train parameters on a trailing window.
- Freeze parameters.
- Test on the next month or quarter.
- Roll forward.

Parameters to test:

- Lookback windows: 6, 10, 12, 20 trading days.
- Hold horizons: 5, 10, 15 trading days.
- Top-N selection: 3, 5, 10 names.
- IV rank thresholds.
- Minimum liquidity thresholds.
- Sector-neutral vs unconstrained selection.

Acceptance gate:

- Chosen variant must not be the single best historical parameter by accident.
- Nearby parameter settings should remain acceptable.
- Performance should not collapse after transaction costs.

Evidence:

- Full parameter grid saved to CSV.
- Winner selection rule documented before final validation.
- Out-of-sample summary separated from in-sample tuning.

## Stage 5: Argon Integration Plan

Purpose: turn validated strategies into repeatable Argon screens.

Implementation shape:

- Add a strategy research module first, not a production trade recommender.
- Persist each daily strategy snapshot to Postgres.
- Persist strategy inputs, score components, selected contracts, and rejection
  reasons.
- Surface candidates in a research tab with:
  - strategy id
  - signal score
  - target horizon
  - option structure suggestion
  - avoid flags
  - evidence link

Production gate:

- Do not promote to live strategy until options PnL backtest exists.
- Do not show as trade-ready unless option chain quality and event filters pass.

## Immediate Next Step

Build Stage 1 as a faster research script:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/research/us_short_swing_strategy_backtest.py \
  --horizons 5 10 15 \
  --top-n 5 \
  --backtest-start 2023-01-01
```

Then extend it with:

- sector-neutral portfolios
- yearly splits
- monthly return tables
- benchmark comparisons

