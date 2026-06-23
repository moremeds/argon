# Macro Short-Vol Base Case — Mac Mini Production Run (2026-06-23)

Run of the deployed **base case** (`WINNER`) against the mac mini production DB
(`option_wizard` @ `100.66.147.98`), freshest data: **vol_index_daily through
2026-06-18** (SPX) / **2026-06-19** (VIX). Reproduce: `scripts/research/vrp_capital_sweep.py`
(sweep) + `base-case-mini-sweep-2026-06-23.csv` (this run's full trace). All numbers
`[COMPUTED]` from the reconciled ledger (engine Δ Sharpe 0.000).

## 1. What the base case IS — entry / exit rules

The base case is `MacroSignalConfig` defaults (`WINNER` in `reports/vrp_macro_signal.py`):

| Element | Rule |
|---|---|
| **Structure** | Bull put spread (defined-risk): **sell 0.25Δ put, buy 0.125Δ put** as the wing/stop |
| **Underlying signal** | Index IV proxy = VIX/100; realized vol = 20d; **VRP = IV − RV**, z-scored over trailing 252d |
| **Entry cadence** | **Weekly** — a candidate every 5 trading days |
| **Entry gate** | `ramp+`: trade only when **vrp_z > 0**; size = `clamp(vrp_z / 0.5, 0, 1)` (0 at z≤0, full at z≥0.5). Vol must be *rich* to deploy |
| **Hold / exit** | **30 trading days ≈ 43 calendar days**, held to expiry, settled at intrinsic (no profit-take, no stop — the long wing is the defined-risk floor) |
| **Pricing** | Flat-vol Black–Scholes (skew ignored → modeled credit is a conservative floor) |

## 2. Base case headline (capital-blind ROR — the canonical "1.6 Sharpe")

`backtest_laddered(SPX, WINNER)` — scale-invariant return-on-risk, constant-risk slot
account (every slot funded, no $ cap):

| Window | Sharpe | annROR | maxDD | Calmar | rungs |
|---|---|---|---|---|---|
| **Full 2006→2026-06-18 (incl. 2008)** | **1.652** | 0.530 | −0.796 | 0.67 | 522 |
| 2009→2026-06-18 (excl. 2008) | 1.834 | 0.566 | −0.590 | 0.96 | 480 |

**1.652 is THE base-case number** (full history). 1.834 is the post-2008 slice.

## 3. The $50k tradeable reality — base_risk_pct, util, skip%, frequency

Same WINNER, run as a real **$50,000 cash account** (integer contracts, capital-capped).
`base_risk_pct` = fraction of $50k a full-size (w=1) rung risks. One SPX spread ≈ **$15.7k
margin (31% of $50k)** at today's index level; one SPY spread ≈ **$1.7k (3.4%)**.

### SPX direct (cash-settled, European, §1256 — fully tradeable)

| base_risk_pct | Sharpe | CAGR gross | util mean | util peak | skip% | fill% | win% | breach% | rungs | entries/yr |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 1.43 | 14.2% | 0.31 | 1.00 | 0.4% | 98% | 91% | 11% | 279 | 17.9 |
| **0.32** | **1.98** | 16.6% | 0.49 | 1.00 | 14% | 78% | 93% | 9% | 325 | 18.9 |
| 0.50 | 1.87 | 17.7% | 0.61 | 1.00 | 31% | 55% | 93% | 9% | 296 | 17.1 |

### SPY direct (same signal, 1/10th lump → granular)

| base_risk_pct | Sharpe | CAGR gross | util mean | util peak | skip% | fill% | win% | breach% | rungs | entries/yr |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 1.43 | 11.1% | 0.24 | 0.59 | 0% | 100% | 90% | 12% | 463 | 26.7 |
| 0.20 | 1.56 | 14.7% | 0.49 | 1.00 | 0% | 96% | 90% | 12% | 478 | 27.6 |
| 0.35 | 1.63 | 16.4% | 0.64 | 1.00 | 16% | 71% | 91% | 12% | 410 | 23.7 |
| 0.50 | 1.62 | 17.1% | 0.70 | 1.00 | 26% | 54% | 91% | 11% | 360 | 20.8 |

**Reading it:**
- **base_risk_pct is the master dial.** It sets how much of $50k each rung risks → directly
  drives utilisation and skip-rate. Low (0.10–0.20) → low util, ~0 skips, clean. High
  (0.35–0.50) → util 0.6–0.7 but a quarter-to-third of desired size goes unfilled.
- **util mean** never exceeds ~0.7: the ramp+ gate forces idleness when vol is cheap. The
  $50k is *meant* to sit partly in cash earning rf — that idleness is the cost of the edge.
- **skip%** is the capital-binding frequency: 0 when the per-rung budget comfortably funds
  the lump, climbing as you push size. At SPX/0.50, **31% of rungs can't open** and **fill
  is only 55%** — you're leaving half the desired exposure on the table.
- **SPX < base_risk_pct 0.31 silently can't trade recent years** (lump > budget once the
  index is high); SPY has no such gap (util_peak < 1 only at brp 0.10).

## 4. Entry / exit & trade frequency — realized (SPX, base_risk_pct 0.32)

- **325 rungs over 17.2y**, span 2009-01-02 → 2026-03-02.
- **Hold:** median **43 calendar days** (mean 43.5, range 42–47) — the 30-trading-day hold.
- **Gap between entries:** median **8 days** (consecutive weeks fire), mean **19.2 days**
  (the gate skips cheap-vol weeks, stretching gaps).
- **Realized frequency: ~19 entries/yr** at $50k — i.e. the weekly slot actually opens
  **~36% of weeks**. (The gate alone opens ~28–32 weeks/yr; capital binding at $50k/0.32
  trims it to ~19.) **This is not a weekly trade in practice — it's ~biweekly, clustered
  in rich-vol regimes.**
- **Last 5 SPX rungs** (1 contract each, ~$13–16k margin): net +$3,779 / +$3,056 / +$3,176
  / +$3,165 / +$3,240 — all held clean to expiry, no breach.

## 5. This week's live signal (as of 2026-06-18, mini)

`current_macro_signal(SPX)`: spot **7501**, IV 0.164, **vrp_z −1.95**, weight **0.00**,
**action = SKIP**. Vol is *cheap* right now → the ramp+ gate is shut → **stand aside**. A
live confirmation that the base case is a rich-vol harvester, not an always-on seller.

## 6. Consolidated conclusion

- **The base case is real and current:** Sharpe **1.652** capital-blind on data through
  2026-06-18, unchanged from the deployed figure.
- **It is tradeable on $50k two ways, both single-name S&P:**
  - **SPX direct** — best Sharpe (1.4–2.0), cleanest settlement/tax, but ~31%-of-account
    lumps; needs base_risk_pct ≥ ~0.31 to trade every year; ~19 entries/yr.
  - **SPY direct** — Sharpe 1.43–1.63, fully granular, trades every gate-open week
    (~27/yr), no silent gaps. The pragmatic $50k vehicle.
- **Do NOT dilute into a 3-name book.** Adding QQQ (single-name Sharpe 1.01) and especially
  **IWM (0.438, −128% maxDD)** drags the blended book to ~1.0 Sharpe. Single-name S&P wins.
- **Sizing is the only real lever:** base_risk_pct trades return for drawdown and skip-rate;
  the overlay (sell extra when very rich) is leverage, not edge (flat Sharpe).
- **Recommended deployable:** SPY at base_risk_pct ~0.20 (Sharpe 1.56, CAGR ~15%, ~0 skips,
  util 0.49, ~28 entries/yr) for granularity, or SPX at base_risk_pct ~0.20–0.32 if you
  accept the lump and want the top Sharpe. Gate stays ramp+ (idle when vol cheap — as it is
  right now).

## Caveats

- Flat-vol BS ignores skew → modeled credit is a conservative floor (real put-skew credit ≥
  modeled); no real-fill NBBO.
- SPX margin scales with index level; the base_risk_pct ≥ 0.31 "trades-every-year" floor is
  a today-level figure (SPX 7501).
- The SPX/0.32 Sharpe 1.98 is partly capital-cap-as-quality-filter (binding funds only the
  richest weeks) — fragile/in-sample; the robust SPX read is base_risk_pct 0.20 (Sharpe 1.43,
  0 skips).
- Window excludes 2008 for the $50k ledgers (min_date 2009-01-01); the capital-blind 1.652
  includes it.
- T+1 settlement not modeled (margin frees at expiry, same-day reuse) — minor optimism on
  expiry-day entries.
