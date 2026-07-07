# Implied-correlation / dispersion richness gate — falsification (issue #226)

**Date:** 2026-07-07
**Status:** NEGATIVE — do not build. Confidence MED.
**Reproduce:**
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \
uv run python scripts/research/implied_corr_gate.py
```
Full trace: `2026-07-07-implied-corr-gate-results.json` + per-trade `…-trades.csv` (this dir).

## Hypothesis

Index IV richness = **volatility premium + correlation premium**. The validated VRP-macro
edge (SPX bull-put-spread, Sharpe ~1.65) sizes only on **vrp-z** (IV−RV level). Implied
correlation richness was proposed as a *second, near-orthogonal axis*: when implied
correlation is high, index vol is rich relative to its components (the correlation premium),
so selling index vol should pay more. Test: **is index short-vol P&L monotone across
implied-correlation z-score buckets?** Non-monotone ⇒ gate dead.

## Method

- **Correlation measure — CBOE COR1M** (`vol_index_daily` symbol `COR1M`, the S&P 500
  1-month implied-correlation index, real data 2006-01-03 → 2026-05-29). This is the
  *actual* market-observed implied correlation — strictly better than the issue's
  hand-rolled top-10 proxy. **Cross-check:** I also built the issue's equal-weight top-10
  dispersion proxy `ρ ≈ (σ²_I − Σwᵢ²σᵢ²)/(Σ_{i≠j}wᵢwⱼσᵢσⱼ)` from `vrp_daily` component IVs
  (σ_I = SPY IV) on the 286-day overlap. **Pearson(proxy, COR1M) = 0.91 (n=263)** → COR1M
  faithfully represents the quantity the issue asked for. [COMPUTED]
- **Short-vol P&L — the validated machinery, unchanged:** `build_bull_put_spread`
  (`reports/vrp_structure.py`), flat-vol (VIX/100 = IV), short Δ0.25 / wing Δ0.125, hold 20
  trading days (VIX is constant-maturity 30d ⇒ 20d is the cleanest read), settled model-free
  at the realized SPX close, net normalized by `max_loss`, costs from `Settings`
  (0.65 / 0.01 / 0.05). Monthly-ROR Sharpe via `backtest.metrics.monthly_summary`.
- **z-scores:** trailing-252 (strictly backward, no look-ahead) on COR1M, VIX, and
  vrp = VIX/100 − RV20 (RV20 = trailing-20d realized vol of SPX log returns, ann.).
- **Window:** 2007-01-04 → 2026-04-30. **n = 244 non-overlapping (step=20d) trades**
  across 2008 / 2015 / 2018 / 2020 / 2022 stress regimes; 4,861 weekly-overlapping trades
  used only for resolution (their t-stats are inflated by ~2× and autocorrelated — the
  non-overlapping sample is the honest read).

## Results

### 1. Monotonicity — FAILS (inverted-U)

Non-overlapping COR-z quintile mean net (per-trade, normalized by max_loss):

| COR-z bucket | z range | n | mean net | t |
|---|---|---|---|---|
| Q1 (low) | −3.00…−1.04 | 49 | 0.054 | 1.02 |
| Q2 | −1.04…−0.52 | 49 | 0.024 | 0.40 |
| Q3 | −0.52…0.04 | 48 | 0.083 | 1.49 |
| Q4 | 0.04…1.00 | 49 | **0.157** | 3.63 |
| Q5 (high) | 1.00…3.80 | 49 | 0.081 | 1.36 |

The relationship is **hump-shaped**, not monotone: it rises to Q4 then the *highest*
COR-z bucket **gives the gains back**. Spearman ρ=0.60, **p=0.285** (not significant).
The weekly sample shows the identical shape (peak Q4 0.126, Q5 0.093). Economically
sensible: extreme implied correlation coincides with crisis regimes, where the realized-crash
channel cancels the correlation-premium channel. [COMPUTED]

### 2. Confound — COR-z is ~80% a VIX-level proxy

- **Pearson(COR-z, VIX-z) = 0.80**; Pearson(COR-z, vrp-z) = −0.09. [COMPUTED]
- Multivariate OLS `net ~ COR-z + vrp-z + VIX-z`:
  - **Non-overlapping (n=243, honest):** COR-z coef +0.049, **t = 1.45 (ns)**; vrp-z t=0.85 (ns);
    VIX-z t=−0.63 (ns); R²=0.014. **No axis survives on independent trades.**
  - Weekly (n=4841, overlap-inflated): COR-z t=7.4, vrp-z t=4.6, VIX-z −5.9 — but these
    t-stats are not trustworthy (overlapping, autocorrelated).

Once you control for VIX level, the COR-z effect is not statistically distinguishable from
noise on independent data. This is the same failure mode that killed the GEX
regime-persistence study (#228): the candidate signal co-labels a vol regime rather than
carrying independent information. [INFERRED, HIGH]

### 3. Sizing — a COR-z gate does not improve Sharpe

Non-overlapping monthly-ROR:

| sizer | Sharpe | maxDD | annROR | n |
|---|---|---|---|---|
| always-on | 0.732 | −3.11 | 1.007 | 244 |
| COR-z gate (size 1 iff z≥0) | 0.748 | −2.06 | 0.627 | 101 |
| COR-z ramp+ | 0.652 | −2.07 | 0.513 | 101 |
| COR-z **inverse** gate (z<0) | 0.363 | −4.10 | 0.388 | 143 |

The gate lifts Sharpe by 0.016 (0.732→0.748) — trivial, inside noise — while **halving
annual return**. The ramp is worse. The inverse gate is clearly worst, so the *sign* is
directionally as hypothesized (high COR ≳ low COR), but there is no risk-adjusted edge to
harvest. [COMPUTED]

### 4. Regime dependence — the sign flips

Per-year high-COR-z vs low-COR-z mean net: high-COR "wins" in most years but the effect
**inverts in 2020** (high 0.065 vs low 0.115) and collapses to regime noise in the 2022
selloff (high −0.063 vs low −0.457 — everything loses, high-COR just less). Not a stable,
tradable relationship. [COMPUTED]

## Verdict

**NEGATIVE — the implied-correlation gate is not a tradable second axis. Do not build.**
Confidence **MED** (n=244 independent trades, good regime coverage 2007–2026, but tiny
confounded effect size). The three falsification criteria all fail:
1. Short-vol P&L is **not monotone** in COR-z (inverted-U; top bucket reverts; Spearman p=0.29).
2. COR-z is **~80% collinear with VIX-z**, and its marginal effect is **insignificant
   (t=1.45)** on independent trades once vrp-z and VIX-z are controlled.
3. A COR-z gate delivers **no meaningful Sharpe gain** (0.732→0.748) and cuts return in half.

The correlation-premium intuition is real in sign but is dominated by / inseparable from
the VIX-level channel it rides on, and reverses in the crisis regimes where it would
matter most. Consistent with #228 (GEX) and #219 (SVI): a plausible axis that dies on a
regime confound. Re-test only with a genuinely orthogonalized measure (e.g. COR residual
after regressing out VIX term structure) and more non-crisis-clustered history.

## Data coverage / caveats

- COR1M is the real CBOE index but the pre-2021 history in the lake is likely
  reconstructed/backfilled by the market-data-warehouse; the 0.91 agreement with an
  independently-built component-IV proxy on 2025-26 data is the main validity check.
- Flat-vol pricing (single ATM IV, VIX applied at 20d) approximates absolute credit;
  the harvest *direction* is faithful (same approximation the committed VRP work uses).
- 244 independent trades is far better regime coverage than #228 (n=31) but still thin for
  quintile tails — hence MED not HIGH.
