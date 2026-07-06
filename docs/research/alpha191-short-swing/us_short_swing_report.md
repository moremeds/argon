# US Short-Swing Factor Scan

Checked at: `2026-07-02T04:21:26.840130+00:00`

Reproduce:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python /Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/scripts/research/us_short_swing_factor_scan.py --start-date 2023-01-01 --end-date 2026-07-02
```

## Scope

- Universe: active Argon watchlist, `103` tickers.
- OHLCV source: Apex REST `/bars/{ticker}?timeframe=1d` primary; `daily_ohlc` fallback for holes.
- OHLCV matrix: `102` tickers x `876` daily rows.
- Date range loaded: `2023-01-03` to `2026-07-01`.
- Evaluation window: last `252` rows from `2025-07-01`.
- Forward horizons: 3d and 5d close-to-close returns.

## Important Caveats

- This is **US-stock-native**, not a copied Alpha191 implementation.
- Alpha191 is used only as idea inspiration: short-horizon price/volume interaction, range location, reversal, breakout, volatility compression, and slope.
- Apex daily bars currently report null VWAP on tested names, so VWAP-style factors use typical price `(O+H+L+C)/4`.
- Candidate ranking is for short-day swing candidates where options can express leverage. It is not a trade instruction; option structure still needs chain liquidity, spread, IV, event, and risk checks.

## Selected Factor Stack

| factor | idea_family | ic3_mean | ic3_t | ic3_hit | ic5_mean | ic5_t | dates3 | coverage_latest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| slope_acceleration | trend_shape | -0.0412 | -2.5288 | 0.4337 | -0.0561 | -3.6416 | 249 | 102 |
| mom_10 | short_momentum | 0.0312 | 2.1695 | 0.5863 | 0.0356 | 2.5022 | 249 | 102 |
| slope_12 | trend_shape | 0.0237 | 1.6497 | 0.5783 | 0.0337 | 2.2830 | 249 | 102 |
| gap_follow | gap | 0.0260 | 1.5754 | 0.5502 | 0.0258 | 1.5329 | 249 | 102 |
| gap_fade | gap | -0.0285 | -1.6736 | 0.4618 | -0.0263 | -1.5080 | 249 | 102 |
| dollar_volume_rank | liquidity | -0.0224 | -2.6370 | 0.4378 | -0.0337 | -3.9870 | 249 | 102 |
| open_vs_vwap_snapback | typical_price_displacement | -0.0202 | -1.3203 | 0.4659 | -0.0231 | -1.5883 | 249 | 102 |
| accumulation_pressure_6 | range_location | 0.0104 | 0.8990 | 0.5663 | 0.0180 | 1.5247 | 249 | 102 |
| pv_corr_fade_6 | price_volume_interaction | 0.0201 | 2.0020 | 0.5221 | 0.0066 | 0.6662 | 249 | 102 |
| slope_6 | trend_shape | 0.0125 | 0.8140 | 0.5221 | 0.0184 | 1.2384 | 249 | 102 |

## 5 Candidate Shortlist

| ticker | sector | alpha_direction | option_leverage_score | alpha_composite | alignment_count | setup_direction | setup_score | iv_rank | liquidity_rank | scanner_score | direction | bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PANW | SaaS | long | 71.8592 | 0.5387 | 2.0000 | bull | 1.7755 | 54.7900 | 0.3922 | 6.5040 | long | bullish |
| WDC | Memory | short | 57.2124 | -0.2730 | 2.0000 | bear | 1.8253 | 97.6700 | 0.8137 | 6.5940 | short | bearish |
| ORCL | NeoCloud | short | 56.1951 | -0.6895 | 0.0000 | bull | 1.6431 | 46.2500 | 0.7353 |  |  |  |
| NBIS | NeoCloud | short | 52.3509 | -0.4203 | 1.0000 |  |  | 100.0000 | 0.7157 | 6.7060 | short | bearish |
| META | M7 | long | 51.4219 | 0.1752 | 2.0000 | bull | 2.4059 | 85.5800 | 0.8529 | 6.5740 | long | bullish |

## Output Files

- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_factor_eval.csv`
- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_ranked.csv`
- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_shortlist.csv`
