# Unusual Whales Opportunity Scanner Design

Date: 2026-05-11

## Goal

Build a Streamlit app that shows potential options opportunities from Unusual Whales data and TradingView shared watchlists. The app should support live REST polling and saved snapshot replay, persist queryable historical data into local Postgres, and help answer whether unusual option flow is likely opening, closing, rolling, fading, or worth tracking.

This is not a trade execution system. It presents evidence, structure candidates, warnings, and tracking context.

## Repository And Database

- Local repo: `/Users/moremeds/projects/unusual-whales`
- Postgres database: `option_wizard`
- Postgres schema: `uw_scan`
- Environment prefix: `UW_SCAN_`
- Primary storage model: typed relational tables
- Secondary storage model: raw JSON audit archive for debugging/replay

The app should not rely on JSON for analysis. All queryable data must be flattened into typed relational tables with usable numeric, timestamp, ticker, option symbol, expiry, strike, side, and source columns. JSON/JSONB is allowed for raw audit payloads and small `extra` fields only.

## Product Shape

Use a dual-source opportunity engine:

1. **UW Flow Feed**: REST polling of unusual option flow and related UW endpoints.
2. **TradingView Watchlists**: public/shared TradingView watchlist URLs remain the source of truth. The app imports each shared source during a run, saves the imported symbols, and keeps each watchlist separated in the UI.
3. **Tracked Contracts/Expiries**: high-conviction contracts and important expiry/tenor groups are tracked automatically, with manual pinning from the UI.

All sources feed one enrichment and scoring pipeline, but source attribution stays visible.

## V1 Scope

- New Streamlit dashboard.
- Live REST polling only, no WebSocket.
- Snapshot replay from Postgres.
- UW flow feed plus TradingView shared watchlist source tabs.
- Auto-track high-conviction contracts/expiries.
- Manual pinning of contracts and expiry/tenor groups.
- OI and IV tracking for exact contracts and important expiries/tenors.
- OI/IV reconciliation labels: likely opening, closing, rolling, fading, hedge, or unknown.
- Opportunity scoring from the extracted scan logic.
- Suggested trade structures without sizing.
- Full option surface capability, but tiered by default to reduce requests.
- Raw API payload archive plus normalized relational tables.

## Deferred Scope

- Markout tables and dashboards.
- Backtesting dashboards.
- MFE/MAE/outcome statistics.
- Portfolio-aware sizing.
- Account/current-position ingestion.
- WebSocket upgrade.
- TradingView authenticated/session scraping.
- Automated trading or order placement.

## Streamlit Views

### Top Opportunities

Rank opportunities across UW flow and TradingView watchlist sources. Show source badges, score, setup type, suggested structure, warnings, IV/OI context, and track/pin controls.

### UW Flow Feed

Show polling feed of unusual option flow. Include filters for premium, ask/bid side, DTE, volume greater than OI, moneyness, single-leg/multi-leg, and contract type.

### TradingView Watchlists

Render one tab per shared watchlist source. Each tab shows imported symbols, latest UW enrichment, top contracts/expiries, IV rank changes, OI changes, and structure candidates.

### Tracked Contracts

Show exact contracts and expiry/tenor groups under watch. Include OI/IV reconciliation status and history.

### Surface Explorer

Selected ticker view for option surface, important expiries, OI by expiry/strike, greeks, GEX/DEX/vanna/charm, max pain, skew, IV rank, IV rank changes, realized volatility, and VRP proxy.

### Snapshots

Saved polling runs, reloadable as-of views, source metadata, and run status.

## Architecture

- `uw_scan.api`: typed UW REST client, request throttling, pagination, retries, and API usage metadata.
- `uw_scan.sources`: UW flow source, TradingView shared watchlist source, manual pinned source.
- `uw_scan.ingest`: polling runs, dedupe, batch planning, and acquisition tiers.
- `uw_scan.normalize`: converts UW/TradingView responses into typed domain rows.
- `uw_scan.storage`: Postgres schema creation, inserts, loads, and snapshot queries.
- `uw_scan.scoring`: conviction score, setup classification, confirmation flags, and warnings.
- `uw_scan.tracking`: tracked contract/expiry lifecycle and OI/IV reconciliation.
- `uw_scan.structures`: trade structure idea selection without sizing.
- `uw_scan.ui`: Streamlit views.

## Data Flow

1. User starts a live polling run or loads a saved snapshot.
2. Source adapters return source rows: UW flow rows, TradingView symbols, pinned contracts.
3. Batch planner dedupes tickers/contracts/expiries and chooses minimum required UW calls.
4. UW client fetches broad data first, then expensive surface/greek/exposure endpoints only for high-value candidates.
5. Storage writes typed normalized rows plus raw JSON audit.
6. Scoring classifies opportunities and structure ideas.
7. Tracking updates contract/expiry watch state and OI/IV reconciliation.
8. Streamlit renders source tabs, combined opportunities, contract detail, and snapshots.

## Storage Model

Expected core tables in schema `uw_scan`:

- `scan_runs`: one row per polling/snapshot run.
- `source_feeds`: UW feed, TradingView shared watchlist, and manual/pinned source definitions.
- `source_imports`: imported symbols/contracts per source/run.
- `api_request_audit`: endpoint, params, status, latency, fetched_at, response hash, and optional raw payload reference.
- `raw_payloads`: compressed raw JSON payloads for replay/debugging, not primary analytics.
- `flow_events`: normalized unusual flow rows.
- `option_contract_snapshots`: contract-level IV, OI, prev OI, volume, premium, bid/ask/mid/multi/sweep volume, prices, and liquidity.
- `option_surface_snapshots`: ticker/date/expiry surface snapshot metadata and pagination status.
- `greeks_by_expiry_strike`: delta, gamma, theta, vega, rho, vanna, charm, call/put IV by ticker/date/expiry/strike.
- `exposures_by_expiry_strike`: GEX/DEX/vanna/charm exposures by ticker/date/expiry/strike, including ask/bid/OI/volume components where available.
- `oi_by_expiry`: call/put OI by ticker/date/expiry.
- `oi_by_strike`: call/put OI by ticker/date/strike.
- `oi_change_events`: contract-level OI changes.
- `iv_rank_history`: IV rank and IV rank changes by ticker/date.
- `iv_term_snapshots`: IV term structure and implied move by expiry/DTE.
- `interpolated_iv_snapshots`: standard tenor IV, percentile, and implied move.
- `realized_volatility_history`: realized volatility and stock price history.
- `risk_reversal_skew_history`: skew by ticker/date/expiry/delta.
- `max_pain_by_expiry`: max pain by ticker/date/expiry.
- `dark_pool_events`: repeated block prints and levels.
- `short_interest_snapshots`: short interest/utilization/DTC context where available.
- `tracked_items`: tracked contracts and expiry/tenor groups.
- `tracking_observations`: OI/IV observations for tracked items.
- `opportunity_scores`: score, setup types, confirmations, warnings, source attribution.
- `structure_ideas`: suggested structure candidates without sizing.

Use indexes on `run_id`, `ticker`, `option_symbol`, `market_date`, `fetched_at`, `expiry`, `strike`, and `(ticker, expiry, strike)`.

## Scoring And Tracking

The scoring engine starts from the extracted scan logic in `legacy-unusual-whales/docs/scan-logic-from-skill.md`.

Primary flow conviction:

- Volume greater than OI.
- Ask/bid aggression.
- Premium size.
- Single-leg versus multi-leg.
- Moneyness.
- DTE.

Confirmation and warning layers:

- IV change and IV rank change.
- OI change and OI concentration by expiry/strike.
- PCR and net flow context.
- Risk reversal/skew.
- GEX/DEX/vanna/charm exposure.
- Max pain distance.
- Dark pool confirmation.
- Short squeeze context.
- Earnings proximity.
- Liquidity and stale-data warnings.

Tracking is hybrid:

- Auto-track high-conviction flow rows.
- Auto-track important expiries/tenors for TradingView watchlist tickers.
- Allow manual pinning from the UI.
- Reconcile later OI and IV snapshots against the original flow to classify likely opening, closing, rolling, fading, hedge, or unknown.

OI is not truly live intraday. The app should make this explicit and reconcile next-session OI changes when available.

## Structure Ideas

V1 includes trade structure candidates but no sizing. Each structure idea must include a reason and invalidation/warning notes.

Example mapping:

- Deep conviction call flow: call debit spread or long call candidate.
- Deep conviction put flow: put debit spread or long put candidate.
- High IV / earnings IV crush: defined-risk credit spread or iron condor candidate.
- Squeeze setup: small defined-risk call spread or call fly candidate.
- GEX pinning / max pain: iron fly or short premium candidate around pin when liquidity is acceptable.
- Skew/vol anomaly: calendar/diagonal or risk reversal candidate where appropriate.

Position sizing is deferred. Portfolio-aware sizing is a later phase.

## UW API Capability Matrix

The app should cite and use current UW public REST docs as primary references.

### Flow

- Flow Alerts: https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts
- Full Tape: https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.full_tape
- Contract Flow Data: https://api.unusualwhales.com/docs/operations/PublicApi.OptionContractController.flow

### Option Surface

- Option Chains: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.option_chains
- Option Contracts: https://api.unusualwhales.com/docs/operations/PublicApi.OptionContractController.option_contracts

UW can query the option surface per ticker/date. `option-chains` returns contract symbols. `option-contracts` returns paginated contract snapshots with contract IV, OI, previous OI, volume, premium, side volumes, sweep volume, and prices. Full surface capture requires pagination.

### Greeks And Exposures

- Greeks: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greeks
- Greek Exposure: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure
- Greek Exposure By Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure_by_expiry
- Greek Exposure By Strike: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure_by_strike
- Greek Exposure By Strike And Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure_by_strike_expiry
- Spot Exposure By Strike: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.spot_exposures_by_strike
- Spot Exposure By Strike And Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.spot_exposures_by_strike_expiry_v2

UW can query full greeks by expiry and strike. It exposes delta, gamma, theta, vega, rho, vanna, charm, and call/put IV. Exposure endpoints provide GEX/DEX/vanna/charm context by aggregate, expiry, strike, and strike+expiry. Spot exposure endpoints include ask/bid/OI/volume exposure components.

### OI

- OI Change: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_change
- OI Per Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_expiry
- OI Per Strike: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_strike
- Volume And OI Per Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.volume_oi_per_expiry

### Volatility, Skew, And VRP Proxy

- IV Rank: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.iv_rank
- Volatility Statistics: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.volatility_stats
- IV Term Structure: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.implied_volatility_term_structure
- Interpolated IV: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.interpolated_iv
- Historical Risk Reversal Skew: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.historical_risk_reversal_skew
- Realized Volatility: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.realized_volatility

UW provides IV rank, IV history, IV/RV stats, term structure, interpolated IV, implied moves, and historical risk reversal skew. A clearly documented public REST endpoint for named VRP/variance risk premium was not found during design. V1 should compute a practical VRP proxy from UW fields, for example implied volatility minus realized volatility, and store it as a derived value.

### Max Pain, Dark Pool, Shorts

- Max Pain: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.max_pain
- Recent Darkpool Trades: https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.recent
- Ticker Darkpool Trades: https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.ticker
- Short Screener: https://api.unusualwhales.com/docs/operations/PublicApi.ShortController.short_screener
- Short Data: https://api.unusualwhales.com/docs/operations/PublicApi.ShortController.short_data

## Request Minimization Strategy

UW is mostly ticker-scoped rather than broad batch-scoped, so v1 should use a tiered acquisition planner.

Tier 1: broad discovery

- Poll available broad flow endpoints such as flow alerts and full tape.
- Import TradingView shared watchlist symbols.
- Deduplicate ticker, option symbol, expiry, and source rows.

Tier 2: cheap ticker enrichment

- Fetch option contracts with filters.
- Fetch OI per expiry and OI per strike.
- Fetch max pain.
- Fetch IV rank, volatility stats, term structure, and interpolated IV.

Tier 3: targeted deep surface

- For high-score tickers/contracts only, page full option contracts.
- Fetch greeks only for important expiries.
- Fetch spot exposures by strike/expiry with `expirations[]`, strike windows, and pagination.
- Fetch contract flow for exact tracked contracts.

Tier 4: tracking refresh

- For tracked exact contracts, use `option_symbol[]` on option-contract endpoints where possible.
- Refresh OI/IV/greeks for important expiries and strikes.
- Avoid re-fetching unchanged `(endpoint, params, market_date)` combinations inside the same polling cycle.

Persist request fingerprints so repeated runs can reuse cached data where appropriate.

## Error Handling

- Missing UW API key: allow snapshot mode and show setup instructions.
- UW rate limit or transient failure: preserve partial results, show degraded-source warnings, and write failed request audit rows.
- TradingView shared URL parse failure: keep the source tab visible with failure state and no symbols.
- No flow rows: show watchlist enrichment and snapshot options.
- Stale OI: label reconciliation as pending or stale rather than guessing.
- Missing greeks/exposure for an expiry: score without that layer and show a warning.
- Pagination incomplete: mark the surface snapshot as partial.

## Testing

Unit tests:

- API request builder and pagination planner.
- Option symbol parsing.
- Normalizers for UW response examples.
- Scoring rule cases.
- Structure idea mapping.
- OI/IV reconciliation labels.
- Postgres insert/load helpers.

Integration tests:

- Create `uw_scan` schema in a test database.
- Persist a synthetic scan run and reload it.
- Snapshot replay renders equivalent opportunity rows.

UI smoke tests:

- Streamlit starts.
- Main tabs render.
- Snapshot mode works without UW API key.
- A mocked polling run populates Top Opportunities, UW Flow Feed, TradingView Watchlists, Tracked Contracts, Surface Explorer, and Snapshots.

## First Layout Direction

The first Streamlit layout should implement the shell before full data integration:

- Sidebar controls for run mode, polling interval, UW API key status, TradingView shared URLs, thresholds, run scan, save snapshot, and load snapshot.
- Tabs: Top Opportunities, UW Flow Feed, TradingView Watchlists, Tracked Contracts, Surface Explorer, Snapshots.
- Mock or fixture-backed tables/cards matching the final data model.
- No real trading logic hidden in the UI layer; the layout consumes typed view models.
