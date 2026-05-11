# Unusual Whales Opportunity Scanner Design

Date: 2026-05-11

## Goal

Build a Streamlit app that shows potential options opportunities from Unusual Whales data and TradingView shared watchlists. The app should support live REST polling and saved snapshot replay, persist queryable historical data into local Postgres, and help answer whether unusual option flow is likely opening, closing, rolling, fading, or worth tracking.

This is not a trade execution system. It presents evidence, structure candidates, warnings, and tracking context.

## Repository And Database

- Local repo: `/Users/moremeds/projects/unusual-whales`
- Python layout: use conventional `src/uw_scan/` package modules, `app/` for Streamlit entrypoints, `tests/` for tests, and `docs/` for specs/plans.
- Dependency manager: `uv`
- Postgres database: `option_wizard`
- Postgres schema: `uw_scan`
- Environment prefix: `UW_SCAN_`
- Primary storage model: typed relational tables
- Secondary storage model: raw JSON audit archive for debugging/replay

The app should not rely on JSON for analysis. All queryable data must be flattened into typed relational tables with usable numeric, timestamp, ticker, option symbol, expiry, strike, side, and source columns. JSON/JSONB is allowed for raw audit payloads and small `extra` fields only.

Secrets must never be committed. The Unusual Whales token is supplied at runtime through `UW_SCAN_API_KEY`. The repo should include a `.env.example` with sample keys only and a `.gitignore` entry for real `.env` files.

Do not create monolithic scripts. Executable entrypoints belong under `app/`; implementation code belongs under logical package subdirectories such as `src/uw_scan/api/`, `src/uw_scan/ingest/`, `src/uw_scan/storage/`, `src/uw_scan/sources/`, and scoring/tracking modules.

## Product Shape

Use a dual-source opportunity engine:

1. **UW Flow Feed**: REST polling of unusual option flow and related UW endpoints.
2. **TradingView Watchlists**: public/shared TradingView watchlist URLs remain the source of truth. The app imports each shared source during a run, saves the imported symbols, and keeps each watchlist separated in the UI.
3. **Tracked Contracts/Expiries**: high-conviction contracts and important expiry/tenor groups are tracked automatically, with manual pinning from the UI.

All sources feed one enrichment and scoring pipeline, but source attribution stays visible.

## V1 Scope

- New Streamlit dashboard delivered in implementation phases.
- Live REST polling only, no WebSocket.
- Snapshot replay from Postgres.
- UW flow feed plus TradingView shared watchlist source tabs.
- Auto-track high-conviction contracts/expiries.
- Manual pinning of contracts and expiry/tenor groups.
- OI and IV tracking for exact contracts and important expiries/tenors.
- OI/IV reconciliation labels: likely opening, closing, rolling, fading, hedge, or unknown.
- Opportunity scoring from the extracted scan logic.
- Suggested trade structures without sizing.
- Full option surface capability with required tiered acquisition to reduce requests.
- Raw API payload archive plus normalized relational tables.

V1 is a required product scope delivered in ordered implementation slices:

1. Layout shell with fixture-backed view models.
2. Postgres schema, migrations, and snapshot load/save contracts.
3. UW API client, request audit, pagination, and normalization.
4. UW flow source and TradingView shared watchlist source ingestion.
5. Scoring, structure ideas, and source attribution.
6. Tracking and conservative OI/IV reconciliation.
7. Targeted deep surface refresh and Surface Explorer.

## Deferred Scope

- Markout tables and dashboards.
- Backtesting dashboards.
- MFE/MAE/outcome statistics.
- Portfolio-aware sizing.
- Account/current-position ingestion.
- WebSocket upgrade.
- TradingView authenticated/session scraping.
- Automated trading or order placement.
- Full historical backfill from UW unless the account has the required historical option trades add-on.

## Streamlit Views

### Top Opportunities

Rank opportunities across UW flow and TradingView watchlist sources. Show source badges, score, setup type, suggested structure, warnings, IV/OI context, and track/pin controls.

### UW Flow Feed

Show polling feed of unusual option flow. Include filters for premium, ask/bid side, DTE, volume greater than OI, moneyness, single-leg/multi-leg, and contract type.

### TradingView Watchlists

Render one tab per shared watchlist source. Each tab shows imported symbols, latest UW enrichment, top contracts/expiries, IV rank changes, OI changes, and structure candidates.

TradingView shared watchlists remain external sources of truth. V1 should not edit or maintain local watchlists. Each source definition contains:

- Source label.
- Owner/person label when useful.
- Shared URL.
- Source type and status.

Each import run writes:

- Source URL and source label.
- Parse timestamp.
- Imported symbols.
- Failed or ignored symbols.
- Parser status and error message when applicable.

A TradingView parse failure must not block UW flow polling. The affected source tab should show the failure state and preserve the last successfully imported symbols when available.

Sample source for validation:

- `https://www.tradingview.com/watchlists/326877343/`

Initial review of that URL shows the static HTML can expose watchlist metadata such as the page title, but not necessarily the watchlist symbols. The implementation plan must prove symbol extraction from one or more real shared URLs before the app relies on TradingView ingestion. If static parsing fails, v1 must use a browser-rendered retrieval strategy or mark only that source as failed while the UW flow source continues.

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
- `uw_scan.scoring`: conviction score, setup classification, confirmation signals, and warnings.
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

Table grains and uniqueness rules:

- `scan_runs`: one row per logical polling/snapshot run.
- `source_feeds`: one row per configured source feed.
- `source_imports`: one row per `run_id + source_feed_id + symbol_or_contract`.
- `api_request_audit`: one row per executed or skipped request fingerprint per run.
- `raw_payloads`: one row per successful or failed response payload linked to `api_request_audit`.
- `flow_events`: one row per normalized UW flow event or unique trade row per run.
- `option_contract_snapshots`: one row per `run_id + option_symbol + fetched_at_utc`.
- `option_surface_snapshots`: one row per `run_id + ticker + market_date + expiry + page_number`.
- `greeks_by_expiry_strike`: one row per `run_id + ticker + market_date + expiry + strike`.
- `exposures_by_expiry_strike`: one row per `run_id + ticker + market_date + expiry + strike`.
- `oi_by_expiry`: one row per `run_id + ticker + market_date + expiry`.
- `oi_by_strike`: one row per `run_id + ticker + market_date + strike`.
- `oi_change_events`: one row per `run_id + option_symbol + oi_change_date` where UW supplies contract-level OI changes.
- `iv_rank_history`: one row per `ticker + market_date`.
- `iv_term_snapshots`: one row per `run_id + ticker + market_date + expiry`.
- `interpolated_iv_snapshots`: one row per `run_id + ticker + market_date + dte_bucket`.
- `realized_volatility_history`: one row per `ticker + market_date + window`.
- `risk_reversal_skew_history`: one row per `ticker + market_date + expiry + delta`.
- `max_pain_by_expiry`: one row per `run_id + ticker + market_date + expiry`.
- `dark_pool_events`: one row per normalized dark pool trade/print id per run.
- `short_interest_snapshots`: one row per `run_id + ticker + market_date`.
- `tracked_items`: one row per tracked contract or expiry/tenor group.
- `tracking_observations`: one row per `tracked_item_id + observed_at_utc + metric_family`.
- `opportunity_scores`: one row per scored candidate per run.
- `structure_ideas`: one row per opportunity score and structure type.

Schema changes should use explicit migrations. V1 can use SQL migration files or Alembic, but it must include:

- Idempotent `CREATE SCHEMA IF NOT EXISTS uw_scan`.
- Schema version tracking table.
- Repeatable local setup command.
- Test path that creates the schema in a test database and can be rerun safely.

Numeric values from UW must be parsed into typed columns. Many UW fields are returned as strings, so normalization should:

- Use Decimal-compatible parsing for money, price, IV, greeks, OI, volume, and exposure fields.
- Preserve nulls rather than coercing missing values to zero.
- Keep the original raw string only in the raw audit payload.
- Record parser errors in request/source audit rows without crashing the whole run.

All stored rows that represent observed market data should include both:

- `fetched_at_utc`: when the app received the data.
- `market_date`: the market date the data represents.

Rows tied to option flow should also include the trade/event timestamp from UW when available. OI-related rows should preserve any UW-provided current/previous date fields because OI is not truly live intraday.

Raw payload storage should use compressed `BYTEA` by default, linked from `api_request_audit` by `raw_payload_id`. Store `content_encoding`, `content_sha256`, `request_fingerprint`, `response_status`, and `payload_size_bytes`. Typed relational tables are the query surface; raw payload rows are retained for replay/debugging and parser upgrades.

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

OI is not truly live intraday. The app should make this explicit and reconcile next-session OI changes when available. Reconciliation should be conservative by default and use `unknown` unless evidence is strong.

V1 reconciliation heuristics:

- `likely_opening`: same contract OI increases after the flow by a meaningful amount and direction/side evidence is consistent with opening interest.
- `likely_closing`: same contract OI falls after large volume and price/side evidence is consistent with closing interest.
- `likely_rolling`: source contract OI falls while a nearby expiry or strike in the same ticker/side gains OI in the same reconciliation window.
- `fading`: original flow had high volume but no meaningful OI follow-through after next-session OI is available.
- `hedge`: flow conflicts with broader ticker/expiry context or occurs near known catalyst/earnings windows where hedge interpretation is more plausible.
- `unknown`: evidence is incomplete, stale, contradictory, or below thresholds.

Thresholds should be configurable, but v1 should start with conservative defaults such as requiring OI change to exceed both an absolute contract threshold and a percentage of observed flow volume.

Initial reconciliation defaults:

- `min_abs_oi_change`: 100 contracts.
- `min_oi_change_pct_of_flow_volume`: 0.25.
- `roll_strike_distance_pct`: 0.10 from underlying spot for nearby strike matching.
- `roll_expiry_window_days`: 45 calendar days from source expiry.
- `reconciliation_wait`: next available OI date after the flow date.
- `unknown_on_conflict`: true.

## Structure Ideas

V1 includes trade structure candidates but no sizing. Each structure idea must include a reason and invalidation/warning notes.

Example mapping:

- Deep conviction call flow: call debit spread or long call candidate.
- Deep conviction put flow: put debit spread or long put candidate.
- High IV / earnings IV crush: defined-risk credit spread or iron condor candidate.
- Squeeze setup: small defined-risk call spread or call fly candidate.
- GEX pinning / max pain: iron fly or short premium candidate around pin when liquidity is acceptable.
- Skew/vol anomaly: calendar/diagonal or risk reversal candidate when skew and tenor evidence supports it.

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
- Volume And OI Per Expiry: https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.vol_oi_per_expiry

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
- Recent Darkpool Trades: https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_recent
- Ticker Darkpool Trades: https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_ticker
- Short Screener: https://api.unusualwhales.com/docs/operations/PublicApi.ShortController.short_screener
- Short Data: https://api.unusualwhales.com/docs/operations/PublicApi.ShortController.short_data

## Request Minimization Strategy

UW is mostly ticker-scoped rather than broad batch-scoped, so v1 should use a tiered acquisition planner.

The app should expose request caps in the sidebar or config so polling cannot accidentally explode into full-surface scans for every source ticker. Initial defaults:

- Max UW flow rows consumed per polling cycle: 100.
- Max TradingView symbols imported per source: 200.
- Max watchlist tickers enriched per cycle: 50.
- Max deep-surface tickers per cycle: 8.
- Max important expiries per ticker for greeks/exposure: 4.
- Max option-contract pages per ticker in normal mode: 2.
- Full surface refresh is required for selected high-confidence tracked tickers and can also be triggered by explicit user action.
- Concurrency should be bounded and retry/backoff should respect UW rate-limit responses.

Before a live run, the UI should show a request-budget preview with estimated calls by tier. The planner should enforce a hard `max_requests_per_cycle` default of 250 and stop lower-priority enrichment before exceeding it.

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

Persist request fingerprints so repeated runs can reuse cached data when endpoint volatility and snapshot mode allow reuse.

Request fingerprints should include endpoint, normalized parameters, market date, source run, and API version/base URL. Within a polling cycle, duplicate fingerprints should be skipped. Across cycles, cached data can be reused only when the endpoint data is not expected to change intraday or when the user is replaying a snapshot.

Historical analysis has a hard data availability boundary. Without UW's historical option trades add-on, backtests and markouts can only use data captured by this app going forward plus any historical endpoints available under the current subscription.

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

Browser/UI verification:

- In addition to unit and integration tests, every Streamlit UI milestone needs a browser-level check with Playwright MCP or Browser Use.
- Start Streamlit with `uv run streamlit run app/streamlit_app.py`, open the local URL, verify the six main tabs are visible, and capture a screenshot or equivalent browser observation.
- UI verification failures block completion even if unit tests pass.

## First Layout Direction

The first Streamlit layout should implement the shell before full data integration:

- Sidebar controls for run mode, polling interval, UW API key status, TradingView shared URLs, thresholds, run scan, save snapshot, and load snapshot.
- Tabs: Top Opportunities, UW Flow Feed, TradingView Watchlists, Tracked Contracts, Surface Explorer, Snapshots.
- Mock or fixture-backed tables/cards matching the final data model.
- No real trading logic hidden in the UI layer; the layout consumes typed view models.
