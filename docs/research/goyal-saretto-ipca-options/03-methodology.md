# 03 — Methodology

All page references are to the RFS-version PDF in `_references/goyal-saretto-2024.pdf` (mirrors the journal pagination 1783–1821).

## 1. Return definition (the dependent variable)

**Delta-hedged call returns, expiration-to-expiration, daily-rebalanced delta.** Equation (1), p.1789:

```
DHCall_{t+1} = [(C_{t+1} − C_t) − Σ_{n=0}^{N−1} Δ_{d_n} · (S_{d_{n+1}} − S_{d_n})] / (Δ_t S_t − C_t) − R_{f,t+1}
```

Concretely:
- Open the position on the **Monday after expiration** (residual maturity ≈ 25 calendar days).
- Hold to **expiration Friday** of the next month.
- Rebalance the hedge **daily** with that day's Δ.
- Scale gains by (Δ_t S_t − C_t) so the denominator is always positive — therefore the return is the *negative* of writing a delta-hedged call.

Why this matters for replication: most academic option-return work uses month-end-to-month-end. Goyal-Saretto's choice avoids selection issues from Duarte-Jones-Khorram-Mo (2023). UW's flow data is daily and contract-level, so this is reconstructible — but it means we have to know each contract's Δ each day, which means relying on either the UW-supplied surface or our own daily re-mark.

**Robustness checks (Internet Appendix IA4, IA5):** delta-hedged puts, straddles, and month-end-to-month-end returns. Not in the main paper PDF.

## 2. Sample and filters (§2.1, p.1788–1789)

- **Source:** OptionMetrics, Jan 1996 – Dec 2022 (324 months).
- **Stock universe:** CRSP share codes 10 or 11 (US common stock).
- **All-observation filters (eliminate non-standard or arbitrage-violating contracts):** standard settlement; standard expiration (no weeklies); 100-share contract size; both bid and ask quotes present; ask ≥ bid; bid-ask spread ≥ minimum tick (5¢ for px ≤ $3, 10¢ for px > $3); midpoint price ≥ exercise payoff; |Δ| ≤ 1 with proper sign.
- **First-leg-of-return filters:** ATM (strike/spot ∈ [0.8, 1.2]); positive volume or positive open interest; midpoint price > 25¢; percentage bid-ask spread < 50%.
- **Dividend filter:** exclude underlying stocks paying a dividend during the holding period (avoids early-exercise issues for American calls).

## 3. The 46 characteristics (Appendix A, p.1815–1817)

Four families. Bolded names below are the ones with the largest Γ-impact in Table 5, in descending order.

### A.1 Contract characteristics (8)

`Moneyness`, `Bid-ask spread`, `Open interest`, `Delta`, `Vega`, `Gamma`, `Volume`, `Option price` ($ midpoint)

### A.2 Risk-neutral distribution measures (8)

`IV ATM` (ATM IV on 30-day surface), `IV slope` (OTM−ATM on 30-day surface; OTM = strike/spot = 0.8), `IV term` (360d ATM − 30d ATM), `IV vol` (stdev of Δ=0.5, 30d IV over last month, ≥15 obs), `MFvol` (model-free implied vol from 30d OTM C+P, Bakshi-Kapadia-Madan 2003), `MFskew`, `MFkurt`

### A.3 Physical distribution measures (9)

`Stock return` (last month), `Stock return11` (last 11 months skipping the most recent), **`RV`** (log-return realized vol over last 12mo, daily, ≥150 obs), `Rskew`, `Rkurt`, `Turnover`, `IdiosynVol` (FF3-residual stdev over last month, ≥10 obs), `Max10` (avg of 10 highest daily returns over last 3 months), `Autocorrelation` (last 6mo, ≥100 obs)

### A.4 Physical − risk-neutral differences (4)

**`RV−IV`** (the headline), `RV−MFvol`, `Rskew−MFskew`, `Rkurt−MFkurt`

### A.5 Stock-level firm characteristics (17)

`BM`, `Profitability`, `InstOwn` (TR 13f), **`MarketCap`**, `RSI` (Ramachandran-Tayal 2021), **`Assets`** (Compustat AT), `Debt` (DLTT + DLC), `Leverage` (debt/assets), `CashFlowVar`, `Cash to asset`, `AnalystDisp` (IBES), `1yr NewIss`, `5yr NewIss`, `Profit margin`, **`Stock price`** (Blume-Husic 1972), `ROE` (FF 2006), `ExternalFin` (Bradshaw-Richardson-Sloan 2006), `Z-score` (Dichev 1998)

**Rank-transform pre-IPCA:** all 46 characteristics are converted to cross-sectional ranks ∈ [0,1] each month, then normal-inverse-CDF-transformed to z-scores ≈ [−3, 3] (footnote 9, p.1796). The constant is added as a 47th column.

## 4. The IPCA model (§3, p.1792–1796)

### Setup — Equation (2)

```
R_{i,t+1} = α_{i,t} + β'_{i,t} F_{t+1} + ε_{i,t+1}
            = (Z'_{i,t} Γ_α) + (Z'_{i,t} Γ_β) F_{t+1} + ε_{i,t+1}
```

- `R_{i,t+1}` : delta-hedged call return for stock *i* in month *t+1*.
- `Z_{i,t}` : L×1 vector of 46 z-scored characteristics + a constant, **observed at t**.
- `Γ_α` : L×1, static mapping from characteristics to a (potentially absent) intercept.
- `Γ_β` : L×K, **static** mapping from characteristics to factor loadings. K = number of latent factors. The dynamic-beta structure comes entirely from `Z` moving over time.
- `F_{t+1}` : K×1 latent factor realizations, **estimated**, not observed.
- `α_{i,t}`, `β_{i,t}` : implied by Γ_α, Γ_β through the linear projection.

### Matrix form — Equation (3)

```
R_{t+1} = (Z_t Γ_α) + (Z_t Γ_β) F_{t+1} + E_{t+1}
```

with R_{t+1} = N_{t+1}×1, Z_t = N_{t+1}×L. The trick: define `W_t = Z'_t Z_t / N_{t+1}` (L×L) and `X_{t+1} = Z'_t R_{t+1} / N_{t+1}` (L×1) — the latter being the **managed-portfolio return** for each characteristic.

### First-order conditions — Equation (4)

```
F_{t+1}    = (Γ̂'_β W_t Γ̂_β)^{-1} Γ̂'_β (X_{t+1} − W_t Γ̂_α)

vec(Γ̂')   = (Σ_t W_t ⊗ F̂_{t+1} F̂'_{t+1})^{-1} Σ_t X_{t+1} ⊗ F̂_{t+1}
```

OLS-style updates; iterate to convergence. **Initialize** Γ_β to the first K eigenvectors of the sample second moment of the managed-portfolio returns, F to the first K PCs of that panel. Converges quickly because Z'Z isn't very volatile (p.1794).

### Identification

`Γ_β P · P^{-1} F` is observationally equivalent to `Γ_β F` for any L×L `P` — so impose:
1. `Γ'_β Γ_β = I_K` (orthonormal columns of Γ_β),
2. Unconditional second moment of F diagonal with descending diagonal entries,
3. Time-series average of F positive,
4. In the **restricted** model where `Γ_α = 0`, additionally `Γ'_α Γ_β = 0` (not binding since Γ_α is forced to 0).

### Choice of K

Two model selections:
- **Constrained (Γ_α = 0)** — used in the headline results. K varies 1→5; **K = 3** is the chosen baseline. Three reasons: (a) bootstrapped Wald test of unrestricted-α rejects H₀ of zero α for K ≤ 4, (b) for K ≥ 4 some estimated factors are statistically zero-premium (unpriced), (c) Table 2 shows R²s nearly saturate at K = 3.
- **Unrestricted** — used to compute portfolio-level alphas in Table 3 once Γ_β is fixed from the constrained fit.

### Pricing metrics (§3.2)

- **Total R²** = 1 − Σ ε²/Σ R² (Gu-Kelly-Xiu 2020 panel form, NO demeaning).
- **Time-series R²** = avg-over-i of per-asset time-series R².
- **Cross-section R²** = avg-over-t of per-month cross-sectional R².
- **Relative pricing error** = Σ_i α²_i / Σ_i R̄²_i — *not* α'α / R'R, this one weights by long-run return magnitude.

### Standard errors (Appendix B, p.1817–1818)

α-standard errors require bootstrap because both Γ̂_β and F̂ are estimated. They bootstrap the latent-factor estimation (B = 1,000 reps) using Student-*t* (df=5) draws, then compute Wald statistics on Γ_α and Γ_β.

## 5. Long-short portfolio construction (§2.2, p.1790)

For each of 46 characteristics:
- Sort stocks into **10 deciles** on the prior Monday (positions held Mon-to-Fri-after-next-expiration).
- Compute equal-weighted average delta-hedged call return per decile, midpoint price.
- Form **10−1 or 1−10** long-short to make the full-sample average return positive (Table 1, "Construction" column shows the direction).
- That long-short series is what Table 1, Table 3, Table 6, and Figures 1, 3 plot.

## 6. Transaction cost overlay (§2.2, p.1792)

Following Muravyev & Pearson (2020):
- **ESPR/QSPR = 30%** (effective-to-quoted spread ratio).
- Buy at `mid + 0.30 × half-spread`, sell at `mid − 0.30 × half-spread`. Example given: bid $3, ask $4 (mid $3.50). Buy at $3.65, sell at $3.35.
- Only the **initiation leg** incurs costs — exit is at expiration, no further trading.
- Daily delta-rebalancing happens in the *underlying stock*, where TC ≈ 0 for our purposes.

After TC: 16 of 46 strategies still have significant gross returns; **all 46 have negative IPCA alphas** (Internet Appendix Figure IA1).

## 7. Multiple-hypothesis-testing correction (Benjamini-Hochberg)

- 5% FDR cutoff applied to the 46 strategies as one family per table.
- Footnotes give the cutoff *t*-stats: **Table 1 = 2.25** (mean return) and **2.44** (TC-adjusted return). **Table 3 = 2.60** (IPCA alpha).
- Table 6 reports the cutoffs per period for the Zhan-et-al-10 restricted set: 2.22 / 2.06 / 3.11 raw and 3.12 / 3.21 / 3.29 alpha across full / in-sample / out-of-sample.

## 8. What's deferred to the Internet Appendix

- IA1 — net-of-TC IPCA alphas figure (the source of the "all 46 negative" claim).
- IA2 — pricing portfolios sorted on liquidity, moneyness.
- IA3 — delta-hedged puts and straddles.
- IA4 — month-end-to-month-end returns.
- IA5 — daily-rebalanced delta-hedged calls (the version Cao-Han 2013 / Zhan-et-al-2022 use).
- IA Tables IA1–IA5 — robustness pricing-error tables corresponding to those samples.

If we want to fully replicate, the IA needs to be pulled from the OUP supplementary page.
