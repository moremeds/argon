# web — Next.js 16 frontend

Argon dark theme, terminal aesthetic. Mono labels uppercase, hand-rolled SVG charts (no chart library, except lightweight-charts on the Technicals price pane).

## Stack

- Next.js 16 + React 19 (RSC by default, `"use client"` for interactivity)
- TypeScript, strict
- `@fontsource/inter` (sans) + `@fontsource/ibm-plex-mono` (mono)
- Vitest (unit) + Playwright (e2e)
- Types generated from FastAPI: `npm run gen:types` → `lib/types.ts`

## Layout

```
web/
├── app/                 # Next.js App Router (pages, layouts, RSC)
├── components/          # React components — 14 subtrees
│   ├── shared/          # cross-page chrome: AppShell, Sidebar, HealthPanel, QueueProgress, Rescan/ScanAll buttons
│   ├── watchlist/       # CardGrid + TickerCard + filters
│   ├── stock/           # Detail page tabs + panels
│   ├── regime/          # /regime subtab components (CRI, VCG, GEX, Canary, GRG, MacroShortVol, …)
│   ├── gold/            # /gold GOLD COMPASS cockpit
│   ├── macro/           # macro desk chrome: tabs.ts VALID_TABS registry + domain/ panels + overview/ scenes
│   ├── rates/           # /rates panels
│   ├── fundamentals/    # AI chain desk panels (CapexPanel, ChainMapPanel, ValuationPanel, CaseCards, …)
│   ├── radar/           # RadarTable — research triage surface
│   ├── reports/         # ReportView — versioned research report renderer
│   ├── positioning/     # PositioningScreenerTable
│   ├── positions/       # PositionsPanel + PnlChart (VRP macro entry-capture positions)
│   ├── scanner/         # /scanner candidates + discovery
│   └── vrp/             # /vrp panels
├── lib/                 # api.ts, formatters, types.ts (generated), svgChart.ts, chanlun.ts, chanlunSeg.ts, indicators.ts, volumeProfile.ts, priceChartData.ts, regime/, fundamentals/, lwc/, dashboardData, freshness, occ
└── tests/               # unit (vitest) + e2e (playwright); subdirs: components/, e2e/, fixtures/, lib/, unit/
```

## Conventions

- **Server Components for data fetching.** Pages call `api.*` at render time. Push `"use client"` to the leaf interactive component, not the page.
- **`export const dynamic = "force-dynamic"`** on pages that read `searchParams` and need to bypass the RSC Router Cache (see `app/page.tsx` — filter chip clicks).
- **Hand-rolled SVG.** Helpers live in `lib/svgChart.ts` (`linearScale`, `finiteDomain`, `pathFromPoints`). Don't pull in `recharts` / `d3` / `visx`. **Two documented exceptions**, both using `lightweight-charts` + `lib/lwc/` primitives: (1) _2026-07-10_ the Technicals **price pane** (`components/stock/panels/TechnicalsPriceChart.tsx`); (2) _2026-08-02_ the **SPX density cone** on /regime (`components/regime/DensityConeChart.tsx`) — it needs a real dated x-axis, candlesticks, and pan/zoom, none of which the SVG helpers provide. Every other chart stays hand-rolled SVG.
- **Don't render a lightweight-charts component in vitest.** `fancy-canvas` calls `window.matchMedia`, which jsdom lacks — it surfaces as unhandled rejections while tests still "pass". Mock the chart component (`vi.mock("@/components/…Chart")`) and cover the canvas in a Playwright e2e spec instead.
- **Inline styles + CSS variables** (`var(--bg-panel)`, `var(--text-muted)`, etc.) — no styled-components, no CSS-in-JS lib. Tailwind utilities ARE used in the newer surfaces (`components/{fundamentals,radar,reports}/`, `app/chains`, `app/reports`); `components/{macro,rates,gold}/` instead use bespoke global CSS classes (`app/macro/board.css`, CSS modules) and older panels stay on inline styles + CSS variables.
- **Mono label style:** 10px, letter-spacing 1.5, uppercase, `var(--text-muted)`. Value: 22px bold mono, primary color. See the `Tile` component in `components/stock/panels/VolMetricsCard.tsx` for the canonical pattern.
- **Formatters** (`lib/formatters.ts`): `fmtPct`, `fmtSigned`, `fmtDecimal`, `toNum`. Use these — they handle null/string/number uniformly.
- **Never trust scale.** UW returns `iv_rank` 0–100 but `percentile` 0–1. Re-check the contract when wiring a new tile.

## Commands

```bash
npm run dev          # next dev (port 3001)
npm run typecheck    # tsc --noEmit
npm run lint
npm run lint:gold-copy       # scripts/lint-gold-copy.mjs
npm run test         # vitest
npm run test:e2e     # playwright
npm run test:e2e:technicals  # playwright --config playwright.technicals.config.ts (CI gate)
npm run gen:types    # regenerate lib/types.ts from FastAPI openapi.json
```

Two configs, deliberately: `playwright.config.ts` boots its own web+API stack,
`playwright.technicals.config.ts` boots the fixture-API stack instead (Playwright's
`webServer` is config-level and cannot be set per project, so a second stack needs a
second file). To run against servers you started yourself — a worktree stack, a
canary build on another port — use the default config with
`PW_NO_WEBSERVER=1 PLAYWRIGHT_WEB_PORT=<port>` rather than adding a config file.

After any backend model change, run `gen:types` and commit the diff. `lib/types.ts` is checked in (~525 KB / ~16.5k lines) — drift between API and client = bug.
