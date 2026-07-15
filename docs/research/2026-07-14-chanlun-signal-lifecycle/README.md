# Chanlun signal lifecycle — pending/confirmed/invalidated + confirmation-lag research

**Date:** 2026-07-14 · **Branch context:** feat/chanlun-v2 (PR #279, post 买卖点-fix c054a6d)
**Question (user):** marks are painted retroactively and confirm ~4–8 daily bars after the
bar they decorate — way too slow. Want (a) a PENDING mark at bar close, then
CONFIRMED / INVALIDATED (invalidated fades after 5–10 bars), and (b) confirmation
narrowed to ~1 bar.

Three parallel research streams (theory/prior-art, empirical walk-forward probe,
UI/architecture). Full reports in this directory:

| File | What |
|---|---|
| `research_theory.md` | czsc / chanlun-pro / TradingView prior art, 分型强度, 区间套, repaint UX conventions (cited) |
| `research_empirical.md` | Walk-forward prefix-replay methodology + results, AAPL+NVDA 1300 daily bars each |
| `research_probe_output.md` / `research_probe2_output.md` | Full result tables (lifecycle; conditional persistence) |
| `research_probe_lifecycle.test.ts` / `research_probe2_conditional.test.ts` | Reproducible probes (drop into `web/tests/lib/`, run `npx vitest run <file>`; results written via appendFileSync) |
| `research_ui_arch.md` | lightweight-charts 5.2.0 marker capabilities + 3 architecture options for lifecycle state |

Reproduce: bars from `GET http://127.0.0.1:8400/api/stock/{AAPL,NVDA}/technicals`,
replay `computeChanlun(bars.slice(0, i))` for i = 60..N, track mark identities
`(time, kind)` across prefixes. No synthetic data.

## Headline numbers (pooled AAPL+NVDA)

1. **`confirmed=true` never lies.** 100% of live-confirmed vertices (202/202),
   3B/3S (26/26), and divergences (40/40) remain in the final confirmed set.
   Exceptions: 1B/1S retracts 71.4% (n=7, small), **2B/2S never confirms live
   (0/20) — defect as implemented** (the retest vertex structure is superseded
   before its confirmation arrives).
2. **Median extreme→confirmed lag = 8 trading bars** (p90 11–14) across all
   categories. Structural: a vertex confirms only when the next opposite stroke
   endpoint forms ≥ MIN_VERTEX_GAP=4 merged candles away.
3. **A bare 1-bar pending gate is noise.** Survival→final-confirmed conditional
   on the mark still standing k bars after its extreme:

   | k bars after extreme | vertices | 3B/3S | 1B/1S | 2B/2S | 背离 |
   |---|---|---|---|---|---|
   | 1 | 28.1% | 19.2% | 13.8% | 0% | 35.4% |
   | 2 | 38.2% | 29.5% | 26.3% | 0% | 41.2% |
   | 4 | 64.7% | 56.5% | 50.0% | — | 67.8% |
   | 6 | 84.1% | 83.9% | 62.5% | — | 85.1% |

   Gradual (+10–13 pts/bar), no cliff. At k=6 survivors are a median 1–2 bars
   from `confirmed` anyway — **a standing-for-k gate buys almost nothing over
   the flag**.
4. **分型确认 (fractal complete at next close) discriminates but does not
   rescue k=1:** 32.0% survival vs 18.4% without (~1.7×). The dominant killer is
   a *later more-extreme same-direction fractal* replacing the endpoint —
   invisible to any next-bar test by construction.
5. Marks never flicker in place (flip-flop count 0 everywhere): identities are
   one-shot; the visual churn is the provisional tail *migrating*, not blinking.

Caveats: n=2 tickers (mega-cap tech, one bull regime); 1B/1S and 2B/2S cells are
small-sample and directional only.

## Prior art (see `research_theory.md` for citations)

- **czsc** models exactly the missing state machine: `finished_bis` (confirmed 笔)
  vs `ubi` (未完成笔) with fractal candidates surfaced the instant the third
  merged candle closes — the forming structure is a first-class rendered object,
  not a nullable tail. It also has a magnitude early-confirm (`bi_change_th`):
  an outsized swing promotes a short 笔 without waiting out the candle gap.
- **分型强度**: practitioners grade the confirming candle by where it closes
  (top: third candle closing below the first candle's midpoint / breaking its
  low = strong) and act at completion with fewer false pendings.
- **区间套 / 小级别转大级别** is the *only* honest route to same/next-day
  confirmation of a daily-level point: confirm when the 30m/60m sub-level
  completes its own structure. Blocked today — the stock page has daily bars
  only (apex :8322 bars API is the candidate intraday source).
- **UX convention** (TradingView etc.): bar close is the canonical pending line;
  provisional marks are visibly provisional ("?", transparency); invalidated
  marks disappear (fade-out is a nicety, not a convention). Shipping chanlun
  products (chanlun-pro, 缠论++) already do pending-with-?-then-erase.

## Architecture facts (see `research_ui_arch.md`)

- lightweight-charts 5.2.0 markers take raw canvas colors — rgba/8-digit-hex
  alpha works natively; three visual states need zero new plumbing. Hollow
  glyphs would need a custom primitive (~150 LoC, like the 中枢 rect).
- `computeChanlun` is stateless: "invalidated" can only be known by diffing two
  computes. Options: (a) K-prefix replay per data pass (~60× compute — heavy),
  (b) incrementalizing the pipeline (multi-week rewrite, rejected),
  (c) **pass-to-pass diff across live renders (~free, session-only memory)**,
  (d) server-side Python port persisting signal events to Postgres (durable,
  cold-load-correct, aligns with the Stage-1 alert pipeline).

## Recommendation

**Phase A (client, small diff):** three-state lifecycle on the existing overlay —
PENDING at bar close (fractal-complete gate; 分型强度 as a sub-shade), rendered
translucent + "?"; CONFIRMED full-color (the only alert-worthy event); INVALIDATED
via pass-to-pass diff, shown struck/faded for 5–10 bars then dropped
(session-only; honest limitation on cold reload). Fix or demote 2B/2S (0/20
live-confirm) and mark 1B/1S low-trust.

**Phase B (the real ~1-bar path):** 区间套 fast-confirm — a daily PENDING point
upgrades to CONFIRMED-BY-SUBLEVEL when the 60m/30m sub-structure completes the
same-side point, using apex intraday bars. Server-side port + Postgres event log
belongs here (alert pipeline v1 lane).

**Not recommended:** shipping a bare 1-bar "confirmed" on daily bars alone —
measured 19–35% survival would spray false signals; a k-standing gate only
reaches trustworthiness where the existing flag fires anyway.
