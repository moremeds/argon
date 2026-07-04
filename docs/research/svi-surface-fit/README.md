# SVI Surface-Fit Feasibility Gate — 2026-07-04

**Question:** can raw-SVI fit argon's banked UW IV grid cleanly and arb-free enough
that the fitted-vs-marked residual is a trustworthy mispricing signal?

> **The fit is trustworthy — but the residual is NOT a tradable edge.** See
> [`residual-edge-test.md`](./residual-edge-test.md): the residual mean-reverts (real
> signal) yet the realizable, after-cost edge is ~\$0.18/contract — smaller than one
> option commission. A market-maker's edge, not a taker's. This gate is a green light to
> *understand* the surface, not to build a trade.

**Verdict: PASS (liquid names) / gate on liquidity.** On the six liquid underliers the
raw-SVI fit is sub-half-a-vol-point (RMSE p50 **0.47**, p90 **0.81**, max **1.02** vol
pts; 178/180 fits under 1 vol pt) and **100% butterfly-arb-free** — the residual there
is real signal, not fit noise. Thin chains (BKSY/NOV) degrade to p50 **1.77** / p90 **3.6**
vol pts with **10.8%** butterfly violations, so a productionized signal must gate on chain
liquidity/density, not fit the whole universe.

## Method
- **Source:** `option_surface_grid_daily` (mini `option_wizard`, read-only). Banked history
  spans 2025-12-26 → 2026-07-02 (129 dates); this probe sampled **10 dates × 8 tickers**.
- **Panel:** liquid {SPY, QQQ, NVDA, AAPL, TSLA, MU} + 2 runtime-thinnest tickers
  (BKSY, NOV) × nearest-to-{7, 30, 90} DTE (≥5-DTE floor; 0–4 DTE excluded, #207 lesson).
- **Forward anchor = the 50-delta strike** (`forward_from_delta`), *not* `underlying_spot`:
  the grid populates `underlying_spot` on only **5 of 129 dates** (≈4% of rows — a recent
  capture change), so anchoring on it would have restricted the gate to a week of data and
  fabricated a "6-month" claim. The `call_delta`=0.5 crossing is the textbook SVI forward
  `k=ln(K/F)` anchor and is present on ~all rows; validated against a real spot (SPY
  2026-07-02: F≈748 vs spot 745.64 = spot+carry). Real spot is only a last-resort fallback.
- **Wing clip = call_delta ∈ [0.05, 0.95]** (5-delta put … 5-delta call). The raw grid
  carries junk deep-wing marks — e.g. an SPY strike at k=−5.3 marked **470% IV** — that
  wreck the fit (unclipped, even the ATM bucket ran ~1.4 vol pts off, liquid p50 3.35). The
  delta band is DTE-adaptive for free and removes those without a hand-tuned |k| cutoff.
- **Smile from OTM wings** (`put_iv` for K<F, `call_iv` for K≥F): call/put IV disagree on the
  ITM leg (SPY K=727: cIV 0.177 vs pIV 0.149), so each strike takes its OTM (cleaner) mark.
- **Fit:** raw-SVI (Gatheral) via scipy `least_squares`, multi-start over (m, σ); bounds
  b≥0, |ρ|<1, σ>0. RMSE reported in vol points (1 pt = 0.01 IV).
- **No-arb diagnostics:** butterfly `g(k)≥0` (Gatheral density) scanned over the fitted k
  range; calendar total-variance monotonicity at k=0 across the {7,30,90} tenors per date.

## Results
- Fits: **217** (180 liquid, 37 thin).
- Fit RMSE (liquid): p50 **0.47** vol pts, p90 **0.81**, max **1.02**.
- Fit RMSE (thin): p50 **1.77** vol pts, p90 **3.61**, max **5.05**.
- Butterfly violation rate (min g<0): **0.0%** liquid, **10.8%** thin (**1.8%** overall).
- Calendar: **0** date-panels with a total-variance inversion at k=0.
- Failure mode on thin chains: dominated by **BKSY** (a ~$1 illiquid name) at short DTE —
  sparse, noisy OTM marks the smooth SVI form can't reconcile without bending into arb.

## Read
On liquid underliers the fitted-vs-marked residual is **trustworthy** (sub-vol-point,
arb-free) — a rich/cheap strike genuinely stands off its own smile rather than off fit
error. That is the green light to prototype the surface-mispricing signal, **but only where
the fit is clean**, so the productionized version needs: (1) a **liquidity/chain-density
gate** (strike count, delta coverage, min OI) to exclude the thin-chain regime that produced
10.8% arb here; (2) the **delta-forward + 5-delta wing clip** carried over verbatim — both
were load-bearing (without them the gate falsely reads FAIL); (3) an **IB-IV cross-check**
on flagged residuals before trusting any single mark. Calendar arb was absent on the 3-tenor
grid, but that check is coarse (only 3 expiries/date) — a real cross-expiry model (SSVI)
should precede any calendar-spread use. **Next step:** brainstorm/spec the residual→signal
layer with the liquidity gate as a first-class input, not the naive whole-universe fit.

## Caveats
- Sampled 10 of 129 banked dates (linspace) — a representativeness sample, not the full set.
  Reproduce reads live off the mini; re-run for the current grid.
- `underlying_spot` is unreliable pre-2026-06-22; this analysis deliberately does not depend
  on it. If a future signal wants true spot (not forward), backfill it first.
- Overlay PNGs (`figs/*.png`) are **not** committed (repo `.gitignore` blocks `*.png`);
  `overlays.csv` is the lossless durable trace. matplotlib is a research-only dep — the bare
  reproduce command emits the CSVs and skips figs; add `--group research` to render PNGs.

## Reproduce
`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python -m scripts.research.svi_surface_fit_probe`
(needs the mini's DB creds + a UW key present via `.env`/`.env.local`; makes **zero** UW/IB calls.)
Traces: `fits.csv` (per-smile params/RMSE/violations), `overlays.csv` (marked-vs-fit per
strike, ~30d), `figs/*.png` (per-ticker overlay plots, regenerated locally).
