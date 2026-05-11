# Unusual Whales Scanner Handover

Date: 2026-05-11

## Current State

Repository: `/Users/moremeds/projects/unusual-whales`

This repo currently contains validated design and implementation plans for a Streamlit-based Unusual Whales opportunity scanner. The implementation itself has not started yet.

Key docs:

- Design spec: `docs/superpowers/specs/2026-05-11-uw-scan-design.md`
- Foundation/layout plan: `docs/superpowers/plans/2026-05-11-uw-scan-foundation-layout.md`
- Data ingestion plan: `docs/superpowers/plans/2026-05-11-uw-scan-data-ingestion.md`
- Opportunity layer plan: `docs/superpowers/plans/2026-05-11-uw-scan-opportunity-layer.md`

Recent commits:

- `bb45d08 Validate UW scan plans against current docs`
- `b91bfb2 Fix UW deep surface request planning gaps`

Working tree was clean after the last commit.

## User Requirements

- Build under this repo directory: `/Users/moremeds/projects/unusual-whales`.
- Follow Python conventions:
  - `src/uw_scan/` for package code
  - `app/` for Streamlit entrypoint
  - `tests/` for tests
  - `docs/` for docs
- Do not create monolithic scripts or top-level one-off scripts.
- Use `uv` for dependency management and command execution.
- Use local Postgres database `option_wizard`, schema `uw_scan`.
- Store queryable normalized relational tables. Do not rely on JSON/JSONB for analysis.
- Raw payload storage is allowed only as compressed audit/replay storage.
- Every queried response and normalized result should be persisted.
- V1 features are required, not optional flags.
- Use polling only. No paid streaming/websocket dependency for v1.
- Use Streamlit to present potential opportunity results.
- Use TradingView shared watchlists as external source of truth. Do not maintain a separate local watchlist.
- Keep TradingView watchlist sources separated in UI.
- Track IV changes, OI changes, important expiries/tenors, and exact unusual-flow contracts.
- Support saved snapshots plus live API polling.
- Verification must include normal unit/integration tests plus browser-level Streamlit verification with Playwright MCP or Browser Use.

## Secret Handling

The user provided an Unusual Whales API token in chat. Do not commit it or write it into docs.

Use environment variable:

```bash
UW_SCAN_API_KEY=...
```

A token-fragment scan was run after the last commits and returned no matches.

## Validated External Premises

Checked against current public docs on 2026-05-11.

Unusual Whales:

- Flow alerts live endpoint: `/api/option-trades/flow-alerts`
- Full tape endpoint: `/api/option-trades/full-tape/{date}`
  - Treat as dated archive/backfill, not normal live polling.
- Option chains endpoint: `/api/stock/{ticker}/option-chains`
- Option contracts endpoint: `/api/stock/{ticker}/option-contracts`
  - Ticker-scoped. Exact contract refresh must include ticker.
- OI endpoints:
  - `/api/stock/{ticker}/oi-change`
  - `/api/stock/{ticker}/oi-per-expiry`
  - `/api/stock/{ticker}/oi-per-strike`
  - `/api/stock/{ticker}/option/volume-oi-expiry`
- Volatility endpoints:
  - `/api/stock/{ticker}/iv-rank`
  - `/api/stock/{ticker}/volatility/stats`
  - `/api/stock/{ticker}/interpolated-iv`
  - `/api/stock/{ticker}/volatility/realized`
  - `/api/stock/{ticker}/volatility/term-structure`
- Greeks/exposure endpoints:
  - `/api/stock/{ticker}/greeks` requires `expiry`
  - `/api/stock/{ticker}/greek-exposure/strike-expiry` requires `expiry`
  - `/api/stock/{ticker}/spot-exposures/expiry-strike` requires `expirations[]`
- Named VRP endpoint was not found. V1 should compute a derived VRP proxy from implied volatility and realized volatility.

TradingView:

- Sample URL: `https://www.tradingview.com/watchlists/326877343/`
- Static HTML appears to expose metadata/page title but not necessarily symbols.
- V1 must attempt static parse first, then browser-rendered retrieval with Playwright/Browser Use, then mark only that source degraded if both fail.

Tooling:

- `uv sync --extra postgres` is the setup path.
- Use `[dependency-groups] dev = [...]`, not a `dev` optional extra.
- Run Playwright browser install with:

```bash
uv run playwright install chromium
```

- Run Streamlit with:

```bash
uv run streamlit run app/streamlit_app.py
```

## Known Gaps And Risks

- Endpoint paths are validated, but response schemas, pagination behavior, entitlement behavior, and exact parameter combinations still need live smoke tests with the user's token.
- TradingView browser-rendered extraction may be brittle if TradingView requires login, blocks automation, changes DOM, or rate-limits access.
- Request budget math is an estimate. It must be calibrated after real endpoint pagination and payload size measurements.
- Local Postgres migrations are planned but not executed yet.
- Streamlit UI is planned but not implemented yet.
- Backtesting and markout are deferred to v2, but v1 persistence must preserve enough history for them.
- Browser-level UI verification is required after UI implementation, not yet run.

## Recommended Next Session Start

Start by reading:

1. `docs/superpowers/specs/2026-05-11-uw-scan-design.md`
2. `docs/superpowers/plans/2026-05-11-uw-scan-foundation-layout.md`
3. `docs/superpowers/plans/2026-05-11-uw-scan-data-ingestion.md`
4. `docs/superpowers/plans/2026-05-11-uw-scan-opportunity-layer.md`

Then execute the foundation plan first.

Required skill flow for next session:

- Use `superpowers:executing-plans` or `superpowers:subagent-driven-development`.
- Use `superpowers:test-driven-development` for implementation tasks.
- Use `superpowers:systematic-debugging` for any failing test or unexpected behavior.
- Use `superpowers:verification-before-completion` before claiming a milestone is done.

Suggested implementation order:

1. Scaffold package, `pyproject.toml`, README, `.env.example`, and first tests.
2. Add config and typed models.
3. Add fixture data and Streamlit shell.
4. Add request-budget estimator.
5. Add TradingView static and browser-rendered adapter.
6. Add schema migration foundation.
7. Run unit tests.
8. Start Streamlit and verify UI with Browser Use or Playwright MCP.
9. Move to data ingestion plan only after foundation plan passes.

## Last Verification Commands

These were run after the latest docs update:

```bash
git diff --check HEAD
git status --short
rg -n "<token-fragment-pattern>" .
```

Results:

- `git diff --check HEAD`: exit 0
- `git status --short`: clean
- token-fragment scan: no matches
