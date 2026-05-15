# Unusual Whales API Reference

**Base URL:** `https://api.unusualwhales.com`

**Authentication:** Bearer token in Authorization header
```
Authorization: Bearer {UW_TOKEN}
```

The `UW_TOKEN` environment variable should contain your API key.

---

## Core Endpoints for Xenon

### Dark Pool / OTC Flow (Primary Edge Source)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/darkpool/{ticker}` | GET | Dark pool trades for a ticker on a given day |
| `/api/darkpool/recent` | GET | Latest dark pool trades across all tickers |

**Dark Pool Ticker Parameters:**
- `ticker` (path, required): Stock symbol
- `date` (query, optional): ISO date (YYYY-MM-DD), defaults to current/last market day
- `min_premium`, `max_premium`: Filter by trade premium
- `min_size`, `max_size`: Filter by trade size
- `limit`: Max 500

**Response Fields:**
```json
{
  "data": [{
    "ticker": "AAPL",
    "executed_at": "2023-02-16T00:59:44Z",
    "price": "18.99",
    "size": 18600,
    "premium": "353214",
    "nbbo_bid": "18.99",
    "nbbo_ask": "19",
    "market_center": "L",
    "volume": 9940419
  }]
}
```

---

### Options Flow Alerts (Signal Detection)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/option-trades/flow-alerts` | GET | Latest flow alerts (sweeps, blocks, unusual activity) |

**Key Parameters:**
- `ticker_symbol`: Filter by ticker(s)
- `min_premium`, `max_premium`: Premium range
- `min_size`, `max_size`: Size range
- `is_sweep`: Boolean - intermarket sweeps only
- `is_floor`: Boolean - floor trades only
- `is_call`, `is_put`: Filter by option type
- `is_ask_side`, `is_bid_side`: Filter by trade side
- `all_opening`: Boolean - opening transactions only
- `min_dte`, `max_dte`: Days to expiration range
- `is_otm`: Boolean - OTM contracts only
- `rule_name[]`: Filter by alert type (RepeatedHits, FloorTradeLargeCap, etc.)
- `issue_types[]`: Common Stock, ETF, Index
- `limit`: Max 200

**Response Fields:**
```json
{
  "data": [{
    "alert_rule": "RepeatedHits",
    "ticker": "MSFT",
    "option_chain": "MSFT231222C00375000",
    "strike": "375",
    "expiry": "2023-12-22",
    "type": "call",
    "underlying_price": "372.99",
    "total_premium": "186705",
    "total_size": 461,
    "open_interest": 7913,
    "volume": 2442,
    "volume_oi_ratio": "0.308",
    "total_ask_side_prem": "151875",
    "total_bid_side_prem": "405",
    "has_sweep": true,
    "has_floor": false,
    "all_opening_trades": false
  }]
}
```

---

### Stock Information

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock/{ticker}/info` | GET | Company info, sector, market cap |
| `/api/stock/{ticker}/options-volume` | GET | Options volume & premium summary |
| `/api/stock/{ticker}/ohlc/{candle_size}` | GET | OHLC price data |

**Info Response:**
```json
{
  "data": {
    "ticker": "AAPL",
    "full_name": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "marketcap": "2850000000000",
    "avg30_volume": "73784934",
    "has_options": true,
    "is_s_p_500": true
  }
}
```

---

### Options Chain Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock/{ticker}/option-contracts` | GET | All option contracts for ticker |
| `/api/stock/{ticker}/expiry-breakdown` | GET | Available expirations with volume/OI |
| `/api/stock/{ticker}/greeks` | GET | Greeks for each strike at an expiry |
| `/api/option-contract/{id}/historic` | GET | Historical data for specific contract |

**Option Contracts Parameters:**
- `expiry`: Filter by expiration date
- `option_type`: call or put
- `vol_greater_oi`: Boolean - volume > OI filter
- `exclude_zero_vol_chains`: Boolean
- `maybe_otm_only`: Boolean - OTM only

---

### Greek Exposure (GEX)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock/{ticker}/greek-exposure` | GET | Total greek exposure over time |
| `/api/stock/{ticker}/greek-exposure/strike` | GET | GEX by strike |
| `/api/stock/{ticker}/greek-exposure/expiry` | GET | GEX by expiration |
| `/api/stock/{ticker}/greek-flow` | GET | Intraday delta/vega flow per minute |

---

### Options Flow by Ticker

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock/{ticker}/flow-per-strike` | GET | Flow aggregated by strike |
| `/api/stock/{ticker}/flow-per-expiry` | GET | Flow aggregated by expiration |
| `/api/stock/{ticker}/net-prem-ticks` | GET | Net premium ticks (1-min intervals) |

---

### Volatility Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock/{ticker}/volatility/realized` | GET | IV vs realized volatility |
| `/api/stock/{ticker}/volatility/term-structure` | GET | IV term structure by expiry |
| `/api/stock/{ticker}/volatility/stats` | GET | Comprehensive volatility statistics |
| `/api/stock/{ticker}/iv-rank` | GET | IV rank data over time |

---

### Analyst Ratings

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/screener/analysts` | GET | Analyst ratings and price targets |

**Parameters:**
- `ticker`: Filter by ticker
- `action`: initiated, reiterated, downgraded, upgraded, maintained
- `recommendation`: buy, hold, sell
- `limit`: Max 500

**Response:**
```json
{
  "data": [{
    "ticker": "MSFT",
    "action": "maintained",
    "recommendation": "buy",
    "analyst_name": "Tyler Radke",
    "firm": "Citi",
    "target": "420.0",
    "sector": "Technology",
    "timestamp": "2023-09-11T11:21:12Z"
  }]
}
```

---

### Seasonality

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/seasonality/{ticker}/monthly` | GET | Average return by month |
| `/api/seasonality/{ticker}/year-month` | GET | Returns per month per year |
| `/api/seasonality/market` | GET | Market-wide seasonality (SPY, QQQ, etc.) |
| `/api/seasonality/{month}/performers` | GET | Best/worst performers for a month |

---

### Institutional Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/institution/{ticker}/ownership` | GET | Institutional ownership of ticker |
| `/api/institution/{name}/holdings` | GET | Holdings for an institution |
| `/api/institutions` | GET | List of institutions |

---

### Short Interest

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/shorts/{ticker}/interest-float/v2` | GET | Short interest and float data |
| `/api/shorts/{ticker}/data` | GET | Short data including borrow rate |
| `/api/shorts/{ticker}/volume-and-ratio` | GET | Short volume and ratio |
| `/api/short_screener` | GET | Screen for high short interest |

---

### Insider Trading

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/insider/transactions` | GET | Insider buy/sell transactions |
| `/api/insider/{ticker}` | GET | Insiders for a ticker |
| `/api/insider/{ticker}/ticker-flow` | GET | Aggregated insider flow |

---

### Congress Trading

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/congress/recent-trades` | GET | Latest congress trades |
| `/api/congress/congress-trader` | GET | Trades by congress member |

---

### ETF Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/etfs/{ticker}/info` | GET | ETF information |
| `/api/etfs/{ticker}/holdings` | GET | ETF holdings |
| `/api/etfs/{ticker}/exposure` | GET | ETFs containing a ticker |

---

### Market Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/market/market-tide` | GET | Market-wide options sentiment |
| `/api/market/sector-etfs` | GET | SPDR sector ETF stats |
| `/api/market/total-options-volume` | GET | Total market options volume |
| `/api/market/oi-change` | GET | Biggest OI changes |
| `/api/market/economic-calendar` | GET | Economic events |
| `/api/market/fda-calendar` | GET | FDA calendar events |

---

### Earnings

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/earnings/premarket` | GET | Premarket earnings |
| `/api/earnings/afterhours` | GET | Afterhours earnings |
| `/api/earnings/{ticker}` | GET | Historical earnings for ticker |

---

### Screeners

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/screener/stocks` | GET | Stock screener with many filters |
| `/api/screener/option-contracts` | GET | Options contract screener (Hottest Chains) |

---

### WebSocket Streaming

**WebSocket URL:** `wss://api.unusualwhales.com/socket?token={UW_TOKEN}`

**Channels:**
| Channel | Description |
|---------|-------------|
| `option_trades` | All option trades (6-10M/day) |
| `option_trades:{TICKER}` | Option trades for specific ticker |
| `flow-alerts` | Live flow alerts |
| `price:{TICKER}` | Live price updates |
| `gex:{TICKER}` | Live GEX updates |
| `news` | Live headline news |
| `lit_trades` | Exchange trades |
| `off_lit_trades` | Dark pool trades |

**Join Channel:**
```json
{"channel": "option_trades:AAPL", "msg_type": "join"}
```

---

## Error Handling

| Status | Description |
|--------|-------------|
| 200 | Success |
| 404 | Ticker not found |
| 422 | Invalid parameters |
| 500 | Internal server error |

---

## Rate Limits

- Standard tier: Varies by endpoint
- Advanced tier: Higher limits + WebSocket access
- Full tape download: Advanced tier only

---

## Exhaustive API Surface Audit

Verified against the official OpenAPI document at
`https://api.unusualwhales.com/api/openapi` and live-probed with the current
local API key on 2026-05-15.

- The live official OpenAPI currently exposes **177 GET operations**. The local
  YAML spec has been refreshed to that official surface.
- Live audit result with the current key: **140 accessible**, **36 gated**, and
  **1 unresolved sample-invalid** operation.
- Generated evidence:
  - `docs/uw-samples/uw_api_capability_audit.json` stores the machine-readable
    status, sample request, response shape summary, entitlement hint, and
    backfill classification for every operation.
  - `docs/uw-samples/uw_api_capability_audit.md` stores the complete
    human-readable operation matrix.

Current-key accessible families include standard alerts/configuration metadata,
standard congressional trades, crypto whale/price endpoints, dark pool/off-lit
and lit flow, earnings, ETF data, group flow, insider data, institution data,
core market endpoints, net flow, news, option-contract data, option flow alerts,
recent politician trades, prediction-market aggregate endpoints, screeners,
seasonality, short-interest data, socket metadata, and broad stock/options/
Greek/volatility/fundamental endpoints.

The only unresolved sample is `/api/predictions/user/{user_id}`: the generated
sample returned `422 HashDive API error: 400`, so entitlement for that specific
operation remains unknown until we have a real prediction-market user id sample.

---

## Advanced / Gated Feature Spectrum

Verified against official docs and the exhaustive live audit with the current
local API key on 2026-05-15. The current key is **not** Advanced: Advanced+
probes returned `403` with "This endpoint requires the Advanced API tier or
higher." Premium/enterprise groups returned missing-access `422` responses.

| Tier / scope | Feature area | Endpoint examples | Live probe / docs result |
|---|---|---|---|
| Current/basic API | Core options, dark pool, stock, Greek, volatility, crypto, ETF, institution, insider, standard congressional, screeners, seasonality, shorts, prediction aggregates, socket metadata | 140 audited GET operations returned `200` | Available with current key; see the capability audit matrix for every path. |
| Advanced+ | Forex | `/api/forex/rate`, `/api/forex/history`, `/api/forex/intraday` | Official operation docs say "Requires Advanced+ tier"; current key returned `403`. |
| Advanced+ | Commodities | `/api/commodities/{name}` for `wti`, `brent`, `natural-gas`, `copper`, `aluminum`, `wheat`, `corn`, `cotton`, `sugar`, `coffee`, `all-commodities` | Official operation docs say Advanced+; current key returned `403`. |
| Advanced+ | US macro/economy series | `/api/economy/{indicator}` for `gdp`, `gdp-per-capita`, `treasury-yield`, `fed-funds`, `cpi`, `inflation`, `retail-sales`, `durables`, `unemployment`, `payrolls` | Official operation docs say Advanced+; current key returned `403`. |
| Advanced+ | Digital currency series | `/api/digital-currencies/history`, `/api/digital-currencies/intraday` | Official operation docs say Advanced+; current key returned `403`. |
| Advanced+ | Company fundamentals / listings extras | `/api/companies/listings`, `/api/companies/{ticker}/profile`, `/api/companies/{ticker}/dividends`, `/api/companies/{ticker}/splits`, `/api/companies/{ticker}/earnings-estimates`, `/api/companies/{ticker}/transcripts/{quarter}` | Current key returned `403` requiring Advanced API tier or higher. |
| Advanced+ | Market intelligence extras | `/api/market/movers`, `/api/calendar/ipo`, `/api/analytics/sliding`, `/api/analytics/window` | Current key returned `403` requiring Advanced API tier or higher. |
| Advanced API / websocket scope | Personal-use WebSocket streaming | `option_trades`, `flow-alerts`, `price:{TICKER}`, `news`, `lit_trades`, `off_lit_trades`, `gex:*`, `market_tide`, `net_flow:*`, `interval_flow`, `contract_screener`, `trading_halts`, `custom_alerts` | Socket metadata endpoints returned `200`; official docs still mark personal-use streaming access as Advanced plan scope. |
| Advanced API | Full tape archive | `/api/option-trades/full-tape/{date}` | Official docs say Advanced API and last 3 trading days; current key returned `422 Missing access for full tape`. |
| Premium | Congressional unusual-trade products | `/api/congress/unusual-trades`, `/api/congress/unusual-trades/by-tickers`, `/api/congress/unusual-trades/chart-data`, `/api/congress/unusual-trades/stats` | Current key returned `422 Missing access for unusual trades`; response says premium endpoint. |
| Premium | Private markets | `/api/private-markets/*` | Current key returned `422 Missing access for private markets`; response says premium endpoint. |
| Enterprise / Professional | Redistribution/custom solutions, politician portfolio endpoints, stock ownership | `/api/politician-portfolios/*`, `/api/stock/{ticker}/ownership` | Current key returned enterprise-only missing-access responses. |
| Enterprise Startup + Kafka | Kafka event streaming | `stream.unusualwhales.com:9083` topics such as flow alerts | UW Kafka page advertises replay from offsets, consumer groups, 72h retention, REST quota, websocket access, and real-time Kafka access. |

---

## Backfill / Historical Query Notes

Verified against the live UW API with the current local API key on 2026-05-15.
This section documents source capability only; the app does not yet have a
general-purpose backfill runner for missed scan windows.

The exhaustive audit classifies **69 operations** as having explicit historical
selectors (`date`, `newer_than`, `older_than`, `start_date`, or `end_date`) and
**5 additional operations** as historical by path shape. This is broader than
the endpoints currently integrated into `uw_scan`; use the capability matrix
before adding new fetchers.

### Account-Level Lookback Observed

- Date-parameter endpoints returned live data for `2026-04-14` and `2026-04-15`.
- The same endpoints rejected `2026-03-13` and `2025-05-14` with `403` and the
  message: earliest available date is `2026-04-01 (30 trading days)`.
- Treat "30 Day historical look back" on the plan page as **30 trading days** for
  date-based endpoints, subject to endpoint-specific rules.
- Timestamp-cursor flow alerts behaved differently: `/api/option-trades/flow-alerts`
  returned data through `2026-04-15T20:00:00Z`; requesting
  `older_than=2026-04-14T20:00:00Z` returned an empty `data` array, not a 403.

### Confirmed Backfillable Endpoint Groups

| Data group | Endpoint(s) | Historical selector | Live probe result | Backfill note |
|---|---|---|---|---|
| Flow alerts | `/api/option-trades/flow-alerts` | `newer_than`, `older_than`, `limit` | `200`, incident window `2026-05-14T17:47:31Z..20:00:00Z` returned rows | Cursor/page by timestamp; persist by `alert_id`. Confirmed near 30-day edge on `2026-04-15`; `2026-04-14` returned empty. |
| Dark pool / off-lit prints | `/api/darkpool/{ticker}` | `date` or `newer_than`/`older_than`, plus `limit` | `200` for `TSLA` on `2026-04-14` and for incident timestamp window | Date-based lookback confirmed as 30 trading days for this key. |
| Strike flow | `/api/stock/{ticker}/flow-per-strike` | `date` | `200` for `TSLA` on `2026-04-14`; `403` for `2026-03-13` | Daily aggregate can be repaired by market date. |
| Intraday strike flow | `/api/stock/{ticker}/flow-per-strike-intraday` | `date` | `200`, `TSLA` on `2026-05-14` returned 1-minute rows from market open through close | Useful for missed intraday windows, but endpoint returns the whole market date. |
| Greeks by expiry | `/api/stock/{ticker}/greeks` | `date`, `expiry` | `200` for `TSLA`, `date=2026-04-14`, `expiry=2026-05-15`; `403` for `2026-03-13` | Requires choosing expiry dates for the backfill run. |
| GEX strike/expiry | `/api/stock/{ticker}/greek-exposure/strike-expiry` | `date`, `expiry` | `200` for `TSLA`, `date=2026-04-14`, `expiry=2026-05-15`; `403` for `2026-03-13` | Same expiry-selection requirement as greeks. |
| Spot GEX by expiry/strike | `/api/stock/{ticker}/spot-exposures/expiry-strike` | `date`, `expirations[]`, paging/filter params | `200` for `TSLA`, `date=2026-05-14`, `expirations[]=2026-05-15` | Official docs note data is available since `2025-01-16`, but current key/date-window limits still apply. |
| OI by strike | `/api/stock/{ticker}/oi-per-strike` | `date` | `200` for `TSLA` on `2026-04-14`; `403` for `2026-03-13` | Daily snapshot repair by market date. |
| Max pain | `/api/stock/{ticker}/max-pain` | `date` | `200` for `TSLA`, `date=2026-05-14` | Daily expiry-level snapshot. |
| IV rank | `/api/stock/{ticker}/iv-rank` | `date` | `200` for `date=2026-04-14`, response included a small trailing series ending on that date; `403` for `2026-03-13` | Endpoint returns a trailing slice ending at `date`, not just one row. |
| Volatility stats | `/api/stock/{ticker}/volatility/stats` | `date` | `200` object for `TSLA`, `date=2026-04-14`; `403` for `2026-03-13` | One object per requested market date. |
| Realized volatility | `/api/stock/{ticker}/volatility/realized` | `date`, optional `timeframe` | `200` for `date=2026-04-14`, response returned about 250 rows ending on that date | Historical series endpoint; date parameter anchors the returned series. |
| Term structure | `/api/stock/{ticker}/volatility/term-structure` | `date` | `200` for `TSLA`, `date=2026-04-14`; `403` for `2026-03-13` | Daily expiry term snapshot. |
| Historical risk-reversal skew | `/api/stock/{ticker}/historical-risk-reversal-skew` | `date`, `expiry`, `delta` | `200` for `TSLA`, `date=2026-05-14`, `expiry=2026-05-15`, `delta=25`, returned a historical series ending on date | Backfill must pick expiry/delta combinations. |
| Options volume history | `/api/stock/{ticker}/options-volume` | `limit` | `200`, `limit=5` returned recent daily rows | Current repo uses this as a multi-day pull; no direct `date` selector observed in the integrated fetcher. |

### Not Currently Backfillable With This Key / Setup

- `/api/option-trades/full-tape/{date}` returned `422` with "Missing access for
  full tape"; official docs mark it as Advanced API / websocket-scope access.
- `/api/stock/{ticker}/option-contracts` returned the current chain snapshot and
  is not a historical date repair path in the current fetcher.
- WebSocket channels are live streaming only for this app; use REST endpoints
  above for repair/backfill.
- `matrix_state_snapshots` is app-derived and currently empty; it cannot be
  repaired from UW directly until the app-side derivation job is implemented.

---

## Script → Endpoint Mapping

Which scripts use which UW endpoints:

| Script | Endpoints Used |
|--------|----------------|
| `fetch_ticker.py` | `/api/darkpool/{ticker}` (validation via activity) |
| `fetch_flow.py` | `/api/darkpool/{ticker}`, `/api/option-trades/flow-alerts` |
| `fetch_options.py` | `/api/stock/{ticker}/option-contracts`, `/api/option-trades/flow-alerts` |
| `fetch_analyst_ratings.py` | `/api/screener/analysts` |
| `scanner.py` | `/api/darkpool/{ticker}`, `/api/option-trades/flow-alerts` |
| `discover.py` | `/api/darkpool/recent`, `/api/option-trades/flow-alerts` |
| `leap_scanner_uw.py` | `/api/stock/{ticker}/volatility/stats` |

---

## Full API Spec

See `docs/unusual_whales_api_spec.yaml` for complete OpenAPI specification.
