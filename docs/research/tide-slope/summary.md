# Market-tide slope/sentiment — forward-return probe

- Sessions with EOD sentiment: **121** (2026-01-02 → 2026-06-26)
- Sessions with a 1d forward SPY return: **120**
- State balance: 59 BULLISH / 44 BEARISH / 17 BALANCED · baseline next-day drift +0.058%
- n = 120; significance bar on the correlation is ~0.18 (|r| below it ⇒ not distinguishable from noise).

## Mean next-day SPY return by sentiment state

| State | n | mean fwd_ret_1d | median |
|---|---|---|---|
| BALANCED | 17 | -0.0321% | +0.2723% |
| BEARISH | 44 | +0.0993% | +0.0705% |
| BULLISH | 59 | +0.0529% | +0.0440% |
| ALL (baseline) | 120 | +0.0579% | — |

## Directional skill (predict next-day sign from state)

- Trend-following hit rate: **52/103 = 50%**
- Contrarian (fade) hit rate: **51/103 = 50%**
- Trend-following, volume-confirmed only: **46/88 = 52%**
- **Control — naive price momentum** (sign of the session's own return): **61/120 = 51%**

## Slope ↔ next-day return correlation

- Pearson(session_slope, fwd_ret_1d): **0.14025578062407393**
- Spearman(session_slope, fwd_ret_1d): **0.06222654350996598**
- Pearson(signed_trend_strength, fwd_ret_1d): **-0.00669961537090395**

## How to read this

Trend-following hit rate **above** the price-momentum control **and** |corr| above the significance bar ⇒ the options-flow slope leads price with info beyond the trend. Hit rate ≈ control ≈ 50% and |corr| below the bar ⇒ descriptive only — no forecast power.

## Caveats

1. **Beats price momentum?** The control is the key confound: if the slope's hit rate ≈ the naive price-momentum control, it adds no edge beyond yesterday's price.
2. **Multiple looks.** Several cuts were tested (state buckets, contrarian, volume-confirmed, two corr flavours); no multiple-comparison correction — discount borderline results accordingly.
3. **Regime span.** Check the state balance above. A one-sided sample (all-bull or all-bear) flatters any momentum signal; a balanced sample (both states well-represented) is the fairer test.
4. **EOD close-to-close, no costs.** Signal known at close[d]; return is close[d]→close[d+1]. No slippage/fees modeled.

## Verdict

**DESCRIPTIVE — NO predictive edge.** Directional hit rate 50% ≈ coin flip and ≈ the price-momentum control (51%); correlation +0.14 is below the ~0.18 significance bar; the BULLISH/BEARISH next-day means barely separate. The slope reads CURRENT sentiment well but does NOT forecast next-day SPY return on this sample. Earlier small-n 'edges' were single-regime artifacts. Treat it as a sentiment descriptor, not a signal (cf. the VCG 'descriptive, not predictive' finding).

Reproduce: `uv run python scripts/research/tide_slope_backtest.py`
