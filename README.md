# Unusual Whales Opportunity Scanner

Per-ticker options analytics, watchlist-driven. Next.js (web) + FastAPI (API) + APScheduler (worker) backed by Postgres, sourced from Unusual Whales and massive.com.

## Status

Active rework (2026-05-12) replaces the Streamlit prototype with a card-grid watchlist landing page and a regime-style detail page. Backend is additive on top of the existing `src/uw_scan/` pipeline; the prior Streamlit UI has been archived.

- Spec: [`docs/superpowers/specs/2026-05-12-uw-watchlist-ui-rework-design.md`](docs/superpowers/specs/2026-05-12-uw-watchlist-ui-rework-design.md)
- Plan: [`docs/superpowers/plans/2026-05-12-uw-watchlist-ui-rework-plan.md`](docs/superpowers/plans/2026-05-12-uw-watchlist-ui-rework-plan.md)

## Local Setup

```bash
uv sync --extra postgres
cp .env.example .env
# Fill in UW_SCAN_API_KEY and MASSIVE_API_KEY.

# Apply migrations against the local Postgres `option_wizard.uw_scan` schema:
bash scripts/migrate.sh

# Boot all three processes:
bash scripts/dev.sh
```

Next.js dev server: <http://127.0.0.1:3001>
FastAPI dev server: <http://127.0.0.1:8400>
FastAPI OpenAPI: <http://127.0.0.1:8400/openapi.json>

## Database

Local Postgres database `option_wizard`, schema `uw_scan`. Migrations and integration tests run against a real local Postgres — fake cursors are explicitly banned (see Implementation Guardrails in the spec).
