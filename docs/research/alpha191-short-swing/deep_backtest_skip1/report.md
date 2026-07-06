# Alpha191 deep backtest — S&P 500 + Nasdaq-100 single names

Universe: 510 names · history 1995-01-03..2026-07-02
· backtest from 1997-01-01 · quintile=0.2 · cost=10.0bps/unit-turnover.

## Headline (full-sample, sorted by Sharpe)

| config | cagr | ann_vol | sharpe | sortino | max_drawdown | period_hit_rate | days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| buyhold_eqw | 0.1512 | 0.1972 | 0.813 | 1.047 | -0.5133 |  | 7422 |
| reversal_5_5d | 0.0411 | 0.091 | 0.487 | 0.742 | -0.2307 | 0.463 | 7422 |
| reversal_5_10d | 0.035 | 0.0899 | 0.427 | 0.66 | -0.3004 | 0.496 | 7422 |
| reversal_10_10d | 0.019 | 0.09 | 0.254 | 0.392 | -0.3517 | 0.488 | 7422 |
| reversal_10_15d | 0.0145 | 0.0891 | 0.206 | 0.296 | -0.2998 | 0.478 | 7422 |
| lt_mom_12_1_21d | -0.0324 | 0.1037 | -0.265 | -0.279 | -0.7463 | 0.516 | 7422 |
| fade_5d | -0.0355 | 0.0845 | -0.384 | -0.432 | -0.6992 | 0.45 | 7422 |
| fade_10d | -0.0366 | 0.0837 | -0.402 | -0.456 | -0.7076 | 0.439 | 7422 |
| fade_15d | -0.0407 | 0.0838 | -0.453 | -0.481 | -0.7776 | 0.431 | 7422 |
| lt_mom_3_21d | -0.0457 | 0.0921 | -0.462 | -0.534 | -0.7861 | 0.448 | 7422 |
| lt_mom_6_21d | -0.052 | 0.1031 | -0.465 | -0.49 | -0.8224 | 0.476 | 7422 |
| momentum_15d | -0.0481 | 0.0866 | -0.525 | -0.576 | -0.8063 | 0.421 | 7422 |
| baseline_mom10_10d | -0.0643 | 0.09 | -0.693 | -0.753 | -0.8897 | 0.395 | 7422 |
| momentum_10d | -0.064 | 0.0875 | -0.711 | -0.765 | -0.8915 | 0.4 | 7422 |
| momentum_5d | -0.0937 | 0.0878 | -1.076 | -1.156 | -0.9513 | 0.384 | 7422 |

## Caveats
- **Survivorship-biased**: today's SP500+NDX100 tested on old data; delisted losers absent. Deep numbers overstate. (Fix later via index_membership_changes.csv.)
- Underlying-return only; no options PnL, no earnings/event filter.
- Dollar-neutral L/S -> Sharpe is selection skill, not market beta (cf. buyhold_eqw).
- vwap proxy = typical price on daily bars.

Files: equity_curves.csv, metrics_summary.csv, per_year.csv, rebalance_log.csv

Reproduce: `uv run python scripts/research/alpha191_deep_backtest.py --universe-dir docs/research/alpha191-short-swing/universe --out docs/research/alpha191-short-swing/deep_backtest_skip1`
