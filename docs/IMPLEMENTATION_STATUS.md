# Implementation Status

Date: 2026-05-11

## Current Summary

The repository now has a working Streamlit app, a Python package under `src/uw_scan/`, live Unusual Whales flow polling, a computed analysis builder, SQL migrations, and Postgres snapshot save/load support. It is no longer only a static fixture demo, but it is also not the complete V1 product described in the plan.

The live app defaults to `Live polling` when `UW_SCAN_API_KEY` is configured. The latest verified live run fetched 100 UW flow rows, enriched the top-premium ticker set, built computed analysis boards, and saved/reloaded results from local Postgres.

## Done From Original Plan

- Created conventional repo layout: `app/`, `src/uw_scan/`, `tests/`, `docs/`.
- Added `uv` project metadata, README, `.gitignore`, `.env.example`, and `AGENTS.md`.
- Added environment config with `.env` support and test isolation for local secrets.
- Added typed Pydantic models for dashboard views, flow rows, opportunities, surfaces, snapshots, and stock analysis reports.
- Built Streamlit dashboard tabs for opportunities, UW flow, TradingView watchlists, tracked contracts, surface explorer, and snapshots.
- Added UW endpoint registry and REST client.
- Added live flow parsing from `/api/option-trades/flow-alerts`.
- Added live enrichment calls for IV rank, volatility stats, term structure, Greek exposure, spot exposure, OI per strike, and darkpool.
- Added computed stock analysis from structured inputs instead of copied prose.
- Added request-budget planning and caps.
- Added SQL migrations for the planned `uw_scan` schema.
- Applied migrations to local `option_wizard.uw_scan`.
- Added repository functions for migrations, snapshot save, snapshot list, and snapshot replay.
- Verified real Postgres snapshot save/replay.
- Added first-pass scoring, structure ideas, and OI reconciliation helpers.
- Added TradingView static/rendered parsers with tests.
- Added browser verification for Streamlit live mode and snapshot loading.

## Supplement Requests Addressed

- Detailed single-stock report format: implemented as generated `StockAnalysis`, not static copied text.
- “Why still fixture?”: fixed default mode so the app opens in live mode when a key is configured.
- “Why only SMH?”: replaced first-ticker-only enrichment with ranked distinct tickers by total absolute live premium.
- “Why only three tickers?”: added `UW_SCAN_MAX_ANALYSIS_TICKERS`, default `3`, because each ticker currently costs about seven enrichment calls and eight tickers took roughly 46 seconds.
- Poor readability: replaced the long single-stock report with an `Analysis Board`, executive summary metrics, and section tabs.

## Current Live Selection Criteria

For each live polling cycle:

1. Fetch up to `UW_SCAN_MAX_FLOW_ROWS` UW flow rows.
2. Group rows by ticker.
3. Sum absolute premium by ticker.
4. Rank tickers by total premium, preserving first-seen order as tie-breaker.
5. Enrich the top `UW_SCAN_MAX_ANALYSIS_TICKERS` tickers.

This is simple and transparent, but not final. It favors premium concentration and may miss lower-premium names with better risk/reward, better OI follow-through, or stronger volatility setups.

## Missing Or Incomplete

- The live analysis is still heuristic. It does not yet fully match the intended institutional scan logic across all requested dimensions.
- The top-ticker selection should be upgraded from total premium only to a composite opportunity score using premium, volume/OI, side aggressiveness, IV rank, GEX proximity, OI concentration, liquidity, and stale-data penalties.
- Live enrichment is capped for speed and does not yet support background batches, caching, or incremental expansion from the UI.
- The `Run scan` button is mostly cosmetic because Streamlit reruns on mode changes; it should become an explicit scan trigger with run state.
- Snapshot replay reconstructs flow and opportunities, but does not yet rebuild the full computed analysis board from persisted normalized enrichment rows.
- Raw API audit helpers exist, but live endpoint responses are not yet persisted into `api_request_audit` and `raw_payloads`.
- Many V1 schema tables exist but are not populated by the live pipeline, including contract snapshots, full surfaces, IV history, term snapshots, exposures, OI changes, short interest, max pain, and structure ideas.
- TradingView parsing exists, but shared watchlist ingestion is not operationally wired into live runs or persisted with last-good-symbol fallback.
- Surface Explorer still uses simple fixture/table data rather than a real selected-ticker surface workflow.
- Tracking is partial: auto-track/manual pin UI, tracked item lifecycle, and next-session OI/IV reconciliation loops are not complete.
- Short interest, skew, max pain, and VRP are only partially mapped and need endpoint-specific calibration.
- The report presentation is improved but still needs a stronger dashboard information hierarchy, filters, and comparison views across analyzed tickers.

## Verification Performed

- `uv run pytest -v`: 56 tests passing.
- Live UW smoke: fetched 100 live flow rows.
- Live enrichment: built computed analyses for three top-premium tickers with default cap.
- Real Postgres migration: applied to `option_wizard.uw_scan`.
- Real Postgres replay: saved and loaded snapshot rows.
- Browser verification: live Streamlit page rendered `Mode: Live polling`, live flow notice, computed analyses notice, and the redesigned `Analysis Board`.

## Recommended Next Work

1. Replace premium-only ticker ranking with composite opportunity ranking.
2. Persist every live UW response through `api_request_audit` and `raw_payloads`.
3. Populate normalized enrichment tables used by the analysis board.
4. Rebuild snapshot replay from persisted normalized enrichment, not only flow/opportunity rows.
5. Wire TradingView shared watchlists into live runs with last-good-symbol preservation.
6. Add UI controls for analysis count, filters, selected ticker, and background enrichment progress.
