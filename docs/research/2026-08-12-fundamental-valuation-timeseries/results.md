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
| `fcf_yield` | platform_scale — FCF multiple | na | na | na | na | na |
| `earnings_yield` | generic P/E anchor; measured INVERTED cross-sectionally | na | na | na | na | na |
| `book_to_price` | generic book anchor; measured INVERTED cross-sectionally | na | na | na | na | na |
| `sales_to_ev` | chips_cyclical / software_growth / high_risk_growth — EV/Sales | na | na | na | na | na |
| `ebitda_to_ev` | power_infra — EV/EBITDA | na | na | na | na | na |
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
| `fcf_yield` | na | na | na | na |
| `earnings_yield` | na | na | na | na |
| `book_to_price` | na | na | na | na |
| `sales_to_ev` | na | na | na | na |
| `ebitda_to_ev` | na | na | na | na |
