# Argon System Panorama Design

## Goal

Create one explorable, Chinese-language architecture panorama for personal technical audit. It must show Argon's real data movement, component boundaries, persistence, API/UI surfaces, AI execution, operations, and external-system relationships without changing business code.

## Reading model

The primary path runs left to right:

`external evidence and market data -> source adapters and workers -> analytical domains -> PostgreSQL -> FastAPI -> Next.js -> operator`

Short side branches show Xenon realtime/query paths, Trade Insights AI providers, job/control flow, and Docker/release operations. The main composition stays within Archify's 12-primary-node showcase limit; detailed modules, routes, worker roles, and data families live inside the nearest semantic node rather than becoming crossing-heavy standalone nodes.

## Scope

- External sources: Unusual Whales, Massive, Xenon/IB, mounted Livewire lake, official macro/public sources, Codex, Claude, and DeepSeek.
- Runtime ingestion: UW and Massive APScheduler roles, standalone WS consumer, AI provider-pinned workers, FastAPI-enqueued jobs, migrations.
- Analytical domains: watchlist/cards, options surface and Greeks, volatility/skew/flow/GEX, regime and VRP, macro/rates/gold, fundamentals/radar/research reports, technicals and positions.
- Persistence: PostgreSQL schema `uw_scan`, warm-store reads, raw/audit evidence, queues, snapshots, research/backtest traces, AI results, and health/usage state.
- Serving: FastAPI router families, OpenAPI-generated TypeScript contract, Next.js App Router page families, admin/health controls.
- Operations: Docker Compose services, database isolation, GHCR release images, Watchtower deployment boundary, and health/freshness signals.

## Truth boundaries

- Repository evidence proves configured architecture, not that every optional provider or worker is currently healthy.
- Existing uncommitted repository changes are out of scope and remain untouched.
- Product names, module names, protocols, environment variables, ports, and API paths remain exact English identifiers inside Chinese prose.
- The diagram is static by default; no decorative motion is added.

## Acceptance

- Archify `architecture` showcase validation reports all nine artifact checks with zero composition errors and zero warnings.
- Delivery succeeds and reports specification/artifact hashes and byte counts.
- Browser evidence passes at 1440x900, 1600x1000, 1920x1080, and 2048x1320 without horizontal or vertical desktop overflow.
- A final image inspection confirms readable labels, an obvious main path, no misleading edge crossings, and balanced use of the largest viewport.

