# Chanlun Phase B — sub-level confirm probe results

Generated: 2026-07-15T11:19:52.925654+00:00
Reproduce: `uv run python scripts/research/chanlun_sublevel_probe.py`

Tickers: AAPL, NVDA, MSFT, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ (skipped/no-data: none)
Total marks traced: 12457; split-boundary exclusions: 266

1B/1S/2B/2S are recorded-but-never-promoted by design (spec §Category scope v1) — their sub-level rows below are structurally empty.

| category | slice | n_sub | resolved | censored | survival | breach | med latency | med lead |
|---|---|---|---|---|---|---|---|---|
| vertex | pooled | 3223 | 3212 | 11 | 0.129 | 0.013 | 0.000 | 8.000 |
| vertex | half_A | 1660 | 1655 | 5 | 0.129 | 0.019 | 0.000 | 8.000 |
| vertex | half_B | 1563 | 1557 | 6 | 0.128 | 0.008 | 0.000 | 8.000 |
| divergence | pooled | 491 | 490 | 1 | 0.157 | 0.016 | 0.000 | 8.000 |
| divergence | half_A | 247 | 247 | 0 | 0.142 | 0.024 | 0.000 | 8.000 |
| divergence | half_B | 244 | 243 | 1 | 0.173 | 0.008 | 0.000 | 7.000 |
| 1B | pooled | 0 | 0 | 0 | - | - | - | - |
| 1B | half_A | 0 | 0 | 0 | - | - | - | - |
| 1B | half_B | 0 | 0 | 0 | - | - | - | - |
| 1S | pooled | 0 | 0 | 0 | - | - | - | - |
| 1S | half_A | 0 | 0 | 0 | - | - | - | - |
| 1S | half_B | 0 | 0 | 0 | - | - | - | - |
| 2B | pooled | 0 | 0 | 0 | - | - | - | - |
| 2B | half_A | 0 | 0 | 0 | - | - | - | - |
| 2B | half_B | 0 | 0 | 0 | - | - | - | - |
| 2S | pooled | 0 | 0 | 0 | - | - | - | - |
| 2S | half_A | 0 | 0 | 0 | - | - | - | - |
| 2S | half_B | 0 | 0 | 0 | - | - | - | - |
| 3B | pooled | 424 | 424 | 0 | 0.085 | 0.019 | 0.000 | 8.000 |
| 3B | half_A | 225 | 225 | 0 | 0.093 | 0.031 | 0.000 | 7.000 |
| 3B | half_B | 199 | 199 | 0 | 0.075 | 0.005 | 0.000 | 9.000 |
| 3S | pooled | 232 | 231 | 1 | 0.087 | 0.000 | 0.000 | 6.500 |
| 3S | half_A | 105 | 104 | 1 | 0.096 | 0.000 | 0.000 | 6.000 |
| 3S | half_B | 127 | 127 | 0 | 0.079 | 0.000 | 0.000 | 7.500 |

## Gate verdicts (survival >= 70% AND breach <= 15% AND median latency <= 2 sessions, in BOTH ticker-halves)

- **vertex**: EXCLUDE
- **divergence**: EXCLUDE
- **3B**: EXCLUDE
- **3S**: EXCLUDE

Shipped `chanlun_promotable_categories` default from this run: ``
