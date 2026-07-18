# Chanlun trust probe on silver-grade bars — design

**Date:** 2026-07-18 · **Status:** design (approved in brainstorm; spec under user review)
**Prior art:** `docs/research/2026-07-14-chanlun-signal-lifecycle/` (repaint + 区间套 probes),
`src/uw_scan/chanlun/` (Python port), `scripts/research/chanlun_sublevel_probe.py` (harness).

## Problem

We can now read **corporate-action-adjusted (silver) daily bars** from apex `:8322`
(verified 2026-07-18: NVDA across its 2024-06-10 10:1 split shows a continuous
120.68 → 121.58 series, no split cliff). The July 2026 chanlun probes ran on bars
with adjusted/unadjusted seams for several mega-caps (the livewire adj_close
blocker), so their instability numbers were partly split-seam garbage, not chanlun.

We are **not** building a tradeable strategy. The question is narrow and honest:
**to what extent can the operator trust 背离 (顶/底背离) and 买卖点 (1/2/3 B/S)?**
Two independent trusts:

1. **Repaint stability** — once a mark reaches `confirmed=true`, does it un-draw?
   How late does confirmation land?
2. **Forward-return edge** — after a mark *confirms*, does price move the predicted
   direction more than a same-ticker baseline?

## The load-bearing methodological rule

The July study proved `confirmed` lands a **median 8 trading bars after the
extreme**. Any forward-return measured *from the extreme* therefore leaks ~8 bars
of lookahead the operator could never have acted on.

- **Primary metric: entry = the confirmation bar's close.** This is the only
  point-in-time-honest moment — the first bar at which the operator actually sees
  `confirmed=true`.
- **Secondary metric: entry = the extreme's close** (hindsight). Reported *only*
  to quantify how much the naive "enter at the pivot" number is inflated by
  lookahead. Never presented as achievable.

This distinction is the whole point of the study. A chanlun backtest that enters
at the extreme is measuring a signal you can only identify in hindsight.

## Scope

- **Timeframe:** daily v1 core (`computeChanlun` / the `src/uw_scan/chanlun/` port).
  线段/weekly-resonance and the 区间套 sub-level path are **out** — that was Phase B,
  which already failed and is a separate question.
- **Categories:** 顶背离, 底背离, 1B, 1S, 2B, 2S, 3B, 3S.
  Direction: 底背离 / 1B / 2B / 3B → bullish; 顶背离 / 1S / 2S / 3S → bearish.
- **Universe:** ~200 liquid large-caps + liquid ETFs. Materialized **once** from a
  real source (UW stock screener by market cap, or SPY/IWB holdings) at authoring
  time and committed as a frozen list with an as-of date — no fabricated tickers,
  no runtime network for the list. Keep only tickers apex has ≥3y of clean daily
  bars for (drop data-gap names). ~200 gives per-category n large enough that even
  2B/2S becomes legible, and dilutes the mega-cap survivorship bias of the July
  10-name set.
- **Window:** apex's full clean history per ticker (~5y, 2021→present).

## Method

Walk-forward prefix replay, reusing the existing harness pattern:

1. For each ticker, fetch full clean daily bars once via `sources/apex.py::fetch_bars`.
2. Walk prefixes `bars[:i]` for `i = warmup..N`; run the pure chanlun compute on each
   prefix (point-in-time — the compute only ever sees bars ≤ i).
3. Track every mark by identity `(time, kind, category)`. Record:
   - first prefix it appears in (any state), first prefix where `confirmed=true`,
   - whether a `confirmed` mark ever later retracts (repaint), lag-to-confirm,
   - the **confirmation bar index** (entry point for the honest forward return),
   - the **extreme bar index** (entry point for the hindsight number).
4. For each confirmed mark, compute forward returns at **+1/+3/+5/+10/+20 trading
   days** from both entry points, signed by the category's direction (so a correct
   bearish call yields a positive "edge" return).
5. Baseline: same-ticker **unconditional** forward return over each horizon
   (mean over all bars). `edge = conditional_mean − baseline_mean`.

## Metrics (per category, pooled + per ticker-half for stability)

Repaint block (reuses July metric, now on clean bars):
- `confirmed`-retraction rate, median & p90 lag-to-confirm.

Edge block, per category × horizon:
- hit-rate `P(direction correct)`, mean & median signed forward return,
- baseline mean, **edge = conditional − baseline**,
- `n`, and a **bootstrap 95% CI on the edge** (+ sign-test p) so thin categories
  are visibly thin rather than over-read.
- Both entry variants side by side (confirmation-close = headline; extreme = ghost).

## Persistence

Exploratory research → committed artifact, not a Postgres table:

```
docs/research/2026-07-18-chanlun-trust-silver/
  summary.md            # tables + verdict per category
  per_signal_trace.csv  # every confirmed mark × horizon: entry, fwd return, baseline
  universe.csv          # frozen ~200-ticker list + as-of date + data-coverage note
```

`summary.md` records the exact reproduce command
(`uv run python scripts/research/chanlun_trust_probe.py ...`). Per the standing
rule, the *full* trace is saved (every mark, every horizon), not just headlines.

## What this study can and cannot say

- **Can:** whether a confirmed 底背离/买点 is, on clean data, even weakly
  informative about forward returns *at the moment you can see it confirmed*; and
  whether confirmed marks are visually stable enough to trust as chart annotations.
- **Cannot:** produce a tradeable strategy (no costs, no position sizing, no
  regime conditioning, no OOS promotion gate). Mega-cap universe is
  survivorship-biased even at n=200 — an edge here is an upper bound. Daily-bar
  confirmation lag (~8 bars) is intrinsic and not tuned away.

## Reused vs new

- **Reuse:** `src/uw_scan/chanlun/` compute, `sources/apex.py::fetch_bars`, the
  prefix-replay pattern from `scripts/research/chanlun_sublevel_probe.py`.
- **New:** `scripts/research/chanlun_trust_probe.py` (forward-return + baseline +
  bootstrap on top of the replay), the frozen universe list, the artifact dir.
- **No production surface** — no migration, no API route, no worker job, no UI.
