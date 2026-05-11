# Unusual Whales Opportunity Scanner

Streamlit dashboard for spotting and tracking options opportunities from Unusual Whales data and TradingView shared watchlists.

## Local Setup

```bash
uv sync --extra postgres
uv run playwright install chromium
cp .env.example .env
```

Put the real Unusual Whales token in `.env` as `UW_SCAN_API_KEY`. Do not commit `.env`.

## First Layout

```bash
uv run streamlit run app/streamlit_app.py
```

## Current Phase

The current implementation is fixture-backed. It verifies the dashboard shape, config loading, request-budget preview, TradingView watchlist adapter contract, and schema migration foundation.

Live UW API polling is required v1 scope and is implemented after the request audit and normalization layer are in place.

## V1 Implementation Phases

| Phase | Coverage |
|---|---|
| Foundation layout | View models, fixture UI, request budget, TradingView static/browser adapter, schema foundation |
| Data ingestion | UW endpoint registry, audit, normalization, schema expansion, request planner |
| Opportunity layer | Scoring, structure ideas, tracking reconciliation, pipeline boundary, Streamlit mode wiring |
| Production hardening | Real Postgres integration test execution, live UW smoke tests, operational browser-rendered TradingView reliability checks |

## TradingView Validation

The sample shared watchlist URL returns page metadata but did not expose symbols through static HTML or rendered Chromium validation in this environment. The app keeps that source degraded while fixture-backed UW flow and other dashboard views continue to render.
