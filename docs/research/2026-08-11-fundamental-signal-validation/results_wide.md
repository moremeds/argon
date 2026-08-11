# Fundamental signal validation — measured results

*2026-08-11 · REGENERATED on every run — interpretation is in `VERDICT.md` · spec §5.2, §13*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py --wide
```

> **Survivorship-selected: both the lake and UW carry live tickers only (ATVI/XLNX/TWTR/SIVB/FRC/VMW return zero rows), so these are companies that survived to 2026. No costs, capacity or shorting constraints are modelled — an IC is not a strategy.**

## Coverage

- 245 tickers with prices
- 82 usable quarters of 97 spanning 2005Q4 .. 2026Q1
- 19287 observations, 10623 with a real `filing_date` (rest lagged 45d from period end)

## Results

Rank IC of each signal against forward return, averaged across quarters. The t-stat is computed on the **quarterly IC series**, not on ticker-quarters — these names move together, so pooling would inflate it by roughly sqrt(cross-section).

### 1q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **0.0404** | **3.276** | 0.684 | 79 |
| `asset_turnover` | 0.0527 | 4.108 | 0.734 | 79 |
| `fcf_margin` | 0.0144 | 1.109 | 0.582 | 79 |
| `gross_margin` | -0.0131 | -1.241 | 0.439 | 82 |
| `neg_net_debt_ebitda` | 0.0715 | 5.286 | 0.744 | 78 |
| `op_margin` | -0.0072 | -0.733 | 0.488 | 82 |
| `rev_growth` | 0.0224 | 1.775 | 0.573 | 75 |
| `roe` | 0.0096 | 0.754 | 0.544 | 79 |

### 2q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **0.059** | **4.835** | 0.718 | 78 |
| `asset_turnover` | 0.0813 | 7.101 | 0.808 | 78 |
| `fcf_margin` | 0.0379 | 3.636 | 0.641 | 78 |
| `gross_margin` | -0.0223 | -2.016 | 0.444 | 81 |
| `neg_net_debt_ebitda` | 0.0888 | 6.212 | 0.753 | 77 |
| `op_margin` | -0.0244 | -2.556 | 0.395 | 81 |
| `rev_growth` | 0.0228 | 1.715 | 0.622 | 74 |
| `roe` | 0.0262 | 2.092 | 0.628 | 78 |
