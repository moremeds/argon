# Cockpit Phase 0 — Skew Sanity Check

**Verdict: Fix-then-proceed.**

The persisted UW `risk_reversal_skew_history` rows show the opposite direction from the previous `00-overview.md` §0.1 mapping. Positive 25-delta skew z-scores clustered in the 2026 Q1 risk-off window, so the Cockpit deriver should treat positive skew z as `vol_up` and negative skew z as `vol_down`.

## Procedure

Ran:

```bash
uv run --with matplotlib python scripts/notebooks/cockpit_skew_sanity.py \
  --env-file /Users/chenxi/projects/unusual-whales/.env
```

Outputs:

- `/tmp/cockpit_skew_distribution.png`
- `/tmp/cockpit_skew_timeseries.png`
- `/tmp/cockpit_skew_scored.csv`
- `/tmp/cockpit_skew_summary.csv`

The script uses the longest-covered 25Δ expiry per ticker, computes a rolling 180-row z-score, and marks whether a row has the full strict 180 observations. SPX has strict 180-row coverage; SPY/QQQ/IWM are provisional because the persisted series are shorter than 180 rows.

## Summary

| Ticker | Expiry used | Rows | Strict 180d rows | Latest z | Extreme negative days | Extreme positive days |
|---|---:|---:|---:|---:|---:|---:|
| IWM | 2026-05-15 | 165 | 0 | -0.812 | 0 | 55 |
| QQQ | 2026-05-15 | 151 | 0 | -1.916 | 3 | 57 |
| SPX | 2026-05-15 | 252 | 73 | -3.996 | 87 | 43 |
| SPY | 2026-05-29 | 118 | 0 | -1.834 | 11 | 31 |

During the overlaid 2026 Q1 risk-off window (`2026-02-20` to `2026-04-08`), skew z-scores were strongly positive:

| Ticker | Rows in window | Min z | Mean z |
|---|---:|---:|---:|
| IWM | 33 | 1.461 | 2.517 |
| QQQ | 33 | 1.070 | 2.212 |
| SPX | 33 | 0.006 | 2.424 |
| SPY | 33 | 0.567 | 1.930 |

SPX is the strongest evidence because it has full strict 180-row z-score history. The ETF tickers support the same sign direction, but their z-scores are provisional until enough rows accumulate for strict 180-row windows.

## Change Made

Updated `docs/research/six-dimension-matrix/00-overview.md` §0.1:

- Before: `skew_25d_zscore_180d > +1.0` → `vol_down`; `< -1.0` → `vol_up`
- After: `skew_25d_zscore_180d > +1.0` → `vol_up`; `< -1.0` → `vol_down`

The 5-day change mapping was flipped consistently:

- Before: positive 5-day change = smirk relaxing; negative 5-day change = accelerated steepening
- After: negative 5-day change = smirk relaxing; positive 5-day change = accelerated steepening

No data migration is needed. The historical rows are raw API values; only the Phase 2 deriver interpretation changes.

## Phase 2 Implication

Proceed to Phase 2 using the corrected §0.1 skew mapping. Do not write Phase 2 tests against the old sign convention.
