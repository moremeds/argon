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
- Verification of the view: vitest `web/lib/__tests__/chanlun.test.ts` (frozen real-ticker
  OHLC fixture) + browser screenshot under `output/playwright/`.
