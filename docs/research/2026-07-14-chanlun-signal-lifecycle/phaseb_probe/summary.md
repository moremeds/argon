# Chanlun Phase B — sub-level confirm probe results

Generated: 2026-07-15T11:05:42.638288+00:00
Reproduce: `uv run python scripts/research/chanlun_sublevel_probe.py`

Tickers: AAPL, NVDA, MSFT, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ (skipped/no-data: none)
Total marks traced: 12457; split-boundary exclusions: 1734

1B/1S/2B/2S are recorded-but-never-promoted by design (spec §Category scope v1) — their sub-level rows below are structurally empty.

| category | slice | n_sub | resolved | censored | survival | breach | med latency | med lead |
|---|---|---|---|---|---|---|---|---|
| vertex | pooled | 2786 | 2775 | 11 | 0.129 | 0.014 | 0.000 | 8.000 |
| vertex | half_A | 1368 | 1363 | 5 | 0.130 | 0.021 | 0.000 | 7.000 |
| vertex | half_B | 1418 | 1412 | 6 | 0.129 | 0.008 | 0.000 | 8.000 |
| divergence | pooled | 425 | 424 | 1 | 0.151 | 0.019 | 0.000 | 7.500 |
| divergence | half_A | 197 | 197 | 0 | 0.127 | 0.030 | 0.000 | 8.000 |
| divergence | half_B | 228 | 227 | 1 | 0.172 | 0.009 | 0.000 | 7.000 |
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
| 3B | pooled | 371 | 371 | 0 | 0.084 | 0.019 | 0.000 | 7.000 |
| 3B | half_A | 188 | 188 | 0 | 0.090 | 0.032 | 0.000 | 7.000 |
| 3B | half_B | 183 | 183 | 0 | 0.077 | 0.005 | 0.000 | 9.000 |
| 3S | pooled | 203 | 202 | 1 | 0.089 | 0.000 | 0.000 | 6.500 |
| 3S | half_A | 87 | 86 | 1 | 0.105 | 0.000 | 0.000 | 6.000 |
| 3S | half_B | 116 | 116 | 0 | 0.078 | 0.000 | 0.000 | 8.000 |

## Gate verdicts (survival >= 70% AND breach <= 15% AND median latency <= 2 sessions, in BOTH ticker-halves)

- **vertex**: EXCLUDE
- **divergence**: EXCLUDE
- **3B**: EXCLUDE
- **3S**: EXCLUDE

Shipped `chanlun_promotable_categories` default from this run: ``
