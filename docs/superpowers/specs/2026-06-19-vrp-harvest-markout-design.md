# VRP harvest markout — is selling rich vol a reliable edge?

Status: design approved 2026-06-19. Build order: **after** the surface capture
(Spec A, `2026-06-19-option-surface-capture-design.md`), though it has no code
dependency on it and can run on existing data any time.

## Problem

We mine the *slope* of the vol smile hard — the skew engine (`reports/skew_markout.py`)
marks out 25Δ risk-reversal against forward returns with proper out-of-sample hygiene.
We do **not** test the *level* mispricing: the variance risk premium (VRP = IV − RV).
We compute and persist it (`vrp_daily`, with `vrp_z_20`) but have never asked the only
question that matters for trading it: **when VRP is rich, does selling vol actually earn
a reliable, positive premium — out of sample, excluding the earnings trap?**

This is a near-term, fully-testable alpha question. `vrp_daily` already holds
**118 tickers × ~313 trading days (2025-05-13 → 2026-06-17), ~25.4k non-null `vrp_z_20`
observations** (verified against the live mini DB on 2026-06-18) — ample for a T+20
markout with cross-sectional buckets and per-quarter stability gates.

## Goals

1. A markout that scores the **realized VRP harvest** conditioned on `vrp_z` extremity,
   bucketed by asset class, with earnings-spanning windows excluded.
2. The same OOS discipline the skew engine uses: a time-ordered walk-forward holdout and
   a per-quarter catastrophic-degradation gate.
3. A persisted verdict per bucket — `HARVEST_SELLABLE` or `NONE` — consumable by
   option-wizard's "is vol rich enough to sell" decision.

## Non-goals (this spec)

- No new UI card in phase 1 (verdicts consumed via API / option-wizard; a vol-tab surface
  is a deferred follow-up).
- No directional VRP test and no ΔVRP-reversion test — we deliberately chose the harvest
  target (see "Forward target"). Those remain possible future variants.
- No per-strike surface dependency — this runs entirely on the daily `vrp_daily` series.

## Methodology

### Signal
`vrp_z_20` from `vrp_daily` (rolling 20d z-score of VRP = IV − RV). Bucketed into a
`deviation_class`:

- **RICH** when `vrp_z ≥ +1.0` (vol expensive vs its own recent baseline)
- **CHEAP** when `vrp_z ≤ −1.0`
- **NORMAL** otherwise

### Forward target — realized VRP harvest
`realized_VRP(t) = IV(t) − RV(t+20)`, where:

- `IV(t)` is the implied vol at the signal date (`vrp_daily` / `realized_volatility_history`).
- `RV(t+20)` is the trailing-21d realized vol read **20 trading days forward** — i.e. the
  realized vol that actually unfolds over roughly the `[t, t+20]` holding window.

This is the premium a short-vol position entered at `t` and held ~one month would *earn*:
positive when IV sold richer than the vol that subsequently realized. **Documented
approximation:** the existing `realized_volatility` series is trailing-21d, so reading it
at `t+20` approximates realized-over-`[t, t+20]` (21d window ≈ 20d horizon). If validation
shows the approximation is loose, the exact fallback is to compute forward realized vol
directly from the price series over `[t, t+20]` (annualized stdev of daily log returns),
reusing the price primitive in `skew_markout._price_series`.

### Earnings exclusion
Drop any observation whose `(t, t+20]` window contains an earnings date — that window is
exactly the earnings short-vol trade our "no hold through earnings" rule forbids, and
leaving it in would contaminate RICH single-name buckets (IV ramps into a known event,
RV gaps on the print). Reuse the earnings-date source the skew lean already consumes
(`reports/skew_analytics.py` earnings gating).

### Bucketing
`(asset_class, deviation_class)`, where `asset_class` reuses the skew classifier
(`index_macro` / `sector_etf` / `credit` / `single_name`) and `deviation_class` is
RICH/NORMAL/CHEAP as above.

### Scoring
For each bucket:

- **Primary metric:** the **absolute** mean `realized_VRP` (NOT cross-sectionally
  demeaned — unlike the directional skew test, the harvest claim is about the premium
  being *positive in level*, not relative-to-universe). A positive, stable mean in the
  RICH bucket is the sellable edge.
- **Conditioning evidence:** the **RICH − CHEAP spread** in mean `realized_VRP` — does
  conditioning on `vrp_z` actually separate harvest outcomes, or is the premium flat
  across the signal?

### Out-of-sample hygiene (reuse skew generics)
- **Walk-forward holdout:** latest 40% of observations by `market_date` (time-ordered, no
  leak) must agree in sign and clear a magnitude floor — reuse the `_rv_walkforward`
  pattern from `skew_markout.py`.
- **Per-quarter catastrophic gate:** fail the bucket if any calendar quarter's mean
  *reverses the aggregate sign with larger magnitude* — reuse `_survives_window_gate`.
  (This is the load-bearing guard our specs always require: aggregate means hide
  per-regime blowups.)

### Verdict
`HARVEST_SELLABLE` requires: `n ≥ min_n` (default 20), mean `realized_VRP > 0` by a
threshold (default 0.02 annualized vol = 2 vol points), survives walk-forward, survives
the quarter gate. Otherwise `NONE`. Confidence capped at "med" (mirrors skew — never claim
"high" from one harness).

## Components

1. **`src/uw_scan/reports/vrp_markout.py`** — new module. Reuses the **generic** helpers
   from `skew_markout.py` (`_forward_value_at`, the walk-forward holdout, the per-quarter
   gate) and the price primitive; adds VRP-specific signal/target/bucketing. Does **not**
   modify `skew_markout.py` (its orchestration is welded to risk-reversal).
2. **Verdict table `vrp_harvest_verdicts`** — new migration. PK
   `(asset_class, deviation_class)`. Columns: `verdict` ∈ {`HARVEST_SELLABLE`,`NONE`},
   `mean_realized_vrp`, `mean_holdout`, `rich_cheap_spread`, `n`, `n_holdout`,
   `survives_walkforward`, `survives_window_gate`, `confidence`, `as_of`.
   Storage method in a new `storage/vrp_markout.py` mixin (per the repository-split rule —
   never appended to `repository.py`).
3. **Worker job `vrp_markout`** — runs the markout **nightly, aligned with the existing
   skew markout job**, and persists verdicts. Read-only over `vrp_daily` + price/earnings;
   writes verdicts.
4. **API read endpoint** — `GET /api/regime/vrp-harvest` (or under the existing vol/skew
   router) returning the verdict rows. No mutation.

## Data flow

```
vrp_markout job (read-only inputs):
  vrp_daily (vrp_z_20, iv)  ─┐
  realized_volatility_history (RV @ t+20) ─┼─► realized_VRP per obs
  earnings dates ────────────┘             │   (drop event-spanning windows)
                                           ▼
            bucket (asset_class × deviation_class) → mean harvest
            → walk-forward holdout + per-quarter gate
            → upsert vrp_harvest_verdicts  → GET /api/regime/vrp-harvest
```

## Testing

- Unit: `realized_VRP` computation incl. the `t+20` forward read and the price-series
  fallback; off-by-one on trading-day offsets.
- Unit: earnings exclusion drops exactly the event-spanning windows (boundary cases at
  `t` and `t+20`).
- Unit: bucket assignment at the ±1.0 `vrp_z` thresholds; asset-class classification.
- Unit: walk-forward holdout split and per-quarter gate, reusing skew fixtures' shape
  (sign-reversal quarter → gate fails).
- Integration (pytest-postgresql): seed a synthetic `vrp_daily` panel with a known
  positive RICH harvest → verdict `HARVEST_SELLABLE`; flatten the signal → `NONE`.

## Acceptance criteria

1. The markout runs on the existing ~25k-observation panel and writes a verdict per
   `(asset_class, deviation_class)` bucket.
2. Earnings-spanning observations are provably excluded (test-verified).
3. A bucket only earns `HARVEST_SELLABLE` if it clears n, magnitude, walk-forward, AND the
   per-quarter gate — and the report exposes the RICH−CHEAP spread so a flat (no-edge)
   result is legible, not hidden.
4. `GET /api/regime/vrp-harvest` returns the verdicts.

### Kill criteria (what tells us there is NO edge)
If the RICH bucket's mean `realized_VRP` is not reliably positive, or the RICH−CHEAP
spread is ~zero, or no bucket survives the quarter gate, the honest conclusion is **no
tradeable VRP-conditioning edge** — we record the `NONE` verdicts and stop, rather than
loosening thresholds to manufacture a signal. (Per the standing review-pattern: a
per-regime catastrophic gate is load-bearing; aggregate positivity alone is not a pass.)

## Out of scope

- Directional VRP test, ΔVRP-reversion test (other targets we explicitly did not choose).
- Multi-horizon sweep (T+5/T+60) — single T+20 for v1.
- VRP UI card — deferred follow-up.
