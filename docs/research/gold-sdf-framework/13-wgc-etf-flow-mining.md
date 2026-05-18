# WGC ETF Flow Mining: Breadth, Concentration, And Post-2022 Sensitivity

Date: 2026-05-17

## Question

Now that the WGC ETF-flow corpus is persisted, should Lens 1 continue to treat
GLD as a sufficient ETF-flow proxy, or should the gold cockpit use a broader
global ETF breadth/flow composite?

Short answer: GLD is still the largest single fund, but it is no longer enough
as a standalone proxy. The global ETF market has become meaningfully less
concentrated, and Asia's share has risen sharply since 2024.

## Data

Source: `uw_scan.wgc_etf_monthly`, loaded from 78 authenticated WGC Goldhub ETF
workbooks. See [12-wgc-etf-flow-corpus.md](./12-wgc-etf-flow-corpus.md).

For this note, rows were canonicalised to the latest workbook revision per
`(ticker, obs_date)` using `source_url DESC`, then grouped monthly.

Canonical sample:

- Rows: 26,217 fund-month observations
- Months: 277
- Date range: 2003-03-31 through 2026-03-31
- Latest month fund count: 182
- Latest total gold ETF holdings: 4,087.8 tonnes

Metrics:

- `holdings_tonnes`: WGC fund-level gold holdings
- `demand_tonnes`: monthly change in tonnes when available
- `flow_usd_mn`: monthly fund flow in USD millions when available
- `gold_price_usd_oz`: WGC workbook gold price context

## Findings

### 1. GLD is still largest, but no longer dominant enough

Latest month: 2026-03-31.

| Rank | Ticker | Fund | Region | Holdings |
|---:|---|---|---|---:|
| 1 | GLD | SPDR Gold Shares | North America | 1,046.9 tonnes |
| 2 | IAU | iShares Gold Trust | North America | 476.0 tonnes |
| 3 | IGLN LN EQUITY | iShares Physical Gold ETC | Europe | 247.1 tonnes |
| 4 | GLDM | SPDR Gold MiniShares Trust | North America | 199.9 tonnes |
| 5 | SGLD LN EQUITY | Invesco Physical Gold ETC | Europe | 198.6 tonnes |
| 6 | 4GLD GR EQUITY | Xetra-Gold | Europe | 170.2 tonnes |
| 7 | PHYS | Sprott Physical Gold Trust | North America | 114.7 tonnes |
| 8 | 518880 CH EQUITY | Huaan Yifu Gold ETF | Asia | 111.2 tonnes |
| 9 | GOLD FP EQUITY | Amundi Physical Gold ETC | Europe | 83.5 tonnes |
| 10 | 1540 JT EQUITY | Japan Physical Gold ETF | Asia | 72.4 tonnes |

GLD share of total WGC gold ETF holdings:

- Pre-2022 average: 48.1%
- Post-2022 average: 26.2%
- Latest: 25.6%

Top-5 concentration:

- Pre-2022 average: 76.3%
- Post-2022 average: 57.1%
- Latest: 53.0%

Interpretation: GLD remains the biggest single signal, but the ETF universe has
spread out. A GLD-only proxy now misses too much regional and issuer breadth.

### 2. Asia has become a real share of the ETF holdings base

Selected year-end snapshots:

| Year | Total Holdings | GLD Share | Top-5 Share | North America | Europe | Asia |
|---:|---:|---:|---:|---:|---:|---:|
| 2008 | 1,222.9t | 63.8% | 91.6% | 71.1% | 24.9% | 0.5% |
| 2011 | 2,530.1t | 49.6% | 71.0% | 62.3% | 33.5% | 2.0% |
| 2016 | 2,199.9t | 37.4% | 62.4% | 52.2% | 41.5% | 4.2% |
| 2020 | 4,017.3t | 29.1% | 59.6% | 49.9% | 45.5% | 3.1% |
| 2022 | 3,723.5t | 24.6% | 56.0% | 46.4% | 48.3% | 3.6% |
| 2024 | 3,224.2t | 27.1% | 56.7% | 51.2% | 39.9% | 6.9% |
| 2025 | 4,025.8t | 26.6% | 54.5% | 52.0% | 35.3% | 10.9% |
| 2026 | 4,087.8t | 25.6% | 53.0% | 50.9% | 34.5% | 12.8% |

Latest month regional holdings:

- North America: 2,079.4 tonnes
- Europe: 1,411.8 tonnes
- Asia: 521.6 tonnes
- Other: 74.9 tonnes

Asia is still smaller than North America and Europe, but it is no longer a
rounding error. The 2025-2026 rise is large enough that Lens 1 should track it
explicitly.

### 3. Latest month was Western outflow, Asian inflow

Latest month demand, 2026-03-31:

- North America: -87.0 tonnes
- Europe: -7.3 tonnes
- Asia: +9.9 tonnes
- Other: -0.4 tonnes
- Global total: -84.8 tonnes

Trailing 12-month regional demand into 2026-03-31:

- North America: +195.1 tonnes
- Asia: +171.2 tonnes
- Europe: +39.2 tonnes
- Other: +5.8 tonnes

Interpretation: the latest month was a Western de-risking/outflow month, but
the 12-month picture shows Asia as a major net accumulator alongside North
America.

### 4. Flow-price sensitivity is stronger post-2022, not weaker

Correlation of global monthly ETF demand with same-month gold return:

- Full sample: +0.43
- Pre-2022: +0.40
- Post-2022: +0.56

Correlation of global monthly USD flow with same-month gold return:

- Full sample: +0.42
- Pre-2022: +0.36
- Post-2022: +0.60

Regional demand correlations with same-month gold return:

- North America: +0.44
- Europe: +0.23
- Asia: +0.22
- Other: +0.23

Interpretation: ETF flows remain price-sensitive, especially in North America.
This does not prove ETF flows drive gold price; same-month correlation can also
reflect momentum chasing, allocation response, or shared macro drivers.

### 5. Breadth has softened slightly post-2022

Monthly positive-demand breadth is:

`positive-demand funds / funds with demand data`

- Pre-2022 average breadth: 52.2%
- Post-2022 average breadth: 48.8%

This is not a dramatic break, but it argues for using breadth as a stabiliser:
when gold rises on narrow GLD-only flow, Lens 1 should treat that differently
from a month where the majority of global products are accumulating metal.

### 6. Extreme ETF-flow months align with obvious stress/momentum regimes

Largest monthly global ETF demand:

| Month | Demand | Gold Return |
|---|---:|---:|
| 2022-03-31 | +230.9t | +4.9% |
| 2016-02-29 | +210.9t | +9.5% |
| 2020-04-30 | +192.6t | +5.7% |
| 2020-07-31 | +181.4t | +6.4% |
| 2020-03-31 | +179.9t | -0.3% |

Largest monthly global ETF outflow:

| Month | Demand | Gold Return |
|---|---:|---:|
| 2013-04-30 | -179.6t | -6.5% |
| 2013-05-31 | -148.2t | -5.1% |
| 2020-11-30 | -127.1t | -1.9% |
| 2021-03-31 | -119.9t | -5.0% |
| 2013-02-28 | -118.9t | -2.6% |

This supports using ETF flow as a structural/momentum thermometer, not as a
standalone directional forecast.

## Product Implication

Lens 1 should graduate from `gld_30d_net_flow_t` alone to a broader WGC-backed
ETF flow composite:

1. `global_etf_demand_1m_t`
2. `global_etf_demand_3m_t`
3. `regional_etf_demand_3m_t`: North America / Europe / Asia / Other
4. `etf_positive_breadth_pct`
5. `gld_share_of_global_etf_holdings_pct`
6. `top5_etf_concentration_pct`

GLD remains useful as the daily, high-frequency proxy. WGC should become the
monthly breadth and global-composition anchor.

## Proposed Lens 1 Use

Use two layers:

- Daily layer: SPDR GLD holdings and UW in/outflow for near-term movement.
- Monthly layer: WGC global/regional/breadth composite for structural context.

Example posture language:

- "ETF flow broadening: Asia and North America both positive over 3 months."
- "ETF flow narrow: GLD inflow positive, global breadth below median."
- "ETF distribution risk: Western ETF outflows partly offset by Asian inflows."

Keep this informational. Do not map it to sizing until Q14/Q23 validation is
complete.

## Caveats

- This is same-month analysis, not a lead/lag test.
- WGC workbooks are snapshots and can revise history. The DB preserves source
workbook lineage, but this note uses the latest revision per `(ticker, month)`.
- Some older 2018-2021 files lack the full modern sheet set. The parser captures
available current-month rows and partial history where present.
- WGC definitions distinguish demand tonnes from USD fund flow. They should not
be treated as interchangeable.

## Next Analysis

1. Run lead/lag correlations:
   - ETF demand at `t-1` versus gold return at `t`
   - regional demand at `t-1` versus global ETF demand at `t`
2. Add real-rate and DXY controls to separate ETF momentum from macro beta.
3. Build a monthly ETF breadth factor and backtest it only as an explanatory
   lens input, not as trade sizing.
4. Compare GLD daily flow to WGC monthly global demand to calibrate when GLD is
   a good proxy and when it is misleading.
5. Explore ETF flow further as its own Lens 1 research thread:
   - identify whether flow breadth, regional rotation, or concentration changes
     add signal beyond headline global demand
   - test whether Asian ETF accumulation behaves differently from North American
     and European ETF flow in the post-2022 sample
   - define which ETF-flow metrics should become persisted cockpit fields versus
     research-only diagnostics
