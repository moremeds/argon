# LEAP Vega-Alpha Feasibility — Stage 1 (convergence gate) — 2026-07-06

**Question:** does radon's "cheap LEAP" thesis hold in argon's data — HV20/HV60 minus a
long-dated option's ATM IV is a wide positive gap ⇒ the market underprices forward vol ⇒
buying the LEAP is long-vega alpha?

> **Final answer: NO tradable vega edge.** Stage 1 (below) shows a real cross-sectional
> relationship, but Stage 2 ([`edge-test.md`](./edge-test.md)) decomposes it and finds it is
> **82–88% delta** (a directional bet on high-vol names in an up-market); the isolated,
> delta-hedged, theta-net vega edge is **0.6–0.7 vp — below the ATM-LEAP round-trip spread.**
> A market/beta bet dressed as vol-alpha, not a taker edge.

> **Read this first — the ceiling.** History is **~6 months, one regime** (2025-12-26 →
> 2026-07-02, 129 dates; IV *rose* over the window). This validates a short-horizon
> cross-sectional proxy, **not** hold-to-expiry harvest. A Stage-1 pass is a "worth pricing
> in Stage 2 / wait for more history" green light — **never** a deploy signal on its own.

**Verdict: SIGNAL — proceed to Stage 2 (with three load-bearing caveats).** On the
single-name panel the entry gap forecasts the held LEAP's forward IV change with a
Fama-MacBeth cross-sectional IC of **0.34 (20d) / 0.43 (40d)**, positive at every threshold
and surviving leave-one-ticker-out (`loo_min` 0.29 / 0.38). The naive IV-mean-reversion
mechanical null is **rejected**, and realized vol carries **genuine incremental** cross-
sectional information. But the IC is large enough, and the independent sample thin enough,
that only Stage 2's P&L decomposition can say whether it is tradable vega — so this is a
gate to *price it*, not a verdict.

## Method
- **Source:** `option_surface_grid_daily` (mini `option_wizard`, read-only) + apex `/bars`
  for realized vol. Banked grid spans 2025-12-26 → 2026-07-02 (129 dates). **Zero UW/IB calls.**
- **Panel:** `{SPY, QQQ, NVDA, AAPL, TSLA, MU}` + the 10 tickers with the most ≥365-DTE
  rows on the latest date → 13 underliers (10 single-name, 3 ETF: SPY/QQQ/SMH). LEAP tenor =
  nearest expiry to **420 DTE** with DTE ≥ 365 (observed DTE p50 **427**, max 735).
- **Entry gap** (cheapness) = `max(HV20, HV60) − ATM_IV`, ATM IV **interpolated at δ=0.5**
  (not nearest-strike — kills coarse-LEAP grid jitter). HV from apex closes as-of the entry
  date (no look-ahead; EOD-consistent with the grid's 19:00-ET IV snapshot). Split-artifact
  guard drops any HV window with a `|1d log-ret| > 0.35`.
- **Forward outcome** = the **held contract's own** ΔIV: `call_iv(fixed strike, entry+h) −
  call_iv(fixed strike, entry)` over `h ∈ {20, 40}` grid-rows (grid dates verified == apex
  trading days). This is the *tradable* mark change, not a constant-moneyness convergence.
- **Primary metric = Fama-MacBeth cross-sectional IC** (per-date Spearman(gap, ΔIV) across
  names, averaged over dates) on the **single-name** panel. This is the only framing the data
  supports: the sample is cross-section-rich (10 names × 109 dates) and time-poor (one regime).
  The pooled rank-IC and hit-rate are reported but **confounded** by the regime's rising-IV
  drift (`baseline_mean_div` = +0.02 to +0.04) and are **not** the gate.

## Results (`convergence_metrics.csv`, `gap_observations.csv` — 2531 obs)

| horizon | FM IC (single-name) | non-overlap IC (n_dates) | loo_min IC | ETF IC | pooled hit-rate |
|---|---|---|---|---|---|
| 20d | **0.345** (t=13.6*) | 0.482 (n=**6**) | 0.292 | 0.239 | 0.68–0.75 |
| 40d | **0.431** (t=24.0*) | 0.588 (n=**3**) | 0.382 | 0.556 | 0.77–0.87 |

`*` the overlapping FM t is **autocorrelation-inflated** — daily entries with 20/40-day
forward windows are ~95% overlapping. Treat it as descriptive, not significance.

**Mean-reversion decomposition (the decider for "is it mechanical?"):**

| horizon | IC(gap) | IC(−IV) — mean-rev null | IC(HV-only) |
|---|---|---|---|
| 20d | 0.369 | **−0.136** | 0.247 |
| 40d | 0.465 | **−0.135** | 0.249 |

`gap` and `ΔIV` share the entry-IV term, so a positive IC *could* be the mechanical
`+var(IV)(1−ρ)` mean-reversion component. It isn't: `IC(−IV)` is **negative** (high-IV
names' IV rose *more* — cross-sectional IV momentum, the opposite of the feared artifact),
and **HV-only has a real +0.25 IC**. So realized vol genuinely forecasts forward IV here —
the signal is not a shared-variable illusion.

## The three caveats that keep this at "price it," not "trade it"
1. **Independent evidence is thin.** The binding non-overlapping sample is **6 dates (20d) /
   3 dates (40d)**. The point estimates are positive but n=3–6 independent observations over
   one regime is not significance, whatever the overlapping t says.
2. **Single regime, rising IV.** `baseline_mean_div` +0.02→+0.04: IV drifted up for
   *everything*. FM removes the common move within-date, but a 6-month up-vol regime can't
   tell you how the signal behaves when vol falls.
3. **Fixed-strike ΔIV conflates vega with skew/moneyness migration (codex #4).** The held
   strike slides across the smile as spot moves; high-HV names move more → more skew-driven
   IV change that is **delta/skew, not vega convergence**. Stage 2's `vega·ΔIV` vs `delta·ΔS`
   split is the only clean separation — and the real test of tradability.

## Read
There is a genuine cross-sectional relationship — high realized-vol names' long-dated IV
rises relative to their peers — and it is not the mechanical artifact I first suspected. But
"IV moves" ≠ "you get paid." Stage 2 decomposes the held-contract P&L and compares the
vega harvest (in vol points) against a realistic ATM-LEAP round-trip spread of **~1–5 vp**
(web-verified: mega-cap ≈1 vp, off-the-top names 2–5 vp). If the harvest is mostly delta, or
below spread, the radon thesis fails the taker test — matching argon's track record
(single-name surface geometry has repeatedly shown no taker edge; the SVI spike, PR #219).

## Reproduce
`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python -m scripts.research.leap_convergence_probe`
(needs the mini DB creds + a UW key present via `.env`/`.env.local`; **zero** UW/IB calls.)
Traces: `gap_observations.csv` (per-entry gap + forward ΔIV, 2531 rows), `convergence_metrics.csv`
(FM/pooled/panel/control metrics per horizon×threshold).
