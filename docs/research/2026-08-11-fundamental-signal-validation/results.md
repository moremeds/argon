# Fundamental signal validation — measured results

*2026-08-11 · REGENERATED on every run — interpretation is in `VERDICT.md` · spec §5.2, §13*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py
```

> **25 highly correlated AI/semi/cloud names; effective breadth is ~2-4 independent bets. Detection floor |IC| ~0.072 against a realistic factor of 0.02-0.05, so this run is underpowered by construction and cannot support any conclusion about the composite.**

## Coverage

- 22 tickers with prices; missing VRT, VST, NOW
- 80 usable quarters of 81 spanning 2006Q1 .. 2025Q4
- 1414 observations, 573 with a real `filing_date` (rest lagged 45d from period end)

## Results

Rank IC of each signal against forward return, averaged across quarters. The t-stat is computed on the **quarterly IC series**, not on ticker-quarters — these names move together, so pooling would inflate it by roughly sqrt(cross-section).

### 1q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **-0.0077** | **-0.228** | 0.455 | 77 |
| `asset_turnover` | -0.0143 | -0.486 | 0.481 | 77 |
| `fcf_margin` | -0.0301 | -1.058 | 0.455 | 77 |
| `gross_margin` | -0.0177 | -0.62 | 0.4 | 80 |
| `neg_net_debt_ebitda` | 0.0612 | 1.899 | 0.532 | 77 |
| `op_margin` | -0.0492 | -1.709 | 0.375 | 80 |
| `rev_growth` | -0.0008 | -0.024 | 0.548 | 73 |
| `roe` | -0.0188 | -0.614 | 0.494 | 77 |

### 2q forward return

| Signal | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| **composite** | **0.0238** | **0.679** | 0.519 | 77 |
| `asset_turnover` | 0.0339 | 1.096 | 0.532 | 77 |
| `fcf_margin` | -0.0117 | -0.372 | 0.519 | 77 |
| `gross_margin` | -0.0107 | -0.386 | 0.425 | 80 |
| `neg_net_debt_ebitda` | 0.0734 | 2.241 | 0.605 | 76 |
| `op_margin` | -0.0296 | -1.064 | 0.45 | 80 |
| `rev_growth` | 0.0293 | 0.901 | 0.603 | 73 |
| `roe` | 0.0048 | 0.147 | 0.468 | 77 |
