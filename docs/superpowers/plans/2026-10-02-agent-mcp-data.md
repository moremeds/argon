# Agent MCP — workstream B (data tools + `web/lib` extraction)

Spec: `docs/superpowers/specs/2026-10-02-agent-mcp-design.md`, which is binding. Its "Interface contracts" section governs.
Branch `feat/agent-mcp-data`, worktree `.worktrees/agent-mcp-data`, merging into `feat/agent-mcp`.
Lead for B: Claude Opus 5.5 session `argon-fa`. Cross-workstream coordinator: `argon-2e`.
Acceptance owned by B: spec items 2 (the bot's EMA, chanlun points and volume profile equal the UI's exactly, for 3 tickers) and 6 (extracted components stay green).

## Approach (one rule)

**Same inputs + same function = same value.** A tool reproduces a UI number by

1. fetching the SAME internal-API GET the component fetches (`ctx.apiGet`), then
2. calling the SAME `web/lib` pure function the component now calls.

Inline component math moves to `web/lib/*` first. The component is rewired to call the extracted function, with no behaviour change. Only then does a tool import it. No Python port, and no second implementation.

`ctx.db` is used only for the EOD-cache invalidation key. All data comes through `ctx.apiGet`, so the tools see exactly what the UI sees.

Precheck, done 2026-10-02: `lib/{indicators,chanlun,chanlunSeg,volumeProfile,fvg}.ts` bundle and run in plain Node. Tools never import `lib/lwc/*`, because it value-imports fancy-canvas. Any pure helper living in `lib/lwc/` (e.g. `buildStats`) moves into `lib/volumeProfile.ts`.

## Inventory (from 2026-10-02 Explore passes; line numbers approximate)

Technicals (browser-computed, `TechnicalsPriceChart.tsx:781-1073`, `TechnicalsTab.tsx`):

- Input layers:
  - `data = mergeLiveHead(api.technicals, api.technicalsLive)` (TechnicalsTab:236; wall-clock freshness of 900 s, so `now` must be injectable)
  - `full = data.series`
  - `rows = sliceSeriesByTimeframe(full, "1y")` (UI default timeframe)
- Computed on `full`, then cut to `time >= rows[0].as_of` for display:
  - EMA 5/20/50
  - BB(20, 2, population sd)
  - ATR band (Wilder 14 ×2 around the server's `sma20`)
  - volume MA50
  - HVE/HV1 markers (`oneYear` 252, `peakLen` 9)
  - low-vol markers (−25%)
- Chanlun: `computeChanlunFull(full rows with as_of,high,low,close non-null)` plus `divergenceTrend(clBars, divergences)` (window 200). The full structure is returned, not display-cut.
- Volume profile: the last 360 of `full` rows with all of OHLCV non-null, then:
  - `computeVolumeProfile(slice, 60, 70)`
  - `findSrZones(profile, slice, last.close)`
  - `findLvnLevels(profile, last.close)`
  - `buildStats` (POC/VAH/VAL/nearest S/R/bias), currently non-exported in `lib/lwc/volumeProfile.ts:152`
- FVG: `findFairValueGaps(rows with high/low non-null)` on the **timeframe-windowed** `rows`, with `maxCount` 6.
- Return distribution (`ReturnHistogram.tsx:20,52-76`, on `data`, live row included): window 60, 21 bins, sample sd, adjusted Fisher-Pearson skew, n ≥ 20.
- Verdicts:
  - `kinematicsReading` (TechnicalsOscillators:87)
  - alignment badge (:142-157)
  - `macdSignal` text (TechnicalsPriceChart:132)
  - `sigmoidRejectReason` (TechnicalsDetailPanels:~85)
- Magnet tiles (`MagnetSubTab.tsx:93-176`):
  - volume tile: 34 bars, SMA20 of volume
  - kinematics: `velocity`/`accel`, KIN 5
  - IV series ×100
- Server-served (pass-through; from `/technicals` and `/magnets`): SMA, dual MACD, RSI, z, RV20, kinematics, RS, forward returns, magnets, VWAP anchor.

Component-inline derivations to extract (the "~10 components"):

| #   | Component                                                                                                                                    | Derivation                                                                                                                                                                       | Tool            |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| 1   | `app/cockpit/[ticker]/CockpitVrpTab.tsx:63-74,135-147,217-223`                                                                               | VRP row z (population sd) + band mean±0.5sd                                                                                                                                      | ticker_snapshot |
| 2   | `app/cockpit/[ticker]/CockpitDealerTab.tsx:24-41,418-496`                                                                                    | group by expiry (first 6), nearest-expiry net vanna/charm totals, peak strike, per-point net                                                                                     | ticker_snapshot |
| 3   | `components/stock/panels/ChainFlowReadPanel.tsx:111-158`                                                                                     | call/put volume ratio + call-heavy/put-heavy/balanced (1.2/0.8), busiest strike, t1 count                                                                                        | ticker_snapshot |
| 4   | `components/stock/tabs/FlowTab.tsx:464-488`                                                                                                  | timeline totals + P/C volume / OI                                                                                                                                                | ticker_snapshot |
| 5   | `components/stock/panels/MagnetGammaBar.tsx:74-100`                                                                                          | top wall, Δ net GEX vs prev close (+%), flip distance                                                                                                                            | ticker_snapshot |
| 6   | `components/stock/panels/TermMovePanel.tsx:123-143`                                                                                          | front/back implied move read, highest move                                                                                                                                       | ticker_snapshot |
| 7   | `components/stock/panels/greeks/{CharmPanel,VannaPanel}.tsx`                                                                                 | per-strike net = call+put for the default expiry                                                                                                                                 | ticker_snapshot |
| 8   | `components/regime/GexSubTab.tsx:107-150,198-216,304-313`                                                                                    | `retagProfileForSpot` (already exported; move to lib) + live spot splice + live day change %                                                                                     | regime_state    |
| 9   | `components/regime/VolBackdropStrip.tsx:41,53-108`                                                                                           | live VIX/VIX3M ratio + contango/backwardation, per-symbol live % change, ratio sparkline join                                                                                    | regime_state    |
| 10  | `components/regime/CriSubTab.tsx:44-91,145-152,264-327`                                                                                      | `priorComponentScore` (exported; move to lib), prev closes, vvix/vix fallback, VIX Δ3d, SPX median filter                                                                        | regime_state    |
| 11  | `components/watchlist/CardGrid.tsx:12-87`                                                                                                    | `sectorRank`, `sizeValue`, `compareCards`, grouping + sort                                                                                                                       | market_overview |
| 12  | Technicals (`TechnicalsTab`, `ReturnHistogram`, `TechnicalsOscillators`, `TechnicalsPriceChart`, `MagnetSubTab`, `lib/lwc/volumeProfile.ts`) | `mergeLiveHead`/`isFresh`/`etSessionDate`/`sliceSeriesByTimeframe`, overlay bar-prep filters, return dist, kinematics verdict, macd text, VP `buildStats`, magnet velocity/accel | technicals_scan |

Out of scope for B: macro desk overview math (zone1–3) and scanner ordering. Both are reachable verbatim through A's `read` tool. If argon-2e wants them inside `market_overview`, a later task adds them.

## Tool contracts (B's proposal; sent to argon-2e 2026-10-02)

- **`technicals_scan(tickers?, fields?, timeframe? = "1y")`**
  - Universe: all active watchlist tickers (`GET /watchlist`).
  - Output: Columnar `{as_of:{eod,live}, columns, rows}`, one row per ticker, latest values.
  - Default compact `fields`, documented in the tool description: price, z, z_band, rsi14, rv20, dist_pct, composite, dual-macd signal text, kinematics verdict, ema5/20/50, bb_upper/lower, atr_upper/lower, vol_ma50, last HVE marker, chanlun last point + last zhongshu + resonance, vp poc/vah/val/nearest_s/nearest_r/bias, fvg count + nearest open gap, return skew.
  - `fields: ["*"]` gives everything, including full chanlun structure arrays and VP zones/LVNs.
  - EOD layer cached in-process per ticker. Invalidation key = `SELECT max(inserted_at) FROM uw_scan.technical_daily`, checked at most once per 60 s. Verified: the upsert (`storage/technicals_repository.py:114`) sets `inserted_at = now()` on conflict, so both the nightly refresh and the on-demand `/technicals/refresh` move the key.
  - Live layer fetched per call, merged with `mergeLiveHead` at read time.
  - Concurrency limit on `apiGet` fan-out (≤ 8 in flight).
- **`ticker_snapshot(ticker)`**: per-ticker object. Includes:
  - the technicals row for that ticker with `fields:["*"]`
  - derivations #1–#7 with their raw API inputs' key fields
  - `as_of` per section
  - A section whose fetch fails returns `{error}` for that section and does not fail the whole call.
- **`regime_state()`**: #8–#10, plus API pass-through of CRI/VCG/VRP-macro current state (EOD + live where the UI shows live), each with `as_of`.
- **`market_overview()`**: watchlist cards in CardGrid order (columnar) + chains. Card numbers come verbatim from `/watchlist`.

All tool output shapes are B-owned. `types.ts`, `server.ts` and `tools/index.ts` are not touched.

## Tasks (worker `argon-b-impl`, Devin `swe-2-max`; one dispatch per task, review gate after each)

- **T1 — Technicals spine (acceptance 2: EMA, chanlun, VP).**
  - Move these into `web/lib/technicals/*.ts`:
    - `mergeLiveHead` (with injectable `now`), `isFresh`, `etSessionDate`, `sliceSeriesByTimeframe`
    - the bar-prep filters (clBars, vpBars, fvgBars)
  - Move `buildStats` into `lib/volumeProfile.ts`.
  - Add `technicalsOverlays(data, timeframe)`, which returns EMA 5/20/50, BB, ATR band, vol MA50, HVE/low-vol markers, the full chanlun result + divergence trend, VP profile/zones/LVN/stats, and FVG.
  - **`TechnicalsPriceChart` consumes the `technicalsOverlays` result for these values instead of calling the primitives itself.** Parity is structural: the UI and the tool share one function.
  - Old export sites re-export, so existing test imports keep working.
  - Tests: `technicalsOverlays` on `tests/fixtures/mcp/{aapl,nvda,spy}_technicals.json` (frozen real payloads; see their README). Assert against values computed by the pre-extraction primitive calls, so the refactor is proven value-preserving. Also test `mergeLiveHead` with an injected `now`.
- **T1b — Technicals verdicts + distribution.**
  - Extract into `web/lib/technicals/*.ts`:
    - `returnBins` + skew
    - `kinematicsReading` + alignment
    - `macdSignal` text
    - `sigmoidRejectReason`
    - magnet velocity/accel + volume-tile prep
  - Components call them. Add unit tests on the same fixtures.
- **T2 — `technicals_scan` tool.** Implement it per the contract above. `ctx.apiGet` paths omit the `/api` prefix. Also add a bundle-purity vitest: esbuild-bundle `web/mcp/tools/*.ts` for node and assert the output contains none of `react`, `react-dom`, `lightweight-charts`, `fancy-canvas`. Add a vitest test with a stubbed `ToolCtx` fed a frozen real payload, asserting the columnar shape, the `tickers`/`fields` filters, and cache reuse/invalidation.
- **T3 — ticker_snapshot extractions #1–#7 + tool.** Rewire each component and add unit tests for the previously untested derivations (#1, #2, #4). Tool test on a stubbed ctx.
- **T4 — regime_state extractions #8–#10 + tool.** Same pattern.
- **T5 — market_overview extraction #11 + tool.** Same pattern.
- **T6 — Verification and parity (acceptance 2 + 6).**
  - Run `npm run test`, `typecheck` and `lint`, plus e2e for the affected pages: `golden-path`, `pin-toggle`, `regime-page`, `marketStructureGreekSubTabs`, `volatility-tab`, `magnet-view`, `test:e2e:technicals`.
  - Parity, acceptance 2:
    - **Structural.** UI and tool call the same `technicalsOverlays`, which the T1 review checks.
    - **Empirical: same inputs.** For 3 real tickers on the local stack, the tool's fetched payload must equal the page's network payloads (same `/technicals` + `/technicals/live` bodies). Run it with the same `timeframe` and a pinned `now`, or outside the 900 s live window so the live row is absent on both sides.
    - **DOM spot check.** The VP stats panel text (the only DOM-readable VP surface) must equal the tool's VP stats. EMA and chanlun are canvas, so their parity rests on the structural check.
  - The lead runs the stack and Playwright steps, and writes `output/mcp-parity/<date>.json`.

Per-task evidence: `docs/superpowers/plans/evidence/agent-mcp-data/t<n>.md`.
Commits: one milestone commit per accepted task on `feat/agent-mcp-data`, with no attribution trailers. Merge into `feat/agent-mcp` after T6 is green. The lead does the merge; the worker never pushes.

## Files

- B owns:
  - `web/mcp/tools/{technicals_scan,ticker_snapshot,regime_state,market_overview}.ts`
  - `web/lib/**` (new and moved pure code)
  - the components listed above
  - their tests under `web/tests/**`
  - `web/scripts/mcp-parity.ts`
  - this plan + evidence
- Forbidden:
  - `web/mcp/{server,types,events}.ts`, `web/mcp/tools/{index,read,list_endpoints,get_events}.ts`
  - `web/package.json`, `web/package-lock.json`
  - `src/**`, `scripts/**` (Python/ops), migrations, `.env*`, `CHANGELOG.md`
  - anything on the mini

## Stop conditions

- An extraction changes a rendered value: an existing test diff, or a snapshot or e2e change. In that case stop and report; do not update the expectation.
- A tool needs a non-GET or a non-allowlisted path → message argon-2e.
- A worker exceeds ~40 turns on one task → stop it and rescope.
