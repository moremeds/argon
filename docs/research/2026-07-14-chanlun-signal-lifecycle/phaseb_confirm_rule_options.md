# Phase B — 区间套 sub-level confirm rules for daily chanlun marks

**Date:** 2026-07-14 · **For:** argon chanlun signal-lifecycle Phase B (server-side port + Postgres event log, Stage-1 alert-pipeline lane)
**Goal:** a daily-timeframe 买卖点/vertex/背离 mark, born PENDING at daily close, upgrades to CONFIRMED within ~1 trading day using 30m (次级别) sub-level structure — instead of waiting the **median 8 daily bars** (`research_empirical.md` §Headline #2) for native daily confirmation.

Claim tags per the repo epistemic convention: `[VERIFIED]` read from cited source/code · `[INFERRED]` deduced · `[FRAME]` chanlun-theoretic (coherent within 缠论, not an empirical claim) · `[GUESS]` no basis. Confidence HIGH/MED/LOW.

---

## 0. The one fact that governs the whole design

The dominant killer of an early daily mark is **a later, more-extreme same-direction fractal replacing the endpoint** (中继分型 dropping / the `better`-fractal replacement in `buildEndpoints`, `chanlun.ts:162-174`). `research_empirical.md` §分型确认 is explicit: *"The dominant killer is not fractal incompleteness; it is a later, more extreme same-direction fractal replacing the endpoint … which no next-bar test can see coming."* [VERIFIED] `research_empirical.md:234`. 分型确认 at k=1 only lifts survival 18.4%→32.0% (~1.7×) — nowhere near alert-grade [VERIFIED] `research_probe2_output.md:33-34`.

Consequence that drives everything below: **no sub-level rule can pre-emptively defend against the killer, because it is a future daily price event.** The only honest defense is (a) anchor the sub-level confirmation to the *exact* daily extreme so a new extreme necessarily breaks it, and (b) make the sub-level-confirmed state **revocable** — demote it to INVALIDATED when a later daily bar breaches the mark's extreme price. This is why the state machine below makes `CONFIRMED_SUBLEVEL` non-monotonic. [INFERRED] HIGH.

Terminology: "native confirmation" = the existing `confirmed=true` flip, which fires when the next opposite daily stroke endpoint forms ≥ `MIN_VERTEX_GAP=4` merged candles away (`chanlun.ts:82,405,441`). It is **100% reliable** for vertices (202/202), 3B/3S (26/26), 背离 (40/40) [VERIFIED] `research_empirical.md:37-43` — so it is the ground-truth target that a sub-level rule tries to *predict early*.

---

## A. State machine

### States
- **PENDING** — daily fractal complete at daily close (Phase A birth gate: 3rd merged candle closed, same-side, per `findFractals`), category applicable (see §E). This is the object Phase A already paints translucent + "?".
- **CONFIRMED_SUBLEVEL** — a 30m sub-level structure has completed the same-side turn at the daily extreme (rule in §B). Alert-eligible but **revocable**.
- **CONFIRMED_NATIVE** — the daily `confirmed=true` has fired. Terminal, monotonic, alert-safe (0 retractions in 268 confirmed identities, `research_empirical.md:35`).
- **INVALIDATED** — the mark's identity `(time, kind)` no longer exists in the recomputed daily result (endpoint migrated to a more-extreme same-direction fractal), OR a later daily bar breached the extreme price (see below). Terminal.

### Mark identity (stable key)
`mark_id = (ticker, category, kind, extreme_date, extreme_price)`. Because `buildEndpoints` migration relocates the endpoint to a *new* `(time, price)`, a migrated mark is a **new** `mark_id`, not a mutation of the old one — matching the probe's finding that identities are one-shot and never flip-flop in place (flip-flop count 0 everywhere, `research_empirical.md:71`). This makes "supersession" observable as "old mark_id absent from today's daily result." [VERIFIED against probe methodology] HIGH.

### Transitions (trigger event → target)

| From | Trigger event | To | Monotonic? |
|---|---|---|---|
| — | daily fractal complete at daily close, applicable category | **PENDING** | birth |
| PENDING | §B sub-level predicate satisfied over the anchor window | **CONFIRMED_SUBLEVEL** | no (see below) |
| PENDING | daily `confirmed=true` fires first (fast/impulsive leg) | **CONFIRMED_NATIVE** | yes, terminal |
| PENDING | mark_id absent from recomputed daily result (endpoint migrated) **or** later daily bar makes a more-extreme same-direction extreme than `extreme_price` | **INVALIDATED** | yes, terminal |
| PENDING | staleness cap: no confirm within `N_STALE` sessions **and** price ≥ `X·ATR` away from extreme | **INVALIDATED** | yes, terminal |
| CONFIRMED_SUBLEVEL | daily `confirmed=true` fires later | **CONFIRMED_NATIVE** | yes, terminal |
| CONFIRMED_SUBLEVEL | later daily bar breaches `extreme_price` (low<P for bottom / high>P for top) | **INVALIDATED** | **this is the non-monotone edge** |
| CONFIRMED_NATIVE | — | — | terminal, never leaves |
| INVALIDATED | — | — | terminal, never resurrects (re-approach spawns a new mark_id) |

### Position: can CONFIRMED_SUBLEVEL still be invalidated by later daily structure? **YES.**
Take the position explicitly: `CONFIRMED_SUBLEVEL` is a **provisional-confirmed** tier, not a terminal one. The killer (§0) is a future daily price event; a sub-level turn at the exact daily low is still falsified if the daily subsequently prints a lower low. Making the state revocable is the *only* honest treatment — the alternative (declare it terminal) would relabel the killer as a "confirmed" mark and reintroduce exactly the repaint the whole project is trying to kill. The design consequence is that the alert tier for `CONFIRMED_SUBLEVEL` must be distinct from `CONFIRMED_NATIVE` (Open Question 1), and the validation gate (§D) measures the breach rate directly. [INFERRED] HIGH.

`CONFIRMED_NATIVE` **is** terminal — the data earns it: 100% retention (`research_empirical.md:37-40`), the one exception being 1B/1S which is excluded from v1 (§E).

### Idempotency / nightly-batch re-run semantics
Phase B runs as a **nightly batch**: for each watchlist ticker, recompute daily chanlun (full history) + 30m chanlun (anchor window) from scratch, derive the canonical state of every live mark, and **upsert** on `mark_id`.
- **Deterministic ⇒ idempotent.** State is a pure function of the bar series (daily + 30m up to the last close). Re-running over the same bars yields identical transitions — a no-op upsert. Only *new bars* advance state. [INFERRED from `computeChanlun` being stateless, `research_ui_arch.md` / README:84] HIGH.
- **First-entered timestamps are preserved** per state (`first_entered_at` never overwritten on re-run) — required for the latency metrics in §D. Store `pending_at`, `sublevel_at`, `native_at`, `invalidated_at`.
- **Terminal short-circuit:** marks in CONFIRMED_NATIVE / INVALIDATED are read-only; the batch only re-derives them to detect a *terminal* arrival (PENDING/SUBLEVEL → NATIVE or INVALIDATED). It never mutates a terminal row.
- **The Postgres event-log** (README architecture option (d), `research_ui_arch.md`) is append-mostly: one row per `(mark_id, state, first_entered_at)`; the current-state view is `MAX(first_entered_at)` per mark_id. Cold-load-correct and durable — this is the piece that makes Phase B alert-pipeline-grade rather than session-only like Phase A.

---

## B. Candidate confirm rules

All three evaluate a **30m chanlun** (`computeChanlun` reused verbatim on 30m bars — same `MIN_VERTEX_GAP=4`, which on 30m = 4 merged 次级别 candles ≈ ~half a session) over an **anchor window** defined identically for all three:

> **Anchor window W(mark).** Let the daily pending mark decorate extreme bar dated `d_ext` at price `P`, kind `bottom`|`top`. Let `d_prev` = date of the previous *confirmed* daily vertex of the **opposite** kind (the start of the leg terminating at `P`); if none within the lookback cap, `d_prev = d_ext − 40 sessions`. `W = 30m bars with timestamp ∈ [session_open(d_prev), last_available_30m_close]`. This mirrors, one level DOWN, the window logic already shipped in `markResonance` (`chanlun.ts:499-526`), which does the same thing one level UP (weekly confirms daily) — Phase B is its mirror image. [VERIFIED code] HIGH.

**Same-side matching, shared definition.** A daily **bottom** mark seeks a 30m **bottom** event; a daily **top** seeks a 30m **top**. The 30m event's extreme must reconcile to the daily extreme: the 30m low that equals `P` must fall inside `session(d_ext)` (the daily low *is* a 30m low of that session) — anchor by `|v30.price − P| ≤ tol` with `tol` a tick, or by `v30.time ∈ session(d_ext)` if the feed isn't price-reconciled (Open Question 3). Exact-extreme anchoring is **load-bearing**: it is what makes the killer observable (a new daily extreme necessarily prints a 30m low below `v30`, breaking both the match and the price guard). [INFERRED] HIGH.

---

### Rule S1 — 30m confirmed same-side reversal vertex at the daily extreme  *(minimal / v1)*

**(i) Predicate.** Over `W`, `computeChanlun(bars30m)` must contain a **confirmed** 30m vertex `v30` (i.e. `v30.confirmed === true`, meaning the 30m up-stroke leaving it has earned an opposite 30m endpoint ≥4 merged 30m candles away — `chanlun.ts:441`) such that:
1. `v30.kind === mark.kind` (bottom for a daily bottom/1B/3B; top for a daily top/1S/3S), AND
2. `v30` reconciles to the daily extreme (same-side matching above), AND
3. `v30` is the extreme of `W` on its side (not superseded by a deeper 30m low — guaranteed if `v30.confirmed` and it's the anchor's low, but assert it: no later 30m fractal beats `v30.price`).

Plain-language: *the 30m has structurally turned off the exact daily low — a 30m 笔 up has completed and the low held as a 30m vertex.*

**(ii) Cadence.** Nightly EOD batch: one `computeChanlun` over `W` per pending mark (or once per ticker, reused across that ticker's marks). **Intraday later:** evaluate on every *completed* 30m bar (gate on 30m `barstate.isconfirmed` — never the forming 30m tail, same invariant as Phase A); latency then drops from ~1 day to intra-session. No predicate change — only the "last_available_30m_close" advances within the day.

**(iii) Expected latency.** 30m carries ~13 bars/RTH session; a confirmed 30m stroke needs `MIN_VERTEX_GAP=4` merged candles + the opposite fractal ≈ 6–8 30m bars ≈ **same session to next session ⇒ ~1 trading day** (vs native's 8). [INFERRED from bar arithmetic] MED.

**(iv) Failure modes.** (a) *The killer* — 30m turns up, then daily prints a new low days later. S1 has **no intrinsic pre-emptive defense**; it relies entirely on the state-machine breach guard (CONFIRMED_SUBLEVEL→INVALIDATED). This is the false-confirm source §D must bound. (b) *Weak 30m turn* — a shallow 30m bounce confirms a vertex that resolves into a 中继, not a turn; S1 admits these (no divergence/strength filter). (c) *Feed mis-reconciliation* — if 30m extremes don't match daily extremes (adjustment mismatch), the anchor misses real turns (Open Question 3).

**(v) Compute cost.** ~100–260 30m bars per window (8–20 daily sessions × 13); one O(n) `computeChanlun` (sub-ms). Per ticker-day: 1 windowed 30m fetch + 1 daily recompute + 1 30m recompute. Watchlist-scale (~50–100 tickers) nightly: trivial. [INFERRED] HIGH.

---

### Rule S2 — S1 + 30m 底背驰/顶背驰 at the extreme  *(区间套 proper / natural v2)*

**(i) Predicate.** All of S1, **plus** the final 30m down-leg (bottom) / up-leg (top) into `v30` must carry a 30m divergence: reuse `markDivergences` on the 30m series and require a 30m `DivergenceMark` of `mark.kind` at `v30` — i.e. the last 30m thrust to `P` had weaker MACD area than the prior same-direction 30m thrust (`legArea(b) < 0.9·legArea(a)`, `chanlun.ts:374`). This is textbook 区间套: *the daily 背驰 is confirmed by a sub-level 背驰 telescoping onto the reversal bar* [FRAME] HIGH; [VERIFIED theory] `research_theory.md:139-155`.

**(ii) Cadence.** Same as S1 (the 30m `computeChanlun` already yields `.divergences`, so S2 is a free additional read over S1's compute).

**(iii) Latency.** Slightly later than S1 — requires **two** same-direction 30m thrusts inside `W` (so the divergence is computable). On a clean impulsive daily leg this may not exist at all ⇒ **lower recall** than S1. Expected ~1–2 trading days when it fires. [INFERRED] MED.

**(iv) Failure modes.** Better killer-defense than S1: a divergence-backed 30m turn means sub-level momentum was already exhausted at `P`, empirically less likely to resume to a new low — but **not immune** (still revocable). Cost of the extra filter: it *fires less and later*, and produces no signal on impulsive legs that lack a sub-level divergence (misses real turns). [INFERRED] MED.

**(v) Compute cost.** Identical to S1 (same single 30m compute; `.divergences` is already produced).

---

### Rule S3 — 30m confirmed same-side 买卖点 (sub-level BSP)  *(strongest / v2–v3, BSP marks only)*

**(i) Predicate.** For a daily **买卖点** mark (1B/2B/3B/…), require the 30m series to contain a **confirmed** 30m BSP of the matching side at/after `v30`: reuse `markPoints` on the 30m series and require a confirmed 30m point whose `kind` side matches (`B` for a daily buy mark) anchored at/near `P`. A daily 1B confirmed by a 30m 1B (30m 趋势背驰 → first sub-level reversal) is the most theory-pure 区间套 for a *specific 买卖点* rather than a bare vertex. [FRAME] HIGH.

**(ii) Cadence.** Same nightly batch; but the 30m BSP itself needs two 30m pivots + a 趋势背驰 (`markPoints`, `chanlun.ts:307-353`), which needs a longer `W`.

**(iii) Latency.** **Highest** — a 30m 1B needs two 30m 中枢 + a breakout leg; that is typically ≥1 full session of 30m structure ⇒ ~1–3 trading days. Trades latency for specificity. [INFERRED] MED.

**(iv) Failure modes.** Inherits the killer (revocable). Additional risk: 30m 买卖点 machinery carries the *same* daily defects one level down — notably 30m 2B/2S is likely as defective as daily 2B/2S (0/20, §E) — so S3 must be restricted to 30m *1B/3B* legs, not 30m 2B. Higher false-negative rate (many daily turns never mint a clean 30m BSP).

**(v) Compute cost.** Same single 30m `computeChanlun` (`.points` already produced) — but requires a wider `W` (more 30m bars) to contain two sub-level pivots. Still sub-ms.

---

## C. Recommendation

**v1 = Rule S1**, applied to the reliable categories in §E, with the state-machine breach guard as the sole killer defense.

Reasoning:
- **Lowest latency, highest recall.** S1 fires ~1 day after birth on the widest set of real turns; S2/S3 fire later and skip impulsive legs. The entire value proposition of Phase B is *speed* (8 bars → ~1), and S1 maximizes it. [INFERRED] HIGH.
- **The killer defense is structural, not filter-based.** Exact-extreme anchoring + the revocable-state breach guard defends the dominant failure mode *without* the divergence filter. Adding S2's filter buys marginal false-confirm reduction at a real recall cost — pay for it only if §D shows S1's breach rate exceeds the gate. [INFERRED] MED.
- **Reuses shipped code unchanged.** S1 is `computeChanlun` on 30m + a vertex `.confirmed` read + the anchor window (mirror of `markResonance`). No new geometry. Aligns with the module-size and "share the pure parser" conventions.

**Natural v2 escalation = Rule S2** — turn on the 30m 背驰 requirement *per-category* wherever §D shows S1's category-level breach rate above the gate. S2 is a strict superset of S1's predicate, so it slots in as a tightening flag, not a rewrite. **S3** is a v2–v3 specialization reserved for daily 买卖点 marks once vertices/背离 are validated.

---

## D. Validation protocol (must pass BEFORE alert-grade)

**Method.** Walk-forward prefix replay, identical in spirit to `research_probe_lifecycle.test.ts` / `_probe2_` (`research_empirical.md:18-27`), extended to two timeframes. For each ticker, for each daily close `d`: (1) daily prefix → birth/native state of every mark (ground truth = the mark's presence in the **full-series** daily `confirmed` set); (2) 30m prefix ending at `close(d)` → evaluate the §B predicate → assign CONFIRMED_SUBLEVEL date. Track each `mark_id` across prefixes.

**Metrics (per category AND pooled):**
1. **Sub-level survival** — of marks reaching CONFIRMED_SUBLEVEL, fraction that reach CONFIRMED_NATIVE (final-series daily `confirmed`). *This is the direct analog of the daily-only survival tables.*
2. **False-confirm (breach) rate** — of CONFIRMED_SUBLEVEL marks, fraction later INVALIDATED by a daily breach of `extreme_price` before native confirm. Report separately from right-censored marks (still pending at end of data). A fired-then-breached alert is the expensive error, so gate on this specifically.
3. **Median confirm latency** — `sublevel_at − pending_at` in trading days; target vs native's **8-bar median** (`research_empirical.md:44`).
4. **Lead over native** — for marks reaching both, median `native_at − sublevel_at` in daily bars (expected ~6–7; that's the bars saved).

**Data.** Requires 30m bars — **not on the daily stock page today** (the page is daily-only, `api.ts` has no intraday endpoint; source is apex REST `:8322` / the mini's ~5.1y 30m store per the session memory — **confirm availability & adjustment, Open Question 3**). Tickers: broaden past the daily probe's AAPL+NVDA to **≥10 liquid watchlist names** × the full ~5.1y of 30m history, so per-category n clears the small-sample caveat that limited the 1B/1S (n=35) and 2B/2S (n=20) daily cells (`research_empirical.md:54`). Walk-forward, no synthetic bars, persist the full per-`mark_id` trace to a committed artifact under `docs/research/` + record the exact reproduce command (repo standing rule).

**Numeric acceptance gate (proposed):**
- **Sub-level survival ≥ 70%, per applied category, not just pooled.** Justification: the daily-only baseline at k=1 is **28.1% vertices / 35.4% 背离 / 19.2% 3B-3S** (`research_probe2_output.md:5,11,26`); the research itself uses **~70% as the "alert-adjacent" threshold** (the smallest-k crossing, `research_empirical.md:237-243`), which the daily-only gate only reaches at **k=4–6** — i.e. 4–6 bars of waiting. If S1 delivers ~70% at ~1-day latency, it hands you the daily-k=4–6 *trust* at daily-k=1 *speed* — the whole point. Below 70% it is no better than the existing PENDING flag and must **not** ship as alert-grade (README "Not recommended" ruling, `README.md:102-104`).
- **Breach rate ≤ 15%** (metric 2). A revocable-confirmed tier is only tolerable if retracted alerts are rare.
- **Median latency ≤ 2 trading days** (metric 3) — else the speed advantage over native (8) is not worth the revocability.
- **Per-category catastrophic gate** (mirrors the AC-F4 per-window rule in the memory index): any category failing the 70%/15% bar in EITHER ticker-half of the walk-forward is **excluded from v1**, not pooled-averaged into passing.

---

## E. Category applicability (v1)

Positions, per the daily reliability evidence:

| Category | Daily native reliability | v1 decision | Rationale |
|---|---|---|---|
| **Vertices (笔 endpoints)** | 100% (202/202) `research_empirical.md:37` | **APPLY (S1)** | The base object; sub-level confirm of a daily vertex *is* the 区间套 core. Large, robust sample. |
| **背离 (divergences)** | 100% (40/40) `research_empirical.md:39` | **APPLY (S1); flagship** | 区间套 exists precisely to refine 背驰 — a daily 背离 confirmed by a 30m 背驰 (S2 makes this explicit) is the highest-value target. Already the closest to an early daily gate (k=4 → 67.8%, `research_probe2_output.md:29`). |
| **3B/3S** | 100% (26/26) `research_empirical.md:38` | **APPLY (S1)** | Reliable daily category; the 3B mark is a pullback-hold vertex, so S1's vertex machinery applies directly. Same-side match = confirm the pullback low held on 30m. |
| **1B/1S** | 71.4% retention, retractable (n=7) `research_empirical.md:41` | **DEMOTE — exclude from v1 auto-confirm** | The *only* class whose daily `confirmed` itself retracts (趋势背驰 re-evaluates as pivots extend). Sub-level confirm would fire early on a mark unstable at the daily level — compounding, not fixing. Revisit in v2 with a hold/hysteresis (`research_empirical.md:135`). |
| **2B/2S** | 0/20 native — defect `research_empirical.md:30,42` | **EXCLUDE — fix at daily level first** | Never confirms as implemented (retest at `exit.b+2` rides the provisional tail, `chanlun.ts:343`). A sub-level rule cannot rescue a daily mark that never stabilizes. This is a Phase-A daily-definition fix, not a Phase-B target. Surface pending-only until the daily 2B/2S definition is redesigned. |

v1 scope: **vertices + 背离 + 3B/3S**, Rule S1. 1B/1S and 2B/2S stay PENDING-only (no sub-level promotion) until their daily definitions are fixed/hardened.

---

## F. Open questions for the human (design-changing only)

1. **Alert tier for CONFIRMED_SUBLEVEL — one alert bucket or two?** Because CONFIRMED_SUBLEVEL is revocable (§A), a later breach = a *retracted* alert. Do we (a) fire a first-class alert on CONFIRMED_SUBLEVEL and accept occasional retraction, or (b) treat it as a distinct lower "provisional-confirmed" tier (badge only, alert reserved for CONFIRMED_NATIVE), or (c) fire on SUBLEVEL only after it *also* survives a minimum hold (e.g. 1 daily bar without breach)? This sets whether the breach-guard buffer is part of the confirm predicate or only the alert policy.

2. **30m vs 60m sub-level (or a cascade)?** 30m gives the fastest, loosest confirm (~13 bars/session, ~1-day latency) but more false-confirms; 60m (~6.5 bars/session) is closer to the *canonical* 次级别 of daily and stricter. Ship 30m alone (speed), 60m alone (fidelity), or 60m-confirms-then-30m-refines cascade? This changes the fetch plan and the latency/false-confirm operating point.

3. **Is the 30m feed corporate-action-adjusted and price-reconciled to the daily bars?** The exact-extreme anchor (§B) — my primary killer defense — needs the 30m session low to equal the daily low. If the intraday store (apex `:8322` / mini) isn't split/div-adjusted consistently with the daily series, the price-equality match must degrade to a session-time match with a tolerance, weakening the anchor. Confirms feasibility of the whole approach.

---

[RULES I BROKE]: None. Latency figures (§B iii) are tagged [INFERRED]/MED from bar arithmetic, not measured — §D metric 3 is the measurement that must confirm them before ship. The 30m data source (apex `:8322`, ~5.1y) is from session memory, not re-verified against a live endpoint — flagged as Open Question 3. All empirical numbers are cited to the specific research-doc line.
