# Own-history valuation — does cheapness time a name against itself?

*REGENERATED on every run · numbers come from `valuation_timeseries.json`*

```bash
uv run python scripts/research/fundamental_valuation_timeseries.py
```

247 tickers scored of 257 loaded · 17005 observations · z-scores expanding, 12-quarter warmup.

Every signal is a **yield**, so high = cheap and the anchor band's
`buy_below` needs a **positive** IC. Lead with the `_dm` (de-marketed)
columns — the raw ones share a macro driver and their t-stats are inflated.

| signal | maps to | 2q IC (dm) | t | holding reversal | t | tickers |
|---|---|---:|---:|---:|---:|---:|
| `fcf_yield` | platform_scale — FCF multiple | 0.0457 | 3.643 | 0.0514 | 4.179 | 247 |
| `earnings_yield` | generic P/E anchor; measured INVERTED cross-sectionally | 0.0329 | 2.56 | 0.0407 | 3.378 | 247 |
| `book_to_price` | generic book anchor; measured INVERTED cross-sectionally | 0.0356 | 2.828 | 0.0551 | 4.947 | 247 |
| `sales_to_ev` | chips_cyclical / software_growth / high_risk_growth — EV/Sales | 0.0744 | 5.773 | 0.0826 | 7.28 | 246 |
| `ebitda_to_ev` | power_infra — EV/EBITDA | 0.0446 | 3.41 | 0.0566 | 4.802 | 246 |
| **`neg_past_ret`** | **the control — pure trailing return, negated, no fundamental input** | **0.0353** | **2.598** | — | — | 247 |

The last row is the whole test. Each valuation signal is
fundamental/price with a numerator that moves quarterly and a denominator
that moves daily, so a falling price alone makes a name read cheap. If the
control earns what the signals earn, these are reversal wearing a
fundamental label; the `holding reversal` column is what is left of each
signal once that is held constant.

## Raw (macro-confounded, directional only)

| signal | 2q IC | t | 2q drawdown IC | t |
|---|---:|---:|---:|---:|
| `fcf_yield` | 0.0665 | 5.063 | 0.0693 | 5.766 |
| `earnings_yield` | 0.0297 | 2.247 | 0.0418 | 3.539 |
| `book_to_price` | 0.1087 | 7.902 | 0.0352 | 2.815 |
| `sales_to_ev` | 0.0852 | 6.29 | 0.0529 | 4.37 |
| `ebitda_to_ev` | 0.0408 | 3.008 | 0.0564 | 4.738 |
