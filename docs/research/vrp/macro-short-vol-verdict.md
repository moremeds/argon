# Macro Short-Vol Harvest — Verdict (2026-06-22)

**Question.** The single-name condor failed (edge inside the bid/ask spread —
[`single-name-condor-verdict.md`](./single-name-condor-verdict.md)). Does a
defined-risk structure *matched to a directional view* harvest the macro VRP at
positive risk-adjusted P&L — and does it **survive a drawdown**?

**Two tests**
1. **11-month per-name sweep** (`vrp_daily`): SPY/SPX/QQQ/IWM × {iron condor, bull
   put spread, cash-secured put} × gate × short-delta × horizon, entry-spaced,
   honest holdout. → `vrp_macro_sweep_results`, engine `reports/vrp_macro_harvest.py`.
2. **Decisive 20-year drawdown** (`SPX + VIX` from `vol_index_daily`, 2006–2026,
   VIX/100 = SPX 30-day IV; index → no corp actions/earnings). 244 entry-spaced
   trades, hold=20, always-on. Engine `reports/vrp_macro_drawdown.py`. Stress years
   {2008, 2009, 2011, 2015, 2018, 2020, 2022} bucketed separately.

## Findings

**A. The edge survives the drawdown.** Bull put spread on SPX over 20 years is
positive at every delta (mean ROR +0.057 → +0.115), wins 83–91% vs a 72–85%
break-even, max drawdown only −2.4 → −4.9 risk-units. It **does not blow up in
selloffs** — the defined-risk wing caps the tail, so it goes ≈flat in stress years
(combined stress ROR ≈ +1) and earns in calm (≈ +23). The "it's just bull-market
beta" fear is **refuted**.

**B. Surprise — over a full cycle the iron condor *looks* best** (+0.156 ROR, +38
total, and **positive +7.5 in stress years**): its call side profits when the market
falls, hedging the put side across regimes. The 11-month "condor loses" was a
*bull-market artifact* — the 2025–26 rally bled the short calls.

**C. …but the condor's edge is partly a flat-vol artifact — the bull put spread's is
not.** Flat-vol prices every leg off ATM IV (VIX). For an index that means:
- put side: real OTM put IV > ATM (steep put skew) → model **under**-states the put
  credit → the **bull put spread is biased conservative** (real fills are *better*).
- call side: real OTM call IV < ATM → model **over**-states the call credit → the
  condor's extra return rides on an optimistic call assumption real skew would
  deflate.

So the **bull put spread is the cleanly-validated, drawdown-robust winner**; the
condor is promising but needs real-fill confirmation of its call-side contribution
before the +0.156 is trusted.

**D. Cash-secured put is out.** 88% win, but ROR ≈ 0 in *both* tests — it ties up
strike×100 of capital to earn nothing risk-adjusted (denominator effect). High
win-rate ≠ capital efficiency.

**E. Structure choice is regime-dependent.**
- **Sustained bull (the current view) → bull put spread** — drop the call side that
  bleeds in a rally.
- **Full cycle / two-sided risk → iron condor** — the call side hedges selloffs (but
  confirm the call credit with real fills first).

**F. IWM on put structures works.** Adding IWM to the put structures (per request):
bull put spread +0.072 ROR / +0.087 win-edge (11-month, n≥10); IWM **condor is
negative** (−0.044). So IWM belongs in the bullish put-spread bucket, not the condor.

## Delta selection (bull put spread)

Short-delta is a pure risk/return knob (wing = short × 0.5):

| short Δ | 20yr mean ROR | win vs breakeven | breach | maxDD | use |
|--:|--:|--:|--:|--:|---|
| 0.16 | +0.057 | 91% vs 85% (+6) | 10% | −2.4 | conservative (widest safety margin) |
| **0.25** | **+0.098** | 87% vs 77% (+10) | 16% | −4.2 | **balanced default** |
| 0.30 | +0.115 | 83% vs 72% (+11) | 20% | −4.9 | aggressive (highest return, deepest DD) |

**Default: sell 0.25Δ put, buy 0.125Δ wing.** Best return with a comfortable
win-margin; 0.16Δ if you want the fattest cushion, 0.30Δ to push return.

## Entry / exit

- **Entry — systematic, always-on, one position at a time** (entry-spaced), **20-DTE**,
  sold at the daily close. Gating on VRP-z tested no better than always-on — the
  macro VRP is persistent, so the rule is simply "always be short, one at a time."
- **Exit — hold to expiry** (current baseline; model-free settlement at realized
  price). The defined-risk wing *is* the stop — no separate stop needed.
- **Management (next refinement, untested):** close winners at ~50% of max credit to
  cut gamma/tail exposure near expiry; consider not re-entering while VIX is in the
  top decile (avoid selling the very cheapest relative premium). Requires daily
  model-marking — the forward **NBBO recorder** enables real marks.

## Caveats

- VIX is constant-maturity 30d IV applied across horizons → **hold ≈ 20d is the clean
  read** (5d/45d are rougher proxies).
- Flat-vol credit ignores skew (see C). Net for the **bull put spread**: conservative
  → real ≥ modeled. For the **condor**: call side optimistic → confirm with real fills.
- SPX index ≈ SPY. **QQQ/IWM long-history drawdown not yet run** — needs VXN/RVX (have)
  + NDX/RUT or ETF prices from the lake (extension).
- Single regime of *real-fill* data still absent; the NBBO recorder (forward-only) is
  the remaining gap between "robust in a conservative model" and "traded."

## Refinements (management, breadth, portfolio) — two priors refuted

Follow-up tests (`reports/vrp_macro_drawdown.py` now multi-index + profit-take aware,
Sharpe via monthly-return series, rf earned on collateral so harvest = excess):

1. **50%-profit-take management does NOT help — it slightly hurts.** SPX bull put
   spread Sharpe **0.92 → 0.76** with a 50% take-profit (more trades 244→509, higher
   win 87%→91%, but lower mean ROR +0.098→+0.046 and *worse* maxDD −4.2→−6.6). The
   conventional "close at 50%" benefit is avoiding late-cycle gamma/pin risk — but our
   structure is *already* defined-risk and settles model-free at the wing, so
   management only forfeits the back half of winners while keeping full-size losers,
   and the earlier re-entries add breach exposure. (Real-world gamma/assignment
   benefit isn't modeled, so not fully ruled out — but on modeled P&L it's negative.)
2. **The edge is SPX-concentrated; it does NOT broaden.** Bull put spread, hold,
   2009–2026: **SPX Sharpe 0.92 → QQQ 0.27 → IWM −0.05.** QQQ is marginal, IWM is
   flat-to-negative (higher realized vol / smaller VRP; VXN/RVX-on-ETF-price is also a
   looser proxy than VIX-on-SPX). This is really an *SPX* short-vol edge, not a broad
   macro one.
3. **Naive 3-name diversification LOWERS the Sharpe** (equal-weight SPX+QQQ+IWM bull
   put spread: **Sharpe 0.57 < SPX-alone 0.92**, though maxDD improves to −1.9). The
   added names are lower-quality, so they dilute faster than diversification helps —
   "diversification raises Sharpe" only holds for *comparable-quality* uncorrelated
   sleeves, which QQQ/IWM are not here. A quality-weighted book is ≈ "just trade SPX."

**Net:** the honest, defensible edge is **SPX bull put spread, 0.25Δ/0.125Δ, 20-DTE,
always-on, held to expiry, no profit-take, Sharpe ≈ 0.9.** Management, breadth, and
naive diversification did not improve it.

## Position count, overlap inflation & weekly laddering

**Steady state = one position at a time.** The backtest enforces entry-spacing
(`select_non_overlapping`: next entry > prior exit), so the equity curve is a single
SPX bull put spread rolled to expiry — **~12 non-overlapping trades/year**, hold ≈ 1
calendar month, one short-put/long-put pair open at any instant (244 trades over
2006–2026 = 12.2/yr). The headline Sharpe ≈ 0.9 is measured on this basis.

**Why "always-on, every RICH day" inflated the naive number.** Opening a fresh 20-day
spread *every* day leaves ~20 overlapping spreads open at once. Adjacent spreads share
19 of their 20 days — same underlying, same direction, ~95% the same bet. Summing their
P&Ls as if independent inflates two ways: (1) **leverage dressed as edge** — 20
concurrent spreads = 20× capital, so the dollar total is ~20× bigger for no improvement
per unit of risk; (2) **fake sample size** — ~20 near-identical samples masquerade as 20
independent data points, smoothing the curve and overstating statistical confidence.
Entry-spacing zeroes both (the ultra-conservative bound); the single-name condor's naive
+$110k holdout was ~97% this artifact.

**Weekly laddering — sizing decides whether it helps or just levers.** Hold = 20 trading
days = 4 weeks → a weekly cadence holds **4 overlapping rungs** in steady state (~52
entries/yr). The rungs stay highly correlated — a crash breaches all four the same week,
so *that* tail is not diversifiable:

| sizing | return | crash tail | Sharpe effect |
|---|---|---|---|
| 4 full-size rungs | ~4× | ~4× loss | ≈ unchanged (4× return for 4× risk) |
| 4 quarter-size rungs (constant book risk) | ≈ 1 position | ≈ 1 position | modestly better |

The constant-risk ladder diversifies *entry timing* across 4 weeks (no longer hostage to
one day's vol/spot) at the same tail — a genuine but small gain, partially offset by **4×
transaction costs** (52 vs 12 round-trips/yr). Net sign is ambiguous until measured on
the aggregate book — see the open experiments below.

## Open experiments (next)

1. **Weekly 4-rung ladder** — aggregate-book Sharpe + maxDD, both sizings, net of 4×
   costs, full 2006–2026; plus a VRP-gated variant (add a rung only when vrp-z is rich).
2. **Delta × DTE sweep** for a sweet spot (short-Δ {0.10…0.35} × DTE {7,14,20,30,45}).
3. **VRP-conditional de-risking at higher delta** — cut or skip size as VRP falls toward
   −0.5 (premium gone from rich to cheap → stop selling it), where the breach tail bites.

## Verdict

**This is a real, drawdown-robust edge** — the first in the whole VRP investigation —
but a **narrow** one (SPX-specific, Sharpe ~0.9, ~10%/yr responsibly sized).
The macro short-vol **bull put spread** (0.25Δ/0.125Δ, 20-DTE, always-on) clears its
breakeven over 20 years *including 2008/2020/2022*, the defined-risk wing caps the
tail, and the conservative flat-vol model *understates* it. For the current bull
regime it's the right structure; the iron condor is the all-weather candidate pending
real-fill confirmation of its call side. CSP rejected. Next: management rules,
real-fill NBBO, and QQQ/IWM long-history.
