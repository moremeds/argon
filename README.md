# Unusual Whales Opportunity Scanner

Streamlit-based opportunity scanner for Unusual Whales options flow data. Produces two canonical reports: a per-ticker analysis card (market structure, volatility, flow, VRP assessment, defined-risk trade plan) and a market-wide scan card (setup classification, day-over-day flow reversals, top pick + secondaries).

## Status

This repository was reset on 2026-05-11. The prior implementation was scrapped; the rebuild starts from the contracts defined in the spec.

- Spec: [`docs/superpowers/specs/2026-05-11-uw-scan-design.md`](docs/superpowers/specs/2026-05-11-uw-scan-design.md) — canonical report formats and implementation guardrails.
- Plan: [`docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md`](docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md) — slice-by-slice rebuild plan.

## Local Setup

Source code lands in the repository as slices ship. Until S0 (endpoint validation spike) lands, the only setup is dependency installation:

```bash
uv sync --extra postgres
uv run playwright install chromium
cp .env.example .env
# Put the real UW token in .env as UW_SCAN_API_KEY. Do not commit .env.
```

## Database

Local Postgres database `option_wizard`, schema `uw_scan`. Migrations and integration tests run against a real local Postgres — fake cursors are explicitly banned (see Implementation Guardrails in the spec).
