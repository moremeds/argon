# Chanlun mark lifecycle — prefix-replay empirical study

**Date:** 2026-07-14 · **Branch:** feat/chanlun-v2 (no commits made) · **Data:** real daily bars
from the local dev API `GET /api/stock/{AAPL,NVDA}/technicals` (`series[].as_of/high/low/close`),
1300 bars each (2021-05-06 → 2026-07). No synthetic bars.

**Method:** walk-forward prefix replay. For prefix length `i = 60..1300` (step 1) run the pure
`computeChanlun(bars.slice(0, i))` and track every mark by identity:
`(time, kind)` for vertices, buy/sell points, and divergences. Per identity I logged the first
prefix it appears in (any state), the first prefix where `confirmed=true`, whether it disappears/
reappears, and whether it exists **confirmed in the final full-series result**.

- Lag unit = **trading bars after the marked bar**: `lag = (prefixEndIndex) − markedBarIndex`
  where `prefixEndIndex = i−1` and `markedBarIndex` = the marked bar's position in the array.
  Lag is always ≥0 (a mark's time can't precede the prefix that reveals it).
- "Final confirmed" = present with `confirmed=true` in `computeChanlun(fullSeries)`.

**Reproduce:**
```
# probe (vitest, writes to scratchpad via fs — stdout is swallowed):
cp <scratchpad>/research_probe_lifecycle.test.ts \
   /Users/chenxi/projects/argon/web/tests/lib/_probe_lifecycle.test.ts
cd /Users/chenxi/projects/argon/web && npx vitest run tests/lib/_probe_lifecycle.test.ts
# raw per-identity: research_idents_{aapl,nvda}.json ; tables: research_probe_output.md
```
Inputs `aapl_tech.json` / `nvda_tech.json` are in the scratchpad (re-fetch with
`curl http://127.0.0.1:8400/api/stock/AAPL/technicals` if missing).

---

## Headline

1. **The `confirmed` flag is trustworthy — it is essentially never retracted.** Of every identity
   that ever reached `confirmed=true` live, the fraction still in the final confirmed set:

   | category | ever-confirmed-live n | retention to final-confirmed |
   |---|---|---|
   | vertices | 202 | **100.0%** |
   | 3B/3S | 26 | **100.0%** |
   | divergences | 40 | **100.0%** |
   | 1B/1S | 7 | **71.4%** (2 of 7 retracted) |
   | 2B/2S | 0 | never confirms live at all |

2. **Confirmation is late.** Median lag from marked extreme to `confirmed=true` is **8 trading bars**
   across every category (p90 11–14, tail to ~58 on the rare long stroke). This is structural: a
   vertex only confirms once the *next* stroke endpoint forms ≥4 merged candles away.

3. **Pending (near-extreme) marks are mostly noise.** A mark visible within ≤1 bar of its extreme
   ("pending at bar close") survives to final-confirmed only ~10–13% of the time. The lag-0 bucket —
   which is essentially the code's designed provisional tail (`extSame` + `forming`) redrawing every
   bar — has the worst survival.

---

## 1. Lag distributions (over identities that reach final-confirmed) — POOLED

| category | n | median lag→appear | p90 | max | median lag→confirmed | p90 | max |
|---|---|---|---|---|---|---|---|
| vertices | 202 | 0 | 1 | 58 | 8 | 13 | 58 |
| 3B/3S | 26 | 0 | 0 | 2 | 8 | 11 | 14 |
| 1B/1S | 5 | 1 | 2 | 2 | 7 | 10 | 10 |
| 2B/2S | 0 | — | — | — | — | — | — |
| divergences | 40 | 0 | 0 | 1 | 8 | 14 | 17 |

Per-ticker tables are in `research_probe_output.md` (AAPL and NVDA sections); they agree closely
(vertices median lag→confirmed = 8 on both names).

Reading: the mark's *dot* lands at the extreme almost immediately (lag→appear median 0), but as an
unconfirmed/provisional dot. The *confirmed* state arrives a median 8 bars later.

## 2. Invalidation & flip-flop

"Invalidation" = of all identities that ever appeared, the fraction that never reach the final
confirmed set (a live watcher saw a mark that later moved/died). POOLED:

| category | ever-appeared | final-confirmed | invalidation rate |
|---|---|---|---|
| vertices | 1727 | 202 | **88.3%** |
| 3B/3S | 319 | 26 | **91.8%** |
| 1B/1S | 35 | 5 | **85.7%** |
| 2B/2S | 20 | 0 | **100.0%** |
| divergences | 245 | 40 | **83.7%** |

Caveat: this rate is dominated by the **designed provisional tail**. Every prefix contributes one or
two transient trailing vertices (the running extreme + forming counter-leg) at a fresh `(time,kind)`;
each is counted as an "appeared" identity that is immediately superseded. So 88% "invalidation" for
vertices largely restates "the tail is provisional by construction," not a bug.

**Flip-flop count = 0 for every category, every ticker.** A mark at a *fixed* `(time,kind)` never
goes appear→disappear→reappear. Marks don't flicker in place — they **migrate**: the provisional dot
at time T vanishes and a new dot at time T′ takes its place. Once a specific `(time,kind)` mark is
dropped, it never returns. (Combined with #1: the only thing that ever "un-draws" a specific mark is
the provisional tail relocating; a *confirmed* mark at a location is permanent, save 1B/1S.)

## 3. KEY DECISION NUMBER — survival by appearance-lag bucket (POOLED)

Survival = fraction of identities appearing at that lag that reach final-confirmed.

| category | lag 0 | lag 1 | lag 2 | lag 3 | lag ≥4 |
|---|---|---|---|---|---|
| vertices | **10.5%** (n=1681) | 47.1% (n=34) | 66.7% (n=3) | 50% (n=2) | 85.7% (n=7) |
| 3B/3S | **8.0%** (n=311) | 0% (n=6) | 50% (n=2) | — | — |
| 1B/1S | — | 13.8% (n=29) | 33.3% (n=3) | 0% (n=2) | 0% (n=1) |
| 2B/2S | **0.0%** (n=20) | — | — | — | — |
| divergences | **15.7%** (n=242) | 66.7% (n=3) | — | — | — |

Early ("pending at bar close", lag ≤1) vs later (lag ≥2), POOLED:

| category | early n | early survival | later n | later survival |
|---|---|---|---|---|
| vertices | 1715 | **11.3%** | 12 | 75.0% |
| 3B/3S | 317 | **7.9%** | 2 | 50.0% |
| 1B/1S | 29 | **13.8%** | 6 | 16.7% |
| 2B/2S | 20 | **0.0%** | 0 | — |
| divergences | 245 | **16.3%** | 0 | — |

The provisional tail makes marks appear *at* the extreme (lag 0), so the lag-0 bucket is not "1 bar
early confirmation candidates" — it is the churn itself. Waiting even to lag ≥4 lifts vertex survival
from 10.5% → 85.7%. But the reliable gate is not a bar-count threshold; it is the `confirmed` flag
(#1), which fires at median lag 8 and is 100% reliable for vertices/3B-3S/divergences.

## 4. What this means for a pending / confirmed / invalidated marker design

The measured numbers point to a clean two-state (plus a caveat state) design:

- **CONFIRMED = permanent, alert-safe** for vertices, 3B/3S, and divergences: retention to the final
  set is **100.0%** (0 retractions across 268 confirmed identities). A "confirmed" badge on these can
  drive an alert with zero repaint risk. Cost: it lands a **median 8 bars (~1.5 weeks daily)** after
  the extreme — this is the intrinsic 缠论 confirmation lag, not tunable away.
- **PENDING = show dashed, never alert.** Marks shown within ≤1 bar of the extreme survive only
  **~8–16%** (vertices 11%, 3B/3S 8%, divergences 16%). This validates the source-file comment that
  the trailing structures are "PROVISIONAL by construction … never alert-worthy." Render them, but as
  provisional; ~85–90% will relocate.
- **1B/1S needs its own weaker tier.** It is the only class whose *confirmed* flag is retractable
  (**71.4%** retention, 2/7 dropped) — trend-背驰 re-evaluates as pivots extend. Treat confirmed 1B/1S
  as "provisional-confirmed": alert only with a hold/hysteresis, not instantly.
- **2B/2S is effectively non-confirming in this data.** 20 appearances, **0** ever reached confirmed,
  **0** survived. As implemented (retest at `exit.b+2`, always near the trailing edge) it rides the
  provisional tail. Do not build an alert on 2B/2S until the confirmation path is redesigned; surface
  it as pending-only.
- **No flicker mitigation needed for fixed marks.** Flip-flop count is 0 everywhere — a specific
  `(time,kind)` never blinks. The "instability" a user perceives is the tail dot *migrating* along
  the last leg, which a single dashed provisional-tail rendering already communicates.

**Net design rule from the data:** gate every alert on `confirmed=true` (with a hysteresis exception
for 1B/1S and 2B/2S). Accept the ~8-bar confirmation lag as the price of zero repaint. Everything
unconfirmed is decoration.

---

### Notes / limits

- n=2 names, one regime-rich window each (2021–2026). Buy/sell-point counts are small
  (1B/1S n=35, 2B/2S n=20 pooled) — the 1B/1S 71% and 2B/2S 0% figures are directional, not tight.
  Vertices/3B-3S/divergences samples are large (1727 / 319 / 245) and robust.
- `computeChanlun` is the daily v1 core (segments/线段 excluded per the file header). The full
  `computeChanlunFull` (segments + weekly resonance) was **not** replayed here.
- Whole replay (2×1240 prefixes) runs in ~0.2s in node — cost was never a constraint.

---

# Follow-up: conditional persistence — "if the mark is still standing at bar m+k"

**Motivation:** the appearance-lag buckets above conflate two populations — identities spawned by the
migrating provisional tail (which die by design) and genuine fractal-complete vertices. The design
question is *conditional* persistence: if we paint a PENDING mark at the close of bar `m+k` **when the
mark is still standing**, how trustworthy is it? Presence at `m+k` already implies no newer
same-direction extreme has superseded it — the natural gate.

**Method:** same prefix replay (i = 60..1300, both tickers). For each identity with marked-bar index
`m` and each k ∈ {1,2,3,4,6}: does the identity exist (any confirmed state) in the prefix whose last
bar index is `m+k`? Probe #1 measured **0 flip-flops** in every category, so presence is a contiguous
prefix interval `[firstAppearI, lastPresentI]` — presence at `m+k` is an interval test (the new probe
re-asserts 0 flip-flops). Identities whose `m+k` prefix falls outside the replayed range [60, N] are
excluded as non-evaluable. Survival = membership in the final full-series confirmed set. "Extra bars"
= `max(0, firstConfirmedBarIdx − (m+k))` over survivors.

**Reproduce:** `research_probe2_conditional.test.ts` in the scratchpad → copy to
`web/tests/lib/_probe_lifecycle.test.ts`, then
`cd /Users/chenxi/projects/argon/web && npx vitest run tests/lib/_probe_lifecycle.test.ts`.
Raw per-identity JSON: `research_conditional_persistence.json` (per-ticker; per-ticker tables in
`research_probe2_output.md`).

## Conditional survival, POOLED (AAPL+NVDA)

| cat | k | N present at m+k | survival → final-confirmed | median extra bars to confirmed |
|---|---|---|---|---|
| vertices | 1 | 687 | 28.1% | 7 |
| vertices | 2 | 510 | 38.2% | 6 |
| vertices | 3 | 366 | 53.6% | 5 |
| vertices | 4 | 303 | 64.7% | 4 |
| vertices | 6 | 233 | **84.1%** | 2 |
| 3B/3S | 1 | 130 | 19.2% | 6 |
| 3B/3S | 2 | 88 | 29.5% | 5 |
| 3B/3S | 3 | 61 | 42.6% | 4 |
| 3B/3S | 4 | 46 | 56.5% | 3 |
| 3B/3S | 6 | 31 | **83.9%** | 1 |
| 1B/1S | 1 | 29 | 13.8% | 5 |
| 1B/1S | 2 | 19 | 26.3% | 5 |
| 1B/1S | 3 | 14 | 35.7% | 4 |
| 1B/1S | 4 | 10 | 50.0% | 3 |
| 1B/1S | 6 | 8 | 62.5% | 1 |
| 2B/2S | 1 | 7 | 0.0% | — |
| 2B/2S | 2 | 3 | 0.0% | — |
| 2B/2S | 3 | 1 | 0.0% | — |
| 2B/2S | 4,6 | 0 | — (none standing) | — |
| divergences | 1 | 113 | 35.4% | 7 |
| divergences | 2 | 97 | 41.2% | 6 |
| divergences | 3 | 71 | 56.3% | 5 |
| divergences | 4 | 59 | 67.8% | 4 |
| divergences | 6 | 47 | **85.1%** | 2 |

Reading: conditioning on "still standing" is a real but *gradual* filter — survival climbs roughly
+10–13 pts per extra bar of standing, with no cliff. Presence itself decays fast (vertices: 687
standing at k=1 → 233 at k=6), i.e. most tail-spawned marks are superseded within a few bars, and the
ones that keep standing are increasingly the real fractal vertices. Per-ticker numbers agree within a
few points everywhere (AAPL/NVDA tables in `research_probe2_output.md`).

## 分型确认 refinement (vertices, k=1)

Among vertices standing at `m+1`, split by whether the merged-candle fractal is strictly complete at
`m+1` (recomputed `mergeInclusions` on the prefix; right merged candle has strictly lower high AND
lower low for a top, mirror for bottoms):

| population | n | survival |
|---|---|---|
| fractal-complete at m+1 | 491 | **32.0%** (157/491) |
| NOT complete | 196 | **18.4%** (36/196) |

(AAPL 29.2% vs 20.9%; NVDA 34.9% vs 16.2%.) The classic 分型确认 trigger does discriminate — roughly
+14 pts, ~1.7× — but even a completed 3-candle fractal at the next close is still a **~1-in-3** bet to
survive as a confirmed vertex. The dominant killer is not fractal incompleteness; it is a later, more
extreme same-direction fractal replacing the endpoint (中继分型 dropping / `better`-fractal
replacement in `buildEndpoints`), which no next-bar test can see coming. 分型确认 alone is not a
usable pending→semi-trusted promotion gate at k=1.

## Takeaway (smallest k where conditional survival crosses ~70% / ~85%)

- **vertices:** ~70% between k=4 (64.7%) and k=6; **~85% at k=6** (84.1%). Practical: "standing at
  m+6" ≈ trustworthy — and at that point confirmation is only a median 2 bars away anyway.
- **3B/3S:** same shape — ~70% between k=4 (56.5%) and k=6; **~84% at k=6**.
- **divergences:** ~70% at **k=4** (67.8%, closest category to an early gate); **85% at k=6**.
- **1B/1S:** never crosses 70% by k=6 (62.5%, n=8) — no early gate exists; wait for `confirmed` plus
  the hysteresis noted above.
- **2B/2S:** 0% at every k and none left standing by k=4 — unrescuable as implemented; pending-only.

Net: a "standing-for-k-bars" PENDING tier only becomes alert-adjacent around k=6, where the
`confirmed` flag (median 2 more bars, 100% reliable for vertices/3BS/div) is about to fire anyway.
The k-gate buys almost nothing over just waiting for `confirmed` — the honest design remains
pending (dashed, no alert) → confirmed (alert), with 分型确认 usable only as a visual sub-shade
(solid-vs-faint pending), not a trust boundary.
