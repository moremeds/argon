# Unusual Whales API — Standard-Tier Reference

**Base URL:** `https://api.unusualwhales.com`  
**Auth:** `Authorization: Bearer {UW_TOKEN}`  
**Rate-limit headers on every response** (including 403/422):

| Header | Meaning |
|--------|---------|
| `x-uw-token-req-limit` | Daily request budget for this token |
| `x-uw-daily-req-count` | Cumulative requests used today |
| `x-uw-req-per-minute-remaining` | Requests left in the current 60-second window |
| `x-uw-minute-req-counter` | Requests used in the current window |
| `x-uw-req-per-minute-reset` | Milliseconds until the per-minute counter resets |

**Historical lookback:** 30 trading days on date-selector endpoints. Date parameters earlier than that return `403`. Timestamp-cursor endpoints (`newer_than`/`older_than`) have shallower effective depth (see Backfill section).

**Gated endpoints** (Advanced+ / Premium / Enterprise) are documented separately in `unusual_whales_advanced_tier.md`. Do not add fetchers for them without upgrading first — probes return 403/422 and consume budget.

---

## Audit baseline

Live-probed 2026-05-15 against the official OpenAPI spec (`/api/openapi`, 177 operations):

| Category | Count |
|----------|-------|
| Accessible (200) | **140** |
| Gated (403 or 422) | 36 |
| Sample-invalid | 1 |
| **Integrated in argon** | **30** |
| Accessible but not yet integrated | ~110 |

Machine-readable evidence: `uw_api_capability_audit.json` / `uw_api_capability_audit.md`.

---

## Integrated Endpoints

Endpoints with a slug in `api/endpoints.py` and a fetcher in `sources/uw.py`.

### Options Flow

| Slug | Path | Purpose |
|------|------|---------|
| `FLOW_ALERTS` | `GET /api/option-trades/flow-alerts` | Sweep/block/unusual-activity alerts. Used by full-scan per-ticker (`fetch_flow_alerts`) and market-wide discovery (`fetch_market_flow_alerts`). Also drives VRP entry discovery. Cursor pagination via `newer_than`/`older_than`; max 200/call. |

Key params: `ticker_symbol`, `is_sweep`, `is_floor`, `is_call`/`is_put`, `min_premium`, `min_dte`, `all_opening`, `rule_name[]`, `limit` (max 200).  
Response gotcha: pagination keys are top-level `newer_than`/`older_than` in the envelope, not a `next_page` field.

Also accessible (no slug yet):  
- `GET /api/stock/{ticker}/flow-alerts` — ticker-scoped flow alerts (recent only, no cursor)  
- `GET /api/option-trades/flow-alerts/{id}` — single alert detail + constituent trades

---

### Volatility

| Slug | Path | Purpose |
|------|------|---------|
| `IV_RANK` | `GET /api/stock/{ticker}/iv-rank` | Daily IV rank time series (trailing ~5 rows). Use the latest `date` row for the card's current IVR. |
| `VOLATILITY_STATS` | `GET /api/stock/{ticker}/volatility/stats` | One object per market date: `iv`, `iv_high`, `iv_low`, `iv_rank`, `rv`, `rv_high`, `rv_low`. Used in VRP macro signal and vol card. |
| `REALIZED_VOLATILITY` | `GET /api/stock/{ticker}/volatility/realized` | ~250-row trailing series of `(date, implied_volatility, realized_volatility, price)`. Used for VRP markout. Date param anchors the returned series. |
| `TERM_STRUCTURE` | `GET /api/stock/{ticker}/volatility/term-structure` | One row per expiry up the curve, `(dte, volatility, implied_move_perc)` — all strings. Used for vol card term structure chart. |
| `INTERPOLATED_IV` | `GET /api/stock/{ticker}/interpolated-iv` | 9-row array of standard tenors (1, 7, 14, 30 … days) with `volatility` and `percentile`. Use for "IV% at 30d" readouts, not `iv-rank`. |
| `SKEW` | `GET /api/stock/{ticker}/historical-risk-reversal-skew` | Time series of 25Δ risk reversal for one (expiry, delta). Both `expiry` + `delta` required. Used by skew engine. |

---

### Greek Exposure (GEX / DEX / Vanna / Charm)

| Slug | Path | Purpose |
|------|------|---------|
| `GREEK_EXPOSURE` | `GET /api/stock/{ticker}/greek-exposure/strike-expiry` | Per-(strike, expiry) GEX/DEX/vanna/charm. `expiry` required. Used for cockpit GEX surface. |
| `GREEK_EXPOSURE_BY_STRIKE` | `GET /api/stock/{ticker}/greek-exposure/strike` | Aggregated per-strike across all expiries. Used for scanner single-name GEX. |
| `GREEK_EXPOSURE_BY_EXPIRY` | `GET /api/stock/{ticker}/greek-exposure/expiry` | Per-expiry totals (call/put GEX, vanna, charm, delta, dte). Used for multi-expiry vanna/charm dropdown. |
| `GREEK_EXPOSURE_HISTORY` | `GET /api/stock/{ticker}/greek-exposure` | Aggregate GEX/DEX over time (default ~90 sessions; pass `timeframe=1Y` for z-score warmup). Used for net DEX trend. |
| `SPOT_EXPOSURES` | `GET /api/stock/{ticker}/spot-exposures/expiry-strike` | Per-strike, per-greek (delta/gamma/vanna/charm) with ask/bid/OI/vol variants. `expirations[]` required. Used for option surface capture. |

Three additional `spot-exposures` paths exist but have no slug:
- `GET /api/stock/{ticker}/spot-exposures` — aggregate exposure vs spot at 1% moves
- `GET /api/stock/{ticker}/spot-exposures/strike` — per-strike without expiry filter
- `GET /api/stock/{ticker}/spot-exposures/{expiry}/strike` — per-strike for one expiry

---

### Options Chain

| Slug | Path | Purpose |
|------|------|---------|
| `GREEKS` | `GET /api/stock/{ticker}/greeks` | Per-strike call+put greeks for one expiry (`expiry` required). ~188 rows for TSLA. Used for surface IV grid. |
| `OI_PER_STRIKE` | `GET /api/stock/{ticker}/oi-per-strike` | (date, strike, call_oi, put_oi) series. Used for OI chart. |
| `OI_CHANGE` | `GET /api/stock/{ticker}/oi-change` | Top 50 OI movers with `curr_oi`, `last_oi`, `oi_change`, fill/bid/ask context. Used for intraday OI movers card. |
| `MAX_PAIN` | `GET /api/stock/{ticker}/max-pain` | Per-expiry max pain with adjacent strikes and close/open. |
| `OPTION_CONTRACTS` | `GET /api/stock/{ticker}/option-contracts` | Full chain snapshot: ask/bid/mid/floor volume, IV, last price, OI. Up to 500/call unfiltered; use `expiry` param to get the full expiry uncapped (~270 rows for SPX). Used for VRP entry quotes and strike discovery. |
| `OPTION_CONTRACTS_BY_SYMBOL` | Same path with `option_symbol[]` | Exact snapshot for OCC symbols. Used for trade-plan pricing. |
| `OPTION_CONTRACT_INTRADAY` | `GET /api/option-contract/{id}/intraday` | Per-minute OHLCV + IV + ask/bid/mid/no-side volume for one contract. `date` required. Used for intraday OI bucket refresh. |

Also accessible (no slug):
- `GET /api/stock/{ticker}/option-chains` — full chain with `option_chain` key but no per-contract pricing (use `option-contracts` instead)
- `GET /api/stock/{ticker}/atm-chains` — ATM contracts for requested expiries, with IV + volume + greeks
- `GET /api/stock/{ticker}/expiry-breakdown` — per-expiry chains/volume/OI count (used directly in option surface capture job)
- `GET /api/option-contract/{id}/flow` — raw trade-level flow for one contract
- `GET /api/option-contract/{id}/volume-profile` — volume at each price level for one contract
- `GET /api/stock/{ticker}/option/stock-price-levels` — options volume at each underlying price
- `GET /api/stock/{ticker}/option/volume-oi-expiry` — volume+OI rolled up by expiry

---

### Dark Pool

| Slug | Path | Purpose |
|------|------|---------|
| `DARKPOOL_TICKER` | `GET /api/darkpool/{ticker}` | Per-ticker dark pool prints. 500/call. Fields: `executed_at`, `price`, `size`, `premium`, `nbbo_bid`/`ask`, `market_center`, `tracking_id`. No notional field — compute `size × price`. |

Also accessible (no slug):
- `GET /api/darkpool/recent` — cross-ticker dark pool feed (same shape, used for discovery)
- `GET /api/lit-flow/recent` + `GET /api/lit-flow/{ticker}` — exchange-printed (lit) trades with same field shape

---

### Short Interest

| Slug | Path | Purpose |
|------|------|---------|
| `SHORT_DATA` | `GET /api/shorts/{ticker}/data` | Intraday snapshots: `short_shares_available`, `fee_rate`, `rebate_rate`. Multiple rows per day. **Does not include** short interest % / utilization — use `SHORT_INTEREST_FLOAT` for those. |
| `SHORT_INTEREST_FLOAT` | `GET /api/shorts/{ticker}/interest-float/v2` | 117-row series: `short_interest`, `si_float`, `si_float_with_synth_long_pct_of_total_shares`, `days_to_cover`, `fee_rate`, `short_shares_available`, `total_float`. |

Also accessible (no slug):
- `GET /api/shorts/{ticker}/interest-float` (v1) — 19-row shorter series
- `GET /api/shorts/{ticker}/ftds` — Failures to Deliver, 728+ periods
- `GET /api/shorts/{ticker}/volumes-by-exchange` — 500-row short volume by exchange
- `GET /api/shorts/{ticker}/volume-and-ratio` — short volume ratio series
- `GET /api/short_screener` — screener: `days_to_cover`, `si_float`, `fee_rate`, `short_interest`

---

### Screener / Bulk

| Slug | Path | Purpose |
|------|------|---------|
| `BULK_SCREENER_STOCKS` | `GET /api/screener/stocks` | 70-field per-ticker rows: `net_call_premium`, `net_put_premium`, `bullish_premium`, `bearish_premium`, `iv_rank`, `implied_move`, `next_earnings_date`, `marketcap`, `sector`, 30d avg volumes. 100/call. Used for bulk scan and single-ticker row fetch. |
| `ANALYST_RATINGS` | `GET /api/screener/analysts` | Analyst actions with firm, target, recommendation, timestamp. `ticker` filter param. |

Also accessible (no slug):
- `GET /api/screener/option-contracts` — "Hottest Chains" screener with ask-side%, bid-side%, delta, 7-day averages, OI/vol context

---

### Stock State & Info

| Slug | Path | Purpose |
|------|------|---------|
| `STOCK_STATE` | `GET /api/stock/{ticker}/stock-state` | Last-trade snapshot: `close`, `prev_close`, `open`, `high`, `low`, `volume`, `tape_time`, `market_time`. Works for indices (SPX `volume=0` by design). |
| `OPTIONS_VOLUME_DAILY` | `GET /api/stock/{ticker}/options-volume` | Daily rows: `call_volume`, `put_volume`, `call_premium`, `put_premium`, `net_call_premium`, `net_put_premium`, `bearish_premium`, `bullish_premium`, 3/7/30d averages. `limit` param. |

Also accessible (no slug):
- `GET /api/stock/{ticker}/info` — `sector`, `marketcap`, `avg30_volume`, `beta`, `has_options`, `next_earnings_date`, `issue_type`
- `GET /api/stock/{ticker}/flow-per-strike` — daily call+put premium aggregated by strike; `date` param; used in VRP macro pipeline but called via client directly
- `GET /api/stock/{ticker}/flow-per-expiry` — daily call+put premium by expiry
- `GET /api/stock/{ticker}/flow-per-strike-intraday` — same as flow-per-strike but at 1-min resolution (full market date per call)
- `GET /api/stock/{ticker}/net-prem-ticks` — 1-min net premium ticks with `net_call_premium`, `net_put_premium`, `net_delta`, `call/put_volume_ask_side`
- `GET /api/stock/{ticker}/nope` — NOPE (Net Options Pricing Effect): 1-min `nope`/`nope_fill`, `call_delta`, `put_delta`; strong empirical predictor of near-term price moves
- `GET /api/stock/{ticker}/greek-flow` — 1-min intraday delta/vega flow (`dir_delta_flow`, `dir_vega_flow`, `total_delta_flow`, `total_vega_flow`)
- `GET /api/stock/{ticker}/greek-flow/{expiry}` — same, per-expiry granularity
- `GET /api/stock/{ticker}/stock-volume-price-levels` — lit+dark volume by price level (53k+ rows for TSLA)
- `GET /api/stock/{ticker}/oi-per-expiry` — OI by expiry
- `GET /api/stock/{ticker}/insider-buy-sells` — per-day timeline of insider buys/sells
- `GET /api/stock/{ticker}/technical-indicator/{function}` — MA/RSI/MACD/BBANDS/STOCH/ADX (251-row series)

---

### Fundamentals (accessible on standard tier)

No slugs exist for these. All return full trailing histories.

| Path | Content |
|------|---------|
| `GET /api/stock/{ticker}/balance-sheets` | 94 quarters: cash, debt, goodwill, PPE, receivables |
| `GET /api/stock/{ticker}/cash-flows` | 94 quarters: FCF, capex, dividends, operating CF |
| `GET /api/stock/{ticker}/income-statements` | 94 quarters: revenue, EBIT, EBITDA, net income, gross profit |
| `GET /api/stock/{ticker}/financials` | All three above in one call |
| `GET /api/stock/{ticker}/fundamental-breakdown` | Revenue segmentation, annual/quarterly toggle |
| `GET /api/stock/{ticker}/earnings` | Earnings timeline with `actual_eps`, `surprise`, `post_earnings_move_1d/1w/2w` |

---

### ETF

| Slug | Path | Purpose |
|------|------|---------|
| `ETF_INFO` | `GET /api/etfs/{ticker}/info` | AUM, expense ratio, inception date, call/put vol, holdings count. Used in Gold Compass. |
| `ETF_IN_OUTFLOW` | `GET /api/etfs/{ticker}/in-outflow` | Daily `change`, `close`, `volume`, `expiration_cycle`, `is_fomc`. Used in Gold Compass. |

Also accessible (no slug):
- `GET /api/etfs/{ticker}/holdings` — full constituent list with premium/vol context (250 rows for SPY)
- `GET /api/etfs/{ticker}/exposure` — which ETFs hold a given ticker
- `GET /api/etfs/{ticker}/weights` — sector/country breakdown

---

### Institutional / Insider / Congress

| Slug | Path | Purpose |
|------|------|---------|
| `INSTITUTION_OWNERSHIP` | `GET /api/institution/{ticker}/ownership` | Latest institutional holders for a ticker. |
| `INSIDER_TICKER_FLOW` | `GET /api/insider/{ticker}/ticker-flow` | Aggregated insider buy/sell flow by date. |
| `EARNINGS` | `GET /api/earnings/{ticker}` | Historical earnings with straddle move data. |

Also accessible (no slug):
- `GET /api/institution/{name}/activity` — institution-level holding changes over time
- `GET /api/institution/{name}/sectors` — institution sector allocation
- `GET /api/institutions` — list of tracked institutions
- `GET /api/institutions/latest_filings` — recent 13F filings
- `GET /api/insider/transactions` — raw insider transactions with `formtype`, `is_10b5_1`, `is_director`
- `GET /api/insider/{sector}/sector-flow` — sector-level insider flow aggregate
- `GET /api/insider/{ticker}` — list of insiders for a ticker
- `GET /api/congress/recent-trades` — congressional trades with ticker, amounts, txn_type
- `GET /api/congress/congress-trader` — filter by politician (date param supported)
- `GET /api/congress/late-reports` — late-filed disclosures
- `GET /api/congress/politicians` — 400 trackable members with trade count
- `GET /api/politician-portfolios/recent_trades` — accessible on standard tier despite enterprise-docs label

---

### Market-Wide

No slugs for any of these yet.

| Path | Content | Signal potential |
|------|---------|-----------------|
| `GET /api/market/market-tide` | 1-min `net_call_premium` vs `net_put_premium`, `net_volume`. `date` param. | **HIGH** — real-time regime pulse |
| `GET /api/market/{sector}/sector-tide` | Same as market-tide but per GICS sector | **HIGH** — sector rotation signal |
| `GET /api/market/{ticker}/etf-tide` | Same but for a specific ETF | **MEDIUM** |
| `GET /api/market/top-net-impact` | Top tickers by net option premium that day | **HIGH** — daily "follow the big money" |
| `GET /api/market/oi-change` | Market-wide top OI movers (same fields as per-ticker OI change) | **MEDIUM** |
| `GET /api/market/total-options-volume` | Daily call+put volume and premium totals | **LOW** — useful for normalization |
| `GET /api/market/sector-etfs` | SPDR sector ETF stats: premium, flow, in_out_flow, 30d averages | **MEDIUM** |
| `GET /api/market/correlations` | Rolling correlation matrix for requested tickers | **MEDIUM** |
| `GET /api/market/economic-calendar` | Upcoming macro events | **LOW** |
| `GET /api/market/fda-calendar` | FDA catalyst calendar | **MEDIUM** for biotech |
| `GET /api/market/insider-buy-sells` | Daily aggregate insider buy/sell counts | **LOW** |
| `GET /api/net-flow/expiry` | Net flow bucketed by expiry and moneyness tier | **MEDIUM** |

---

### Group Flow (Sector-Level Greek Flow)

| Path | Content |
|------|---------|
| `GET /api/group-flow/{flow_group}/greek-flow` | 1-min sector delta/vega flow: `dir_delta_flow`, `dir_vega_flow`, `net_call_premium`, `net_put_premium`. `date` param. |
| `GET /api/group-flow/{flow_group}/greek-flow/{expiry}` | Same, filtered to one expiry. |

`flow_group` values correspond to GICS sectors (e.g. `technology`, `health_care`).

---

### Seasonality

All accessible; none integrated.

| Path | Content |
|------|---------|
| `GET /api/seasonality/{ticker}/monthly` | Average monthly return, win rate, max/min by month |
| `GET /api/seasonality/{ticker}/year-month` | Year×month return matrix |
| `GET /api/seasonality/{month}/performers` | Best/worst performers for a calendar month |
| `GET /api/seasonality/market` | Market-wide seasonality for SPY/QQQ etc. |

---

### Prediction Markets

All accessible. Returns Kalshi/Polymarket-style prediction positions held by smart money / whales / insiders.

| Path | Content |
|------|---------|
| `GET /api/predictions/insiders` | Insider prediction positions by category |
| `GET /api/predictions/smart-money` | Smart-money positions |
| `GET /api/predictions/unusual` | Unusual prediction activity |
| `GET /api/predictions/whales` | Whale positions |
| `GET /api/predictions/market/{asset_id}` | Specific prediction market state |
| `GET /api/predictions/market/{asset_id}/liquidity` | Order-book depth |
| `GET /api/predictions/market/{asset_id}/positions` | Position holders |

---

### Crypto

| Path | Content |
|------|---------|
| `GET /api/crypto/whale-transactions` | Large on-chain transfers with `usd_value`, `whale_score` |
| `GET /api/crypto/whales/recent` | Recent large exchange trades |
| `GET /api/crypto/{pair}/ohlc/{candle_size}` | OHLCV with `date` param |
| `GET /api/crypto/{pair}/state` | Current 24h state |

---

### News & Directory

| Path | Content |
|------|---------|
| `GET /api/news/headlines` | Headlines with `sentiment`, `tags`, `tickers`, `is_major` |
| `GET /api/stock-directory/ticker-exchanges` | 17,566-row ticker → exchange map |
| `GET /api/stock/{sector}/tickers` | Tickers for a given sector |
| `GET /api/alerts` | Custom alert history (user-specific) |
| `GET /api/alerts/configuration` | Alert rule configuration |
| `GET /api/earnings/premarket` + `/afterhours` | Calendar earnings with `expected_move`, `reaction`, `post_earnings_*` |

---

## Signal Opportunities by Priority

Accessible endpoints not yet integrated, ranked by value-to-effort for argon's vol-selling / regime framework:

| Priority | Endpoint | Why |
|----------|----------|-----|
| **P1** | `market-tide` | 1-min market-wide call vs put premium — free real-time regime signal; feeds CRI/VCG directly |
| **P1** | `sector-tide` | Same at sector level — rotate into sector with largest put premium accumulation |
| **P1** | `top-net-impact` | Daily "where is the money?" — single market-wide call covers ~100 tickers |
| **P1** | `flow-per-strike` (ticker) | Already used in VRP macro but lacks formal slug; add it |
| **P2** | `nope` | NOPE intraday — empirical SPX short-term predictor; 1 call/tick |
| **P2** | `net-prem-ticks` | 1-min per-ticker options flow direction — intraday momentum for entry timing |
| **P2** | `greek-flow` | 1-min delta/vega velocity — tracks positioning changes, not just levels |
| **P2** | `ftds` | Failures to Deliver time series — leading indicator for short squeeze candidates |
| **P2** | `option-contract/flow` | Contract-level trade feed for specific positions held |
| **P3** | `seasonality/*` | Confirmed accessible; one call per ticker per year |
| **P3** | `screener/option-contracts` | Hottest chains screener — discovery complement to flow-alerts |
| **P3** | `group-flow/*` | Sector greek flow — fills the gap between stock-level and market-level |
| **P3** | `earnings/premarket` + `afterhours` | Earnings calendar with historical reaction data for sizing |
| **P3** | `shorts/ftds` + `volumes-by-exchange` | Short squeeze scoring additions |
| **P4** | `balance-sheets`, `cash-flows`, `income-statements` | 94 quarters available; useful for fundamentals context scoring |
| **P4** | `congress/recent-trades` | Political signal; low frequency, one daily call covers all |
| **P4** | `predictions/*` | Polymarket/Kalshi positioning — alternative regime sentiment source |
| **P4** | `technical-indicator` | If we want MA/RSI/MACD from UW rather than computing locally |

---

## Backfill Notes

**30 trading-day lookback** on date-selector endpoints. Confirmed live (probed 2026-05-15):
- `2026-04-14` → 200 on dark pool, greeks, OI, skew, vol endpoints
- `2026-03-13` → 403 ("earliest available date is 2026-04-01")

| Endpoint group | Historical selector | Notes |
|----------------|--------------------|----|
| Flow alerts | `newer_than`, `older_than`, `limit` | Cursor; empty array near the 30d edge (not a 403) |
| Dark pool | `date` or `newer_than`/`older_than` | 30 trading days confirmed |
| Strike flow | `date` | Full day per call |
| Intraday strike flow | `date` | Full market date per call (all 1-min rows) |
| Greeks by expiry | `date`, `expiry` | Requires choosing expiries up front |
| GEX strike/expiry | `date`, `expiry` | Same |
| Spot exposures | `date`, `expirations[]` | Official docs note history from 2025-01-16 |
| OI by strike | `date` | Daily snapshot |
| Max pain | `date` | Daily snapshot |
| IV rank | `date` | Returns trailing slice ending at date |
| Volatility stats | `date` | One object per requested date |
| Realized volatility | `date`, optional `timeframe` | ~250-row series anchored at date |
| Term structure | `date` | Daily expiry snapshot |
| Historical skew | `date`, `expiry`, `delta` | Requires per-(expiry, delta) iteration |
| Options volume | `limit` | No `date` param — pagination only |

**Not backfillable with this key:**
- Full tape `/api/option-trades/full-tape/{date}` — Advanced tier required
- WebSocket channels — live streaming only
- `matrix_state_snapshots` — app-derived; requires the compute job to run forward

---

## Adding a New Endpoint

1. Add slug to `EndpointSlug` in `api/endpoints.py` + register in `REGISTRY`
2. Add typed model to the appropriate `models/` domain module + re-export from `models/__init__.py`
3. Add fetcher to `sources/uw.py` (audit + raw payload persist before return)
4. Add persistence method to the appropriate `storage/<domain>_repository.py`
5. Wire into relevant `reports/*` assembler or scheduler job
6. Add unit + integration tests
7. Run `cd web && npm run gen:types` after any model change
