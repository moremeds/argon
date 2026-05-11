# Unusual Whales Opportunity Scanner Design

Date: 2026-05-11

## Goal

Build a Streamlit app that shows potential options opportunities from Unusual Whales data and TradingView shared watchlists. The app should support live REST polling and saved snapshot replay, persist queryable historical data into local Postgres, and help answer whether unusual option flow is likely opening, closing, rolling, fading, or worth tracking.

This is not a trade execution system. It presents evidence, structure candidates, warnings, and tracking context.

## Reset Status

This repository was reset on 2026-05-11 after a prior implementation attempt was scrapped. The prior attempt produced a thorough imitation of a working scanner — typed, tested, modular — but failed three of the spec's core requirements:

1. Schema tables existed but were not populated by the live pipeline (`raw_payloads`, `api_request_audit`, `option_contract_snapshots`, greeks, exposures, and most others).
2. Pipe-delimited TEXT columns were used in place of normalized relational shape, in direct violation of this spec's primary storage rule.
3. TradingView shared watchlists were "degraded" — the spec's source of truth was offline.

The new plan rebuilds V1 from scratch using vertical slices. Each slice ships one end-to-end working feature with real persistence, real Postgres tests, and full error surfacing. The two report formats below are the canonical output contracts; all data infrastructure exists to produce them. See `docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md` for the slice-by-slice plan.

## Repository And Database

- Python layout: conventional `src/uw_scan/` package modules, `app/` for Streamlit entrypoints, `tests/` for tests, and `docs/` for specs/plans.
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

V1 is delivered as **vertical slices**, each shipping one end-to-end working feature (UI → pipeline → API → persistence → reload) with full Implementation Guardrail compliance. Slice ordering, file ownership, and exit gates are owned by `docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md`. Horizontal-layer planning (build all clients, then all storage, then all UI) is explicitly rejected as the failure mode that produced the prior reset.

## Report Formats

V1 has two canonical report outputs. These are the contracts the implementation must satisfy. All data infrastructure (endpoints, normalizers, storage tables, scoring rules) exists to produce them. If a field is shown in either example, the rebuild plan must answer: which UW endpoint supplies it, which table persists it, and which derivation produces it.

### Single-Stock Analysis Card

Per-ticker deep-dive showing market structure, volatility, flow and positioning, VRP assessment, and a defined-risk trade plan. Rendered as a Streamlit section. This is the Slice 1 deliverable.

```
TSLA — $380.88 — BUY

TSLA sits just above the GEX flip at $376 in positive gamma territory, but a
massive $100M gamma wall at $382.50 caps immediate upside. Bullish flow (+$524M
net premium) and historically cheap IV (rank 3.37) favor buying calls for a
breakout above the wall. Short interest below average supports accumulation thesis.

Score              +31/100
IV Rank            3.4/100
IV / HV            42.0% / 31.1%
Skew               Put skew (1.4%)
Term Structure     Contango (normal)
Vol Regime         Low (rank 3.4)
Net Premium (1d)   +$524.3M
C/P Ratio          0.94
GEX Flip           $376.25 (above)
Short Int          43.7% [T+1]
OI Signal          Bullish [T+1]
Data               3/24/2026

Scenarios
  Break $382.50 wall → $392-$400 target
  $375–$385 range-bound (GEX pinning)
  Lose $370 support → $360 gap fill

Conviction         B — Moderate | Top: Cheap IV + bullish flow
Risk               $382.50 GEX wall may cap upside
Watch              Break above $382.50 with volume

Market Structure (score: +8/28)
  Strike   | Net GEX        | Level
  ---------+----------------+-------------
  $382.50  | +$100.4M       | RESIST ★
  $392.50  | +$28.2M        | RESIST
  $400     | +$20.7M        | RESIST
  $376.25  | ~0             | FLIP ◀
  $375     | -$17.9M        | SUPPORT
  $370     | -$44.2M        | SUPPORT ★
  $350     | -$42.8M        | SUPPORT

  GEX Flip           $376.25 — 1.2% below live price $380.88
  Dealer Positioning Positive Gamma — dealers sell rallies, buy dips
  Volume DEX         $380 saw $152.5M vol gamma
  Charm Bias         Neutral at current level; negative above $400
  Vanna Bias         Positive above $400 — vol drop would push price up

Volatility (score: +8/28)
  IV / HV            42.0% / 31.1% (spread: +10.9%)
  IV Rank            3.4/100 (extremely cheap)
  52w IV Range       39.3% – 107.2%
  52w RV Range       28.5% – 112.9%
  VRP                7.6% (thin premium)
  Skew               Put skew — 25δ Put ~41.6% vs Call ~40.2% (Δ1.4%)
  Term Structure     Contango (20 expirations)
                     Near: 38.6% (11 DTE) → Mid: 41.5% (29 DTE) → Far: 45.0% (91 DTE)

Flow & Positioning (+8/24 + +7/20)
  Net Premium        +$524.3M
  Bull / Bear Prem   $2.29B / $1.77B
  C/P Ratio          0.94
  Dark Pool          $2.3M (8 prints) — no conviction
  Top Expiries       Mar 20: +$463M (0DTE opex) | Apr 17: +$94M (29 DTE)
                     May 15: -$11M | Dec 2028: -$17M (LEAPS)
  Short Interest     Ratio 43.7% (z: -0.78, below average)
  OI Changes
    Strike  | Call Vol  | Put Vol
    --------+-----------+----------
    $385    | 136,564   | 56,586    ← call heavy
    $390    | 114,894   | 52,794    ← call heavy
    $380    | 106,881   | 167,016   ← put heavy
  Bias: Bullish above $385
  Squeeze Risk: Low (TSLA too liquid for traditional squeeze)

VRP Assessment — DO NOT SELL
  IV rank at 3.4/100 is near the 52-week floor — options are historically cheap.
  VRP z-score 0.28 is below entry threshold. Worst time to sell premium.
  VRP          7.6% (IV 42.0% − RV 31.1%)
  Z-Score      0.28
  IV Pctile    3.4/100
  Term Struct  Contango (ratio 0.86)
  GEX Regime   Positive — dealers stabilizing
  Signal       DO NOT SELL
  Reason       Failed: VRP z-score < 0.5, IV rank < 30

Bull Call Spread — TSLA
  Buy $385 Call / Sell $400 Call — Apr 17, 2026 (24 DTE)
  Est. Debit         ~$6.40
  Max Profit         ~$8.60
  Max Loss           ~$6.40
  R:R                1.34:1
  IV at Entry        ~42% (rank 3.4)

  Reasoning: IV rank 3.4 makes this the cheapest TSLA vol in a year — ideal for
  buying premium. The $382.50 GEX wall is massive resistance, but +$524M net
  premium and bullish OI above $385 suggest institutional positioning for a move
  higher. Breakout above $382.50 would target $392.50 and $400 GEX walls.

Management Plan
  • Take profit: $393-$395 (~50% of max profit)
  • Stop loss: ~$3.20 (50% of debit)
  • GEX stop: Close if TSLA closes below $370
  • Time stop: Review Apr 3 (14 DTE) · Close by Apr 10 (7 DTE)
```

### Full Scan Report

Market-wide screening across a universe (TradingView shared watchlist or hardcoded fallback), classifying tickers into setup types, ranking by conviction score, surfacing day-over-day flow reversals, and identifying a single top pick with secondary watchlist. This is the Slice 2 deliverable, with day-over-day deltas added in Slice 3.

```
UW Full Scan — Mar 20, 2026
Full scan completed — Mar 20 2026 ~7:40 AM ET

Screened 40 tickers via net-premium API (Mar 19 flow data) → 15 showed
significant one-sided flow → 8 classified into setup types.

Dark pool cross-referenced: NVDA (6 prints, $1.87M) and ORCL (4 prints, $2.28M)
flagged as multi-signal confluence.

Notable shift: ORCL and MSTR both reversed from heavily bearish (Mar 18) to
bullish (Mar 19). TSLA maintains massive +$658M bullish flow for second
consecutive day.

Scan Mode          Full (all 6 signal tiers)
Data Date          Mar 19 flow + Mar 20 DP
Market Context     IVs near 52w lows across board

Setup Candidates (8 found)
  Ticker | Type      | Score | Key Metric            | IV Rank
  -------+-----------+-------+-----------------------+--------
  TSLA   | C (Bull)  | 5/5   | +$658M net, IV=0!     | 0.0
  ORCL   | F (C+E)   | 4/5   | +$96M + 4 DP $2.3M    | 45.0
  NVDA   | F (C+E)   | 4/5   | +$19M + 6 DP $1.9M    | 15.6
  MU     | A (Earn)  | 4/5   | IV 65.7 + $1B prem    | 65.7
  MSTR   | C (Bull)  | 4/5   | +$187M (reversed!)    | 27.8
  COIN   | C (Bull)  | 3/5   | +$88M net, CP 1.16    | 35.1
  META   | C (Bear)  | 3/5   | -$105M net prem       | 15.7
  AMZN   | C (Bull)  | 3/5   | +$11M, CP 2.03        | 17.6

Setup Type Legend
  A = Earnings IV Crush
  C = Deep Conviction
  E = Dark Pool
  F = Multi-Signal Confluence

Day-over-Day Changes
  ORCL  Flipped from -$196M (Mar 18) to +$96M (Mar 19) — massive reversal
  MSTR  Flipped from -$200M to +$187M — crypto sentiment shift
  TSLA  Sustained +$658M bullish for 2nd day — rare persistence

Top Pick: TSLA — Type C (Deep Conviction Bull, 5/5)
  Tesla dominates with the most extreme bullish signal in the scan: +$658M net
  premium with IV Rank at literal zero (52-week low). Rare combination — massive
  institutional bullish flow meeting historically cheap options.

  Signals
    • Deep Conviction Flow: +$658M net premium (top in universe)
    • IV at 52w floor: Rank 0 — options cheapest they've been all year
    • Dark Pool: 4 prints totaling $755K
    • GEX: Price on $380 support, flip at $381.25, resistance $395-$410

  Suggested Setup    Bull Call Spread $382.50/$395 — Apr 17 (28 DTE)
  Position Size      3% max portfolio · 1% max loss

Secondary Picks
  ORCL (Type F)  Flow reversal -$196M → +$96M, 4 DP prints ($2.28M). Bull call
                 spread candidate.
  NVDA (Type F)  6 DP prints ($1.87M), +$19M flow, C/P 1.83, IV Rank 15.6 cheap.
                 Target $185 GEX resistance.
  MU   (Type A)  IV Rank 65.7 + $1B premium. Earnings event. Iron Condor at
                 implied move width, or directional Bull Call.
```

### Setup Type Taxonomy

Four setup classifications drive the scan's `Type` column and the suggested-structure logic. Each ships in a defined slice:

| Code | Setup | Trigger | Slice |
|---|---|---|---|
| **C** | Deep Conviction Directional | Large single-sided net premium (≥ configurable threshold) with directional flow agreement (ask-side aggression, vol > OI, single-leg dominant) | S1, S2 |
| **F** | Multi-Signal Confluence | Two or more of (C, dark pool ≥ threshold, opening-interest build, IV anomaly) in the same ticker on the same date | S2 |
| **A** | Earnings IV Crush | Elevated IV rank (≥ 60) within N trading days of a known earnings date | S3 (requires earnings calendar source) |
| **E** | Dark Pool | Significant dark pool prints (≥ configurable count and notional) corroborating equity-side accumulation | S3 (requires darkpool persistence) |

V1 deliberately limits to these four; additional categories (skew anomalies, squeeze setups, GEX pinning) are noted as scoring confirmations but not promoted to top-level types until reports demand them.

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

Initial review of that URL shows the static HTML can expose watchlist metadata such as the page title, but not necessarily the watchlist symbols. The implementation plan must prove symbol extraction from one or more real shared URLs before the app relies on TradingView ingestion. If static parsing fails, v1 must try browser-rendered retrieval; only if rendered retrieval also fails should that source be marked degraded while the UW flow source continues.

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

- Poll live broad flow endpoints such as flow alerts.
- Treat full tape as dated archive/backfill retrieval (`/api/option-trades/full-tape/{date}`), not as a normal live polling call.
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

## External Validation Notes

Validated against current public documentation on 2026-05-11:

- UW Flow Alerts remains a live REST discovery endpoint at `/api/option-trades/flow-alerts`, with filters for ticker, premium, size, volume, OI, and opening-trade logic.
- UW Full Tape is date-scoped at `/api/option-trades/full-tape/{date}` with a required `YYYY-MM-DD` market date. It should be used for archive/backfill, not as a live polling source.
- UW option surface capture is ticker-scoped. `option-chains` lists contract symbols and `option-contracts` returns paginated contract snapshots under `/api/stock/{ticker}/option-contracts` with `option_symbol[]`, `limit`, and `page` filters.
- UW OI tracking is supported by `oi-change`, `oi-per-expiry`, `oi-per-strike`, and `volume-oi-expiry`.
- UW volatility tracking is supported by `iv-rank`, `volatility/stats`, `interpolated-iv`, `volatility/realized`, and `volatility/term-structure`. Named VRP was still not found as a public endpoint, so VRP remains a derived proxy from IV and realized volatility.
- UW greeks and exposure coverage is supported by `greeks`, `greek-exposure/strike-expiry`, and `spot-exposures/expiry-strike`. The websocket GEX channel exists but is plan-gated, so v1 remains REST polling only.
- Greeks and exposure endpoints are ticker-scoped but not ticker-only. `greeks` and `greek-exposure/strike-expiry` require an `expiry` query parameter; `spot-exposures/expiry-strike` requires `expirations[]`. The request planner must expand deep-surface calls per important expiry.
- The sample TradingView shared URL returned page metadata in static HTML, but symbols were not visible in the fetched HTML. Static parsing, browser-rendered retrieval, and per-source failure states are required in v1.
- `uv sync --extra postgres` is valid for optional dependencies, and `dev` dependencies belong in `[dependency-groups]` where `uv` syncs the default dev group.
- Browser verification needs `uv run playwright install chromium` before Playwright-backed checks, and Streamlit should be started with `uv run streamlit run app/streamlit_app.py`.

## Implementation Guardrails

These rules close specific regression paths observed in the prior implementation attempt. They are non-negotiable for V1 and are enforced by CI tests where possible.

1. **No field-name fallback chains in normalizers.** Read the exact key from a validated UW sample payload (saved under `docs/uw-samples/`), raise on absence. Banned pattern: `_first(record, "volume", "total_volume", "size", "volume_oi_ratio")` — silently coercing a missing field to a semantically different field is worse than a `KeyError`.

2. **No `except Exception:` that swallows the message.** Production code logs `repr(exc)` plus full traceback; user-facing surfaces show enough information for the user to act. Banned pattern: `f"failed: {type(exc).__name__}"`.

3. **No silent fallback to fixtures in production paths.** If live data fails, the report errors loudly with the cause. Fixtures exist only inside `tests/`. The app must not be able to render a dashboard from fake data without explicit user opt-in.

4. **Persistence is part of "done."** Every API response writes to `raw_payloads` plus `api_request_audit`. Every normalized row writes to its typed table. A CI integration test asserts row counts in every populated table after a live-shaped run. A slice is not done if its tables are empty.

5. **No fake-cursor tests for storage code.** Integration tests run against a real Postgres (local `option_wizard` DB with isolated test schema per pytest session). String-contains assertions on SQL strings are banned. Tests persist real rows through the repository, query them back, and assert semantic correctness.

6. **Rate limiter enforces, doesn't just display.** A token-bucket limiter honors UW rate limits and `Retry-After` on 429 responses. The sidebar budget preview reflects actual enforcement state, not estimation theater.

7. **No premature modules.** A module exists only when its content is needed by the current slice. Target: roughly 15 source files for the whole V1. A file under 50 lines is a code smell and should be inlined unless it has a clear independent purpose.

8. **No dead UI controls.** Every Streamlit sidebar input is captured into a typed `RunSettings` (or equivalent) object that flows to the pipeline. A CI test renders the app under `streamlit.testing` and asserts every control affects pipeline state.

9. **SQL arrays, not pipe-joined strings.** Multi-valued columns (`setup_types`, `confirmations`, `warnings`) use `TEXT[]` / `INTEGER[]`. Banned pattern: `"|".join(...)` for storing list data.

10. **Date column semantics are explicit.** Every date and timestamp column carries a SQL comment describing what it represents (`market_date` = trading date the data represents; `fetched_at_utc` = when this app received the row; `event_timestamp_utc` = trade execution time when supplied by UW). A CI test asserts at least one persisted run has `market_date != expiry`.

11. **Endpoint shapes are pinned to saved samples.** S0 of the rebuild plan saves a real UW payload per endpoint under `docs/uw-samples/<endpoint>.json`. Normalizers are unit-tested against those samples. If UW changes a response shape, S0 is re-run, the sample updates, and tests fail until the normalizer is updated. No normalizer ships without a corresponding sample.

12. **Report contracts come before infrastructure.** Each slice ships at least one user-visible piece of the Single-Stock Card or Full Scan Report defined above. A slice that builds only infrastructure with no visible output is not a valid slice.

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

Slice 1 ships the Single-Stock Card as the first user-visible deliverable. Layout sequencing is owned by the rebuild plan; this spec defines only the contracts (Report Formats above) and the guardrails (Implementation Guardrails above) the layout must satisfy.

See `docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md` for slice-by-slice layout sequencing, file ownership, and exit gates.
