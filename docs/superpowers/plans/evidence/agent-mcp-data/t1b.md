# T1b evidence — technicals verdicts + distribution → web/lib

Worker: `argon-b-impl` (kind devin). Branch `feat/agent-mcp-data`, worktree
`/Users/chenxi/projects/argon/.worktrees/agent-mcp-data`. T1 accepted and
committed by the lead as `ac067eed`; T1b sits uncommitted on top per the
amended commit policy (no commits, no staging).

## Context loaded

- `/Users/chenxi/.claude/CLAUDE.md` (global rules)
- `/Users/chenxi/.config/devin/AGENTS.md` (global rules)
- `/Users/chenxi/projects/argon/.worktrees/agent-mcp-data/CLAUDE.md`
- `/Users/chenxi/projects/argon/.worktrees/agent-mcp-data/AGENTS.md` (symlink → CLAUDE.md; read once)
- `/Users/chenxi/projects/argon/.worktrees/agent-mcp-data/web/CLAUDE.md`
- `/Users/chenxi/projects/argon/.worktrees/agent-mcp-data/web/components/CLAUDE.md`
- Plan: `docs/superpowers/plans/2026-10-02-agent-mcp-data.md`
- Fixture provenance: `web/tests/fixtures/mcp/README.md`

- cwd: `/Users/chenxi/projects/argon/.worktrees/agent-mcp-data`
- Temp dir: `output/tmp/argon-b-impl/` (gitignored, `.gitignore:18`)
- Model: requested `swe-2-max`; observed `swe-2-max` (SWE-2 Max per CLI banner)

## What changed

- `web/lib/technicals/returnDistribution.ts` (new): `Bins`, `returnBins`
  (verbatim), `normPdf`, `RETURN_WINDOW`/`RETURN_NBINS` (60/21), and
  `returnDistribution(series)` → `{ n, mean, sd, skew, bins, normal }`. `skew`
  and `normal` (121 count-unit points) are non-null iff `n >= 20 && sd > 0` —
  the panel's old render gate, so output is identical.
- `web/lib/technicals/verdicts.ts` (new): `kinematicsReading` (verbatim),
  `alignmentBadge(a)` → `{ label, count, text }` ("BULL ALIGN 3/3"),
  `macdSignalText(dm)` → `{ text, key } | null` (key feeds the pane's color
  mapping; `DualMacdDetail` type moved here), `sigmoidRejectReason` (verbatim).
- `web/lib/magnetTiles.ts` (appended — the spec's allowed existing-lib option):
  `volumeTile(candles)` → `{ bars, ma, lastVol, lastVolMa, ratio }` (last 34
  candles, SMA20-of-volume over the full candle list then sliced, truthy-gated
  ratio verbatim), and `kinematicsLeg(closes, leg = 5)` → `{ v, accel }`.
- `ReturnHistogram.tsx`: renders from `returnDistribution(data.series)`; keeps
  the `n < 20 || !(sd > 0)` early return; re-exports `returnBins`/`Bins` (the
  unit test imports `returnBins` from this module — unchanged).
- `TechnicalsOscillators.tsx`: imports `kinematicsReading`/`alignmentBadge`,
  re-exports `kinematicsReading`; the badge JSX colors off `badge.label`
  (BULL→positive, BEAR→negative, MIXED→muted — same sign mapping as before).
- `TechnicalsPriceChart.tsx`: `macdSignal` keeps the exported
  `{text, color}` signature and the regex color cascade; text+key now come from
  `macdSignalText`. `DualMacdDetail` imported from verdicts; `fmtDecimal`
  import dropped (unused after the move).
- `TechnicalsDetailPanels.tsx`: `sigmoidRejectReason` imported from verdicts
  and re-exported (the sigmoid test imports it from this module — unchanged).
- `MagnetSubTab.tsx`: calls `volumeTile(data.candles)` and
  `kinematicsLeg(candles.map(close))`; `VOL_BARS`/`KIN` moved into the lib
  functions; formatting (`M`, `× avg`, `sgn`) stays in the component.
- Tests (new): `web/tests/lib/technicals/{returnDistribution,verdicts,magnet}.test.ts`.
  Fixture tests copy the pre-move inline expressions as oracles and deep-equal
  the lib output; literal anchors computed once from the frozen fixtures
  (2026-10-02). Verdicts tests cover each branch with literal inputs plus the
  AAPL frozen detail (t-stats ≈ 25.8/22.6/115.4 → confirmed uptrend;
  alignment 3 → BULL ALIGN 3/3; dual_macd BULLISH/NONE → "BULLISH";
  sigmoid r2 0.821 vs 0.742 → wrong-way clause).

## Verification (all from `web/`)

### `npm run test` — exit 0

```
 Test Files  166 passed (166)
      Tests  1306 passed (1306)
   Duration  13.67s
```

### `npm run typecheck` — exit 0

```
> uw-watchlist-web@0.13.13 typecheck
> tsc --noEmit
```

### `npm run lint` — exit 0

```
> uw-watchlist-web@0.13.13 lint
> eslint .
```

### Targeted run — exit 0

`npx vitest run tests/lib/technicals tests/unit/return-histogram.test.tsx tests/unit/technicals-macd.test.tsx tests/unit/sigmoid-fit-chart.test.tsx`

```
 Test Files  8 passed (8)
      Tests  86 passed (86)
```

Existing tests pass unmodified: `return-histogram.test.tsx` (imports `returnBins`
from the panel), `technicals-macd.test.tsx` (imports `macdSignal` from the
chart), `sigmoid-fit-chart.test.tsx` (imports `sigmoidRejectReason` from the
detail panels).

### Node-compat smoke

`esbuild` bundle of `returnDistribution`/`verdicts`/`magnetTiles` +
`technicalsOverlays` ran in plain `node` (format=cjs, platform=node) — no DOM or
chart imports in the extracted modules:

```
dist aapl {"n":60,"mean":0.00250425958803994,"sd":0.02020646143296038,"skew":-0.9805203821666229}
mag  aapl {"lastVol":86249183,"lastVolMa":43466308.45,"ratio":1.9842766978754092,"v":0.23126898469907342,"accel":-0.002983688016722219}
```

### Forbidden imports — clean

`grep -rnE "react|lightweight-charts|fancy-canvas" web/lib/technicals/ web/lib/magnetTiles.ts` → no matches (exit 1).

### Scope

`git status`/`git diff --stat` touch only owned files:

```
 M web/components/stock/panels/ReturnHistogram.tsx
 M web/components/stock/panels/TechnicalsDetailPanels.tsx
 M web/components/stock/panels/TechnicalsOscillators.tsx
 M web/components/stock/panels/TechnicalsPriceChart.tsx
 M web/components/stock/tabs/technicals/MagnetSubTab.tsx
 M web/lib/magnetTiles.ts
?? web/lib/technicals/returnDistribution.ts
?? web/lib/technicals/verdicts.ts
?? web/tests/lib/technicals/{magnet,returnDistribution,verdicts}.test.ts
?? docs/superpowers/plans/evidence/agent-mcp-data/t1b.md
```

## Fixes during verification (test-side only)

- `verdicts.test.ts` beats-linear literal said 90% for input 0.85 → corrected to
  85% (the function's output was right).
- `returnDistribution.test.ts` degenerate case expected n=30 for 30 closes →
  corrected to 29 (returns are n−1).
- `verdicts.test.ts` needed `?.` on `AlignmentBadge | null` accesses — typecheck
  error, fixed.

No component/rendered expectation changed; no existing test edited.

## Deviations

- Magnet tile prep went into `lib/magnetTiles.ts` (spec allowed
  `lib/magnetTiles.ts` or `lib/technicals/magnet.ts`; the former already owns
  `sma`/`velocity` and the magnet-tile math docstring).
- `MACD`'s `key` (raw, un-uppercased) is returned alongside `text` because the
  pane's color cascade needs it — the `.toUpperCase()` stays with the color
  code in the component.
