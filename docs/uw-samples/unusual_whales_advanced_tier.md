# Unusual Whales API — Gated / Advanced Tier Endpoints

These endpoints return 403 or 422 on the current standard API key. Do not add
fetchers for them without upgrading the subscription. Rate-limit headers are
still returned on blocked responses (they consume your daily budget).

**Live-probed:** 2026-05-15. Tier labels verified against official UW docs and
live 403/422 message bodies.

---

## Advanced+ Tier (403 `advanced_tier_required`)

These return:
```json
{"code": "advanced_tier_required", "message": "This endpoint requires the Advanced API tier or higher."}
```

### Analytics / Intelligence

| Path | Description |
|------|-------------|
| `GET /api/analytics/sliding` | Sliding-window cross-ticker analytics (`correlation`, `rolling_beta`, etc.) for `symbols`, `range`, `calculations` |
| `GET /api/analytics/window` | Fixed-window variant of the same |
| `GET /api/market/movers` | Pre-built top movers list (replaces building it yourself from screener) |
| `GET /api/calendar/ipo` | IPO calendar |

### Macro / Economy Series

| Path | Indicators available |
|------|---------------------|
| `GET /api/economy/{indicator}` | `gdp`, `gdp-per-capita`, `treasury-yield`, `fed-funds`, `cpi`, `inflation`, `retail-sales`, `durables`, `unemployment`, `payrolls` |
| `GET /api/commodities/{name}` | `wti`, `brent`, `natural-gas`, `copper`, `aluminum`, `wheat`, `corn`, `cotton`, `sugar`, `coffee`, `all-commodities` |

### Forex

| Path | Description |
|------|-------------|
| `GET /api/forex/rate` | Spot FX rate |
| `GET /api/forex/history` | Historical daily series |
| `GET /api/forex/intraday` | Intraday series |

### Digital Currencies

| Path | Description |
|------|-------------|
| `GET /api/digital-currencies/history` | Historical OHLCV for `symbol`+`market` pair |
| `GET /api/digital-currencies/intraday` | Intraday series |

### Company Data (Extras)

| Path | Description |
|------|-------------|
| `GET /api/companies/listings` | New listings by date |
| `GET /api/companies/{ticker}/profile` | Detailed company profile |
| `GET /api/companies/{ticker}/dividends` | Dividend history |
| `GET /api/companies/{ticker}/splits` | Stock split history |
| `GET /api/companies/{ticker}/earnings-estimates` | Forward earnings estimates |
| `GET /api/companies/{ticker}/transcripts/{quarter}` | Earnings call transcript |

### Full Tape (422 `missing_access`)

| Path | Description |
|------|-------------|
| `GET /api/option-trades/full-tape/{date}` | Complete options tape for a date (last 3 trading days). Advanced API subscription required. |

**Note on WebSocket access:** Official docs classify personal-use WebSocket streaming as an Advanced plan feature. The `GET /api/socket/*` metadata endpoints return 200 on standard tier (socket enumeration), but actual streaming connections may require Advanced.

---

## Premium Tier (422 `premium endpoint`)

| Path | Description |
|------|-------------|
| `GET /api/congress/unusual-trades` | Curated "unusual" congressional trade signals |
| `GET /api/congress/unusual-trades/by-tickers` | Filtered by ticker list |
| `GET /api/congress/unusual-trades/chart-data` | Charting data for unusual trades |
| `GET /api/congress/unusual-trades/stats` | Aggregate stats |
| `GET /api/private-markets/companies` | Pre-IPO company list |
| `GET /api/private-markets/companies/{npm_ticker}` | Pre-IPO company detail |
| `GET /api/private-markets/companies/{npm_ticker}/funding` | Funding rounds |
| `GET /api/private-markets/companies/{npm_ticker}/investors` | Investor list |
| `GET /api/private-markets/companies/{npm_ticker}/management` | Management team |
| `GET /api/private-markets/companies/{npm_ticker}/pricing` | Historical pricing |
| `GET /api/private-markets/investors` | Pre-IPO investor list |
| `GET /api/private-markets/investors/{name}` | Investor profile |
| `GET /api/private-markets/search` | Search pre-IPO market |

**Standard-tier workaround for congress:** `GET /api/congress/recent-trades`,
`/congress-trader`, `/late-reports`, and `/congress/politicians` all return 200
on standard tier — only the curated "unusual trades" product is premium-gated.

---

## Enterprise Tier (422 `enterprise only`)

| Path | Description |
|------|-------------|
| `GET /api/politician-portfolios/disclosures` | Full disclosure filings |
| `GET /api/politician-portfolios/holders/{ticker}` | Politicians holding a ticker |
| `GET /api/politician-portfolios/people` | Politician list |
| `GET /api/politician-portfolios/{politician_id}` | Individual politician portfolio |
| `GET /api/stock/{ticker}/ownership` | Aggregate stock ownership (note: institution/{ticker}/ownership IS accessible) |

**Exception:** `GET /api/politician-portfolios/recent_trades` is marked enterprise in docs
but returned 200 in the May 2026 live probe — treat as accessible until it breaks.

---

## Enterprise / Kafka Streaming

`stream.unusualwhales.com:9083` — Kafka topics for replay with offsets, consumer groups,
72h retention, and real-time option flow. Not accessible on any REST-only plan.

---

## Upgrade Path

If expanding budget to Daily-Enterprise or similar:
1. The highest-value unlocks are **Full Tape** (complete options tape per day for
   backtesting) and **Economy series** (fed-funds, CPI, payrolls for macro signals).
2. **Analytics/sliding** would replace manual correlation work in `market/correlations`.
3. **Commodities** series would complement the COMEX/LBMA gold sources already in place.
4. **Earnings-estimates** would add forward-looking EPS context to the stock card.

Contact: dev@unusualwhales.com or the API dashboard at
`https://unusualwhales.com/settings/api-dashboard`.
