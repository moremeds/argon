# Goyal & Saretto (2025) — IPCA for Equity Option Returns

**TL;DR.** The cross-section of delta-hedged equity-option returns — the same patterns dozens of "option anomaly" papers have published over 15 years — is largely explained by a single 3-factor IPCA model, and the first factor is essentially the **realized-minus-implied-volatility (RV−IV) spread**. After transaction costs, no strategy keeps a positive IPCA alpha.

## The headline numbers

| Strategy | Raw long-short return (mo) | IPCA alpha (mo) | Explained |
|---|---:|---:|---:|
| RV−IV (10−1) | 2.87% (*t*=24.5) | 0.34% (*t*=4.7) | 88% |
| IV ATM (1−10) | 2.34% (*t*=17.9) | 0.24% (*t*=4.6) | 90% |
| IV slope (1−10) | 2.15% (*t*=25.5) | 0.34% (*t*=4.6) | 84% |
| Stock price (1−10) | 1.73% (*t*=16.1) | 0.09% (*t*=0.65) | 95% |
| MarketCap (10−1) | 1.59% (*t*=16.7) | 0.11% (*t*=1.00) | 93% |

(Paper Table 1 and Table 3. After Benjamini-Hochberg 5% FDR — *t* > 2.6 — only **RV−IV** and **IV slope** keep significant IPCA alphas. Net of 30% effective/quoted transaction costs, *zero* strategies do.)

## How the paper argues it

1. **46 long-short portfolios look highly inefficient** — 39 statistically significant, several with *t* > 10. Raw monthly returns 0.04%–2.87%.
2. **A 3-factor IPCA with no intercept (Γ_α = 0) eats the alpha.** Average residual alpha ≈ 6bp. Only 2 of 46 survive MHT.
3. **The first factor is dominated by RV−IV.** Set Γ_β for RV−IV to zero → 32 other strategies see alpha *increase* ~1%/mo. RV−IV doesn't just explain the RV−IV strategy; it indirectly explains most others through dynamic-beta loadings.
4. **Transaction costs kill what's left.** At 30% effective/quoted spread ratio, IPCA alphas turn negative for all 46.

## Method in one sentence

For each stock-month, project a 46-dimensional characteristic vector Z_{i,t} through a fixed L×K mapping Γ_β to get a time-varying β_{i,t} = Z'_{i,t} Γ_β; the K=3 latent factors F_t are estimated jointly via the Kelly-Pruitt-Su (2019) two-step EM until convergence. No factor portfolios are pre-built — IPCA discovers them.

## What's at stake for this codebase

- Confirms RV−IV / VRP is doing the most economic work among option-side signals. (Already central to CRI.)
- Suggests that piling more option-side cross-sectional signals on top of RV−IV gives diminishing returns absent stock-side context (size, assets, profitability are the *only* non-VRP characteristics that matter in their Γ ranking).
- After transaction costs, no signal in their universe survives — so any "alpha" we surface in `scanner/ranking` is either (a) a duplicate of RV−IV captured via correlation, or (b) gross of frictions we're not accounting for.

See [`CLAUDE.md`](CLAUDE.md) for the file index and [`05-replication-plan.md`](05-replication-plan.md) for how the 46 paper-defined features map to what UW exposes today.
