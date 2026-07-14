# Chanlun (缠论) TV-style chart view — research + v1 design

Date: 2026-07-14
Status: research complete, v1 design adopted, implementation in `web/lib/chanlun.ts` + `TechnicalsPriceChart.tsx`
Sources: web research (chan.py / czsc / chanlun-pro docs, product pages), @crblandet's 缠论++ launch thread
(x.com/crblandet/status/2075468060115312652, fetched via opencli 2026-07-14), argon codebase survey.

## 1. Goal

A TradingView-style Chanlun structural overlay on the stock-page technicals price chart:
笔/中枢/买卖点 drawn automatically on the candles, toggleable like the existing EMA·BB / SMA·σ
segmented control.

## 2. Reference products

| Product | Approach | Notes |
|---|---|---|
| 缠论++ (chanlunpp.org, @crblandet) | 中枢+买卖点 built on **笔, not 线段**; real-time provisional signals that erase if invalidated ("?" markers); paid tier adds 背驰 + 背驰系数 + alerts | Launch thread explicitly trades textbook fidelity for real-time responsiveness; author built it with Claude Code |
| AlphaViz Chanlun Pro (alphaviz.pro/chanlun) | Strict textbook: 分型/笔/线段/中枢(笔级+段级)/买卖点, 3 stroke algos (严笔/宽笔/4K), 2 segment algos (特征序列 / 1+1终结) | Signals confirm only after the move completes — correct but laggy. $20/mo |
| TradingView "ChanLun AlgoTrader" | Strokes + fractals, 3 stroke algos (old/new/4K), stroke-correction (snap endpoints to true extremes) | Public page documents strokes only |

Common visual encoding: 笔 = thin direction-colored polyline; 线段 = thicker/dashed polyline;
中枢 = semi-transparent rectangle [ZD,ZG]×[start,end], faint border while unconfirmed;
买卖点 = labeled markers 1B/2B/3B (green) / 1S/2S/3S (red), "?" suffix while provisional;
背驰 = text annotation + area-ratio coefficient.

## 3. Algorithm (implementable spec)

Chain: raw K → 包含处理 → 分型 → 笔 → 中枢 → 买卖点 (gated by 背驰). All on merged candles.

1. **包含处理 (inclusion merge)** — adjacent candles where one's [low,high] contains the other's
   merge, direction-dependent: up-trend keeps max(high)/max(low), down-trend min(low)/min(high).
   Greedy/transitive: re-test the merged candle against the next. Seed direction from the first
   non-inclusive pair. Most bug-prone step; errors cascade.
2. **分型 (fractal)** — on 3 consecutive merged candles: top fractal = middle has highest high AND
   highest low; bottom = lowest low AND lowest high. Fractals must alternate; consecutive
   same-type keep the more extreme.
3. **笔 (bi)** — connects alternating top/bottom fractals. Rule variants (old笔/新笔/4K/loose);
   v1 uses a 新笔-style rule: the two 3-candle fractal windows share no merged candle AND the
   fractal midpoints are ≥4 merged candles apart (≥1 independent candle between windows).
   czsc uses a similar simplification (CZSC_MIN_BI_LEN=6 bars). Endpoint = the fractal
   extreme candle's high/low.
4. **中枢 (zhongshu) on bi** — price overlap of 3 consecutive bis: ZG=min(highs of first 3 legs),
   ZD=max(lows); requires ZG>ZD. Extends while subsequent bis re-enter [ZD,ZG];
   GG/DD track absolute extremes. v1: standard extension, no pivot merging (zs_combine off),
   no 9-leg 中枢升级.
5. **背驰 (divergence, MACD-area proxy)** — MACD(12,26,9) histogram; leg strength =
   Σ|hist| over the leg's bars. Divergence when the newer same-direction leg makes a new
   extreme with area < 0.9× the prior leg's (chan.py `divergence_rate` default).
   趋势背驰 (across ≥2 non-overlapping pivots) → 1st-class point; 盘整背驰 (single pivot
   entry vs exit leg) is weaker. MACD is an auxiliary proxy, not the textbook definition.
6. **买卖点** —
   - 1B/1S: trend (≥2 non-overlapping same-direction pivots) makes new extreme with 背驰.
   - 2B/2S: after the 1st-class reversal leg, the first pullback fails to break the 1B/1S extreme.
   - 3B/3S: price leaves the pivot and the next pullback fails to re-enter [ZD,ZG]
     (3B: pullback low stays above ZG; 3S: bounce high stays below ZD).
7. **线段 (segment)** — deferred. 特征序列 + 缺口 case-2 confirmation is where the repaint
   ambiguity and community disagreement concentrate; chan.py exposes `chan`/`1+1`/`break`
   algos precisely because none is canonical. 缠论++ skips it for the same reason.

**Provisional tail**: the trailing fractal/bi/pivot/signal is unconfirmed until an opposite
structure follows — render dashed / "?"-suffixed, never alert off it. This is inherent
(the 未来函数 debate in the launch thread's replies), not a bug.

Open-source references: `Vespa314/chan.py` (most complete; the config catalog — bi_algo,
seg_algo, zs_algo, macd_algo=peak|area|slope|... — is effectively the variant spec) and
`waditu/czsc` (quant-signal oriented, Rust core, deliberately simplified deterministic bi).
No production-grade TypeScript Chanlun library was found.

## 4. v1 design in argon

**Placement**: `TechnicalsPriceChart.tsx` price pane (lightweight-charts v5), a standalone
缠论 on/off toggle next to the SMA·σ/EMA·BB segmented control, persisted to
`localStorage["technicals:chanlun"]`.

**Compute**: client-side `web/lib/chanlun.ts` over the full unwindowed daily rows
(same precedent as the client-side EMA/Bollinger overlay). Pure function
`computeChanlun(rows) → {bis, zhongshus, points}`; deterministic and reproducible from
persisted OHLC, so nothing new needs Postgres persistence. Port to Python
(`cards/chanlun.py`) only when the alert pipeline wants these signals.

**Render**:
- 笔: two `LineSeries` polylines (confirmed solid, provisional tail dashed), vertices at
  fractal-extreme bar times.
- 中枢: custom `ISeriesPrimitive` (`web/lib/lwc/chanlunZhongshu.ts`, modeled on
  `bandsIndicator.ts`) drawing semi-transparent rectangles; faint border while extending.
- 买卖点: `createSeriesMarkers` on a chanlun-owned series (not the candle series — volume
  HVE/HV1 markers already own that one), labels 1B..3S, "?" while provisional.

**Timeframe**: daily bars only for v1 (that's the data we have — 1300 sessions + the live
forming bar). Intraday levels are future work and would need an intraday bar store.

**Out of scope for v1**: 线段, segment-level pivots, 中枢升级/merging, 多级别联立 recursion,
alerts, Python port, per-user rule config (the 新笔-style rule is a code constant).

## 5. Reproduce

- X thread fetch: `opencli twitter thread https://x.com/crblandet/status/2075468060115312652`
- Verification of the view: vitest `web/tests/lib/chanlun.test.ts` (frozen real-ticker
  OHLC fixture) + browser screenshot under `output/playwright/`.

## 6. v2 addendum — 线段/段级中枢/中枢升级/区间套 (2026-07-14)

### 6a. Scope shipped

Complete the TradingView-style 缠论 chart view: add 线段 (segments),
段级中枢 + 段级买卖点, pragmatic 中枢升级 (zone merging), and weekly×daily
区间套 resonance. All client-side, same precedent as v1. The Python/alert
port stays deferred (separate workstream, not this spec).

Out of scope: 线段-recursion beyond one level (多级别联立 on the same
timeframe); textbook 九段升级 recursion (a documented pragmatic merge ships
instead); intraday levels (argon has no intraday bar store); Python
port / alert pipeline integration; any backend, API, or DB change (pure
`web/` feature).

### 6b. chan.py extraction summary

Mechanics extracted 2026-07-14 from `Vespa314/chan.py` source —
`Seg/SegListChan.py`, `Seg/EigenFX.py`, `Seg/Eigen.py`,
`Combiner/KLine_Combiner.py` (fetched 2026-07-14).

**Algorithm reference** (verbatim from the v2 implementation plan, Task 3):

1. An UP segment terminates when its DOWN strokes (the feature sequence) form a TOP fractal after direction-aware inclusion merging; DOWN segment is the mirror (UP strokes → BOTTOM fractal).
2. Feature elements 1–2 inclusion-merge along the **segment** direction; element 3 merges along the **local pairwise** direction. Element 2 is formed with `exclude_included=true` (an engulfing stroke starts a NEW element); element 3 merges with `exclude_included=false` (an engulfing stroke MERGES).
3. `allow_top_equal` (+1 for up segments, −1 for down) makes equal highs (top) / equal lows (bottom) not merge, and the fractal condition permits the tie.
4. `actual_break` gates the fractal: the counter-move must genuinely break past element 2's last stroke — or, at the data tail, the fractal is accepted but flagged provisional (`actualBreakFlag=false`, sticky per detector instance).
5. Termination: **case 1** (no 缺口 between elements 1 and 2, where gap = element 1 entirely below/above element 2) → segment ends immediately at the peak vertex of element 2. **case 2** (gap) → `findRevertFx`: the next segment's counter strokes (starting at peak+2, stepping by 2) must themselves form a valid fractal via the same machinery (recursive); data running out first → provisional. chan.py's threshold-break rejection was removed upstream (issue #272) — `canBeEnd` returns only `true | null`, never false. Do not add a threshold rule.
6. A rejected fractal (`reset()`) drops the detector's first stroke and replays the rest — the segment continues toward its true extreme.
7. There is NO explicit "first 3 strokes must overlap" gate — do not add one. A **confirmed** segment spans ≥3 strokes (`is_sure=false` otherwise). First-segment direction: whichever detector accumulates a 2nd element first (with rollback if it loses it), not first-fractal.
8. Batch simplifications (we recompute from scratch every render, chan.py is incremental): no `do_init` rebuild, no `used_to_be_sure`; stroke "sure" = both endpoint vertices `confirmed`; leftover strokes collect into provisional tail segments by the peak method.

**Oracle examples** (abstract algorithm-geometry traces, NOT market data —
hand-traced through the chan.py mechanics above; verbatim from
`web/tests/lib/chanlunSeg.test.ts`):

- **A: case-1 immediate termination.** Vertices `0→10→6→12→8→11→4`: up
  segment ends at 12 (V3), no gap. Expected boundaries (price):
  `[0, 12, 4]`; confirmed: `[true, true, false]`.
- **B: case-2 gap confirmed by the next segment's own fractal.** Vertices
  `0→10→8→20→15→18→5→9→3→7→4→11`: gap top at 20 confirmed; the down segment
  to 3 (V8) also confirms; tail up to 11 provisional. Expected boundaries:
  `[0, 20, 3, 11]`; confirmed: `[true, true, true, false]`.
- **C: case-2 gap unconfirmed at the tail → provisional.** Example B
  truncated before the reverse fractal completes: vertices
  `0→10→8→20→15→18→5→9`. The second boundary is still `20`, but the whole
  chain is provisional (every vertex `confirmed: false`).
- **D: reset() continuation — premature top rejected, true top found.**
  Vertices `0→10→6→14→9→18→12→16→4`: the 14-top fractal fails (feature
  sequence still rising); the detector resets and the segment runs to 18
  (case 1). Expected boundaries: `[0, 18, 4]`; confirmed:
  `[true, true, false]`.

### 6c. Batch-port deviations from chan.py

- **No incremental `do_init`.** chan.py recomputes segment state
  incrementally as new bars stream in (`used_to_be_sure` caches prior
  confirmations); argon recomputes `buildSegments` from scratch on every
  render, so that machinery is unnecessary and was dropped.
- **Stroke "sure" = both vertices confirmed.** The batch analog of
  `is_used_to_be_sure`: a stroke is treated as settled once its two
  endpoint vertices are `confirmed` (v1's stroke-confirmation contract),
  rather than chan.py's incremental confirmation tracking.
- **Peak-method tail collection.** Leftover strokes beyond the last
  confirmed segment collect into alternating provisional segments running
  to each side's extreme vertex (`collect_left`, batch/display form) —
  not chan.py's incremental append-as-you-go.
- **Pragmatic envelope 中枢升级, not textbook 九段升级.** Consecutive
  same-level zhongshus whose `[zd, zg]` ranges overlap merge into one
  level-2 zone spanning both in time, with price envelope
  `[min(zd), max(zg)]`. The textbook 九段升级 recursion (nine-segment
  pivot-of-pivots construction) is explicitly out of scope; merging is
  transitive by construction (3+ consecutive overlapping zones collapse to
  one level-2 zone).
- **Resonance window rule (spec §1.4).** A confirmed daily 买卖点 `p` is
  resonant iff a same-side (B/S) confirmed weekly point `q` exists with
  `q.time ≤ p.time ≤ endOf(q's following weekly leg)` (the following leg's
  end-vertex time; if `q` is the last weekly vertex, the window extends to
  the last bar). Provisional points on either level never resonate.

### 6d. Reproduce

```bash
cd web && npm run test -- tests/lib/chanlunSeg.test.ts tests/lib/chanlunFull.test.ts
```

### 6e. 买卖点 exit-leg semantics fix + 顶背离/底背离 markers (post-review, 2026-07-14)

Shipped v2 produced **zero** 买卖点 on real data (AAPL/NVDA, 1300 bars each).
Root cause: `buildPivots`' exit leg ("first leg fully outside [zd, zg]") is
structurally **always the counter-direction pullback** — a trend-direction
leg fully above zg would need its start vertex above zg, making the previous
leg fully outside first — while `markPoints` assumed it was the breakout
leg. Every downstream gate (3B/3S pull-leg opposition, 1B/1S same-direction
connect/exit) was unsatisfiable. The original oracles passed because their
fixtures were geometrically impossible (a "bottom" priced above an adjacent
"top"), validating `markPoints` against inputs the real pipeline can never
emit. Fix: 3B/3S mark on the exit leg's own end vertex; 1B/1S compare the
breakout legs (`exitLeg - 1`). New oracles enforce a realism invariant
(every top above its adjacent bottoms) plus real-data non-vacuity
assertions. Measured density post-fix: AAPL 11×3B/3S + 2×1S, NVDA 15 + 3
over 5y — MACD gate filters 8 candidates → 3 on NVDA (non-vacuous).

Added 顶背离/底背离 chart annotations (笔-level): legs `i` and `i+2` are
always same-direction; flag the later one when it extends past the earlier
one's extreme on MACD area < 0.9×. Amber dots, annotation-only (买卖点
gating unchanged). Spot-check: 底背离 fired at AAPL 2022-10-13 (bear-market
low) and 2025-04-08 (tariff-crash low); 顶背离 at 2022-01-04 (pre-bear ATH).
