# web/components — React components

## Three subtrees

```
components/
├── shared/        # cross-page chrome: Sidebar, HealthPanel, RescanButton, ScanAllButton
├── watchlist/     # landing-page card grid (TickerCard, FilterBar, CardGrid, blocks/badges)
└── stock/         # per-ticker detail page
    ├── DetailHeader.tsx, TabBar.tsx
    ├── tabs/      # one client component per tab (FlowTab, VolatilityTabClient, etc.)
    └── panels/    # the actual chart / tile components consumed by tabs
```

## Conventions

- **Tabs are Client Components.** They poll, hold local UI state, and orchestrate panels.
- **Panels are mostly pure.** Hand-rolled SVG; props in, SVG out. The canonical chart wrapper is `panels/AnalyticalSeriesPanel.tsx` (title + subtitle frame).
- **Tile pattern** lives in `panels/VolMetricsCard.tsx` and `panels/GexLevelTiles.tsx`. Inline `Tile` component, not a shared abstraction — when both grow we'll extract; until then YAGNI.
- **Color tokens via `var(--…)`:**
  - `--positive` / `--negative` / `--warning` for signed/threshold values
  - `--text-primary` / `--text-muted` / `--text-secondary` for prose
  - `--bg-panel` / `--border-dim` for chrome
  - `--accent-bg` / `--accent-warm` / `--accent-vol` / `--accent-vivid` for chart series
- **Color helpers stay inside the consuming file** (e.g., `vrpColor`, `ivRankTercileColor`). Don't extract until 3+ callers need them.
- **Scale gotchas:**
  - `iv_rank` and `iv_rank_1y` are 0–100 → `fmtDecimal(v, 0)` directly
  - `iv_percentile_30d` is 0–1 → multiply by 100 before `fmtDecimal(v, 0)`
  - `vrp` / `skew_25d` are signed decimals → `fmtSigned`
- **No charting library.** Hand-rolled SVG using `lib/svgChart.ts` helpers.
- **Accessibility:** `role="img"` on chart SVGs, meaningful `<title>` where the tile encodes signed info.
