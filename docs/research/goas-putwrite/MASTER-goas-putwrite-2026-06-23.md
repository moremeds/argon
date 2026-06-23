# GOAS Put-Write Delta Sweep — Findings (2026-06-23)

**Exploratory research.** Skew shape is MODELED (calibrated to one real GOAS quote), not observed — flat-vol is the conservative floor, skew the GOAS-faithful estimate; the truth is bracketed between them.

## Sweet spot (net-of-fee Sharpe @ 100bps, per-regime catastrophe gate applied)
- Flat-vol top: {'delta': 0.3, 'dte': 63, 'pricing': 'flat', 'sharpe': 0.07559823940292629, 'ann_return': 0.04375312632882933, 'max_drawdown': -0.26750276886229396, 'calmar': 0.16356139607419437}
- Skew top:     {'delta': 0.3, 'dte': 63, 'pricing': 'skew', 'sharpe': 0.14659643031192296, 'ann_return': 0.0488898341215207, 'max_drawdown': -0.2197709025958977, 'calmar': 0.22245817596434303}
- Flat & skew AGREE on top (delta, dte): **True**

## GOAS validation
- Calibration anchor: 2026-05-05 SPY=723.77 VIX=17.38; target strike 0.962·S, premium 0.007·S (~7.7% annualized in GOAS's table).
- Net result at ~15Δ / 1-month vs GOAS's 3–6% net: see the fee column in goas-delta-dte-sweep CSV.

## SPY buy-and-hold (price-return): Sharpe 0.34, maxDD -56.46%, CAGR 9.07%

## Methodology: cash-secured (defined-risk); the collateral earns the risk-free (4%, CBOE PUT-index convention), so reported total return ≈ rf + premium harvest — the harvest ABOVE cash is (total − rf). GOAS's 3–6% net is a premium-harvest figure on leveraged (20–40%) collateral, so it is NOT directly comparable to our unlevered total return.

## Caveats: constant-slope modeled skew (understates crisis put richness → premiums are a conservative floor); the sweet spot sitting at the grid edge (max delta/tenor) suggests Sharpe under-penalizes the tail — read with the drawdown/CVaR columns, not Sharpe alone; European cash-settle vs GOAS's American roll-managed book; price-return SPY benchmark (no dividends); VIX constant-maturity 30d applied across tenors.

## Honest de-rating: the headline is the best of 24 cells × 2 pricing modes — expect favorable-corner overfit; de-rate the in-sample Sharpe and prefer the delta that wins under BOTH pricing modes and all regimes.

## Reproduce:
```
uv run python scripts/research/goas_putwrite_run.py
```
