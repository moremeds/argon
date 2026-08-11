# Fundamental signal validation — measured results

*2026-08-11 · REGENERATED on every run — interpretation is in `VERDICT.md` · spec §5.2, §13*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py
```

> **25 highly correlated AI/semi/cloud names; effective breadth is ~2-4 independent bets. A negative result is informative; a positive one is NOT evidence of tradability.**

## Coverage

- 22 tickers with prices; missing VRT, VST, NOW
- 80 usable quarters of 242 spanning 2005-12-31 .. 2025-09-30
- 874 observations, 460 with a real `filing_date` (rest lagged 45d from period end)

## Results

Rank IC of each signal against forward return, averaged across quarters. The t-stat is computed on the **quarterly IC series**, not on ticker-quarters — these names move together, so pooling would inflate it by roughly sqrt(cross-section).

### 1q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **-0.0132** | **-0.335** | 0.468 | 77 |
| `asset_turnover` | -0.1552 | -4.299 | 0.273 | 77 |
| `fcf_margin` | -0.0144 | -0.404 | 0.507 | 75 |
| `gross_margin` | 0.0011 | 0.031 | 0.475 | 80 |
| `neg_net_debt_ebitda` | 0.0384 | 0.888 | 0.589 | 56 |
| `op_margin` | -0.0725 | -2.136 | 0.388 | 80 |
| `rev_growth` | 0.0244 | 0.691 | 0.534 | 73 |
| `roe` | -0.0368 | -0.977 | 0.459 | 74 |

### 2q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **-0.0089** | **-0.206** | 0.487 | 76 |
| `asset_turnover` | -0.0862 | -2.336 | 0.342 | 76 |
| `fcf_margin` | -0.0025 | -0.063 | 0.514 | 74 |
| `gross_margin` | -0.0068 | -0.193 | 0.506 | 79 |
| `neg_net_debt_ebitda` | 0.0192 | 0.467 | 0.491 | 55 |
| `op_margin` | -0.1076 | -3.058 | 0.38 | 79 |
| `rev_growth` | 0.0423 | 1.073 | 0.597 | 72 |
| `roe` | -0.0428 | -1.182 | 0.411 | 73 |
