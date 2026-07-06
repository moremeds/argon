# Alpha191 deep backtest — S&P 500 + Nasdaq-100 single names

Universe: 510 names · history 1995-01-03..2026-07-02
· backtest from 1997-01-01 · quintile=0.2 · cost=10.0bps/unit-turnover.

## Headline (full-sample, sorted by Sharpe)

| config | cagr | ann_vol | sharpe | sortino | max_drawdown | period_hit_rate | days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| buyhold_eqw | 0.1512 | 0.1972 | 0.813 | 1.047 | -0.5133 |  | 7422 |
| reversal_5_5d | 0.0549 | 0.093 | 0.62 | 0.946 | -0.2679 | 0.471 | 7422 |
| reversal_5_10d | 0.0423 | 0.0909 | 0.501 | 0.773 | -0.2559 | 0.495 | 7422 |
| reversal_10_10d | 0.0286 | 0.0903 | 0.356 | 0.548 | -0.2967 | 0.491 | 7422 |
| reversal_10_15d | 0.0221 | 0.0892 | 0.289 | 0.415 | -0.253 | 0.464 | 7422 |
| lt_mom_12_1_21d | -0.0306 | 0.1039 | -0.245 | -0.259 | -0.7456 | 0.524 | 7422 |
| fade_10d | -0.0336 | 0.0841 | -0.364 | -0.413 | -0.674 | 0.442 | 7422 |
| fade_5d | -0.0416 | 0.0844 | -0.46 | -0.521 | -0.7481 | 0.435 | 7422 |
| lt_mom_6_21d | -0.052 | 0.1032 | -0.465 | -0.49 | -0.8232 | 0.47 | 7422 |
| fade_15d | -0.0431 | 0.0846 | -0.477 | -0.509 | -0.7717 | 0.431 | 7422 |
| lt_mom_3_21d | -0.0475 | 0.0922 | -0.482 | -0.559 | -0.7973 | 0.433 | 7422 |
| momentum_15d | -0.0553 | 0.0866 | -0.612 | -0.674 | -0.8444 | 0.395 | 7422 |
| baseline_mom10_10d | -0.073 | 0.0902 | -0.794 | -0.867 | -0.9094 | 0.383 | 7422 |
| momentum_10d | -0.0748 | 0.0877 | -0.841 | -0.908 | -0.9164 | 0.38 | 7422 |
| momentum_5d | -0.1069 | 0.0889 | -1.226 | -1.322 | -0.9685 | 0.391 | 7422 |

## Caveats
- **Survivorship-biased**: today's SP500+NDX100 tested on old data; delisted losers absent. Deep numbers overstate. (Fix later via index_membership_changes.csv.)
- Underlying-return only; no options PnL, no earnings/event filter.
- Dollar-neutral L/S -> Sharpe is selection skill, not market beta (cf. buyhold_eqw).
- vwap proxy = typical price on daily bars.

Files: equity_curves.csv, metrics_summary.csv, per_year.csv, rebalance_log.csv

Reproduce: `uv run python scripts/research/alpha191_deep_backtest.py --universe-dir docs/research/alpha191-short-swing/universe --out docs/research/alpha191-short-swing/deep_backtest`
