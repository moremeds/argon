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

## Entry / exit (original baseline — SUPERSEDED, see "Deployable entry/exit signal")

> ⚠️ The "gating tested no better than always-on" claim below was the **11-month
> window** (uniformly rich). On the full **20-year** history the vrp-z gate is the
> single most valuable lever — see *Experiment results* and *Deployable entry/exit
> signal* further down. The current deployable rule is **weekly, vrp-z-sized, DTE≈30**,
> not always-on 20-DTE.

- **Entry — systematic, always-on, one position at a time** (entry-spaced), **20-DTE**,
  sold at the daily close. ~~Gating on VRP-z tested no better than always-on~~ (refuted
  over 20yr — see below).
- **Exit — hold to expiry** (model-free settlement at realized price). The defined-risk
  wing *is* the stop — no separate stop needed. (This part holds.)
- **Management:** close winners at ~50% of max credit — **tested and REJECTED** (hurts
  Sharpe, see Refinements §1). The useful "manage the premium" intuition is realized
  instead through the **vrp-z entry gate**, not a profit-take.

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
2. **The edge looked SPX-concentrated under the always-on rule** — bull put spread,
   hold, 2009–2026: SPX 0.92 → QQQ 0.27 → IWM −0.05. **PARTLY OVERTURNED:** under the
   vrp-z-sized rule QQQ jumps to **1.00 OOS** (the gate rescues it); IWM stays weak
   (0.41). So it's an *index-VRP* edge that QQQ shares once you only sell when rich — not
   SPX-only. IWM remains a drag (choppy small-cap RV, RVX a looser proxy).
3. **Naive (always-on) 3-name diversification LOWERED the Sharpe** (0.57 < SPX-alone
   0.92). **SOFTENED under the winner config:** SPX+QQQ rises to **1.59** (QQQ is now a
   real sleeve), SPX+QQQ+IWM 1.20. Breadth helps *once each sleeve is individually
   tradeable* — which the vrp-z gate makes QQQ. IWM still dilutes.

**Net (updated by the experiments below):** the original always-on SPX-only read
(Sharpe ≈0.9) was the conservative floor. With the **vrp-z entry gate + DTE≈30** the
deployable edge is **Sharpe ≈1.6 on SPX, ≈1.0 on QQQ (OOS), SPX+QQQ ≈1.6** — and the
gate, not management or naive breadth, is what got it there.

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

## Experiment results — the vrp-z gate is the dominant lever

Three follow-up sweeps on real SPX+VIX (2006–2026), then a synthesis; all in monthly-ROR
Sharpe units (one-at-a-time always-on Δ0.25/20-DTE = **0.92**, the anchor).

**Delta × DTE.** The sweet DTE is **~30 trading days (≈6 weeks)**, not 20 — higher Sharpe
*and* shallower drawdown (Δ0.25: DTE20 0.92/−4.22 → DTE30 1.07/−2.34); a 30-cal-day VIX
applied to a ~43-cal option is *mildly conservative*. Short-Δ 0.25–0.35 all work (return
rises with delta at ~equal Sharpe). **DTE=7 screens highest (Sharpe ≤1.68) but is a pure
flat-30d-IV artifact — discard it.**

**Weekly ladder + de-risk = the same lever.** Laddering alone barely helps (0.92→0.99 —
the rungs are correlated). What moves the needle is **conditioning size on vrp-z**:

| sizing rule (Δ0.30, DTE30, weekly) | Sharpe | maxDD | Calmar |
|---|--:|--:|--:|
| `always` (no signal) | 1.31 | −2.48 | 0.42 |
| `gate0` — skip if vrp-z<0 | 1.49 | −1.19 | 0.61 |
| `ramp` — full at z≥0, →0 at z=−0.5 | 1.42 | −1.53 | 0.52 |
| **`ramp+` — full at z≥0.5, →0 at z=0** | **1.64** | **−0.94** | **0.67** |

The selective `ramp+` (only sell when vol is *clearly* rich) wins — Sharpe 1.64, drawdown
a third of always-on. Across Δ{0.25,0.30,0.35} the DTE30/ramp+ Sharpe is a flat ~1.64
(delta just trades base-return for raw drawdown), so it's structural, not a lucky cell.

**Sweet spot:** **0.25Δ put / 0.125Δ wing, ~30-trading-day (~6-week) expiry, entered
weekly, sized by vrp-z (`ramp+`), held to expiry.** Sharpe ≈1.65 (top cell), maxDD
≈−0.8 risk-unit, Calmar ≈0.67. Δ0.30/0.35 raise base return at the same ~1.64 Sharpe
(delta is a free return/cushion dial) — 0.25Δ is the highest-Sharpe, widest-cushion cell.

## Does it extend to QQQ / IWM? — yes for QQQ, marginally for IWM

The *identical* winner config, out-of-sample (it was tuned on SPX), over the common 2011+
window:

| underlying | Sharpe (winner) | vs always-on Δ0.25/20 | maxDD | read |
|---|--:|--:|--:|---|
| SPX | 2.03 | 1.29 | −0.59 | strong (in-sample-tuned → discount toward ~1.6 full-history) |
| **QQQ** | **1.00** | 0.29 | −0.75 | **lever RESCUES it — now a real sleeve (OOS)** |
| IWM | 0.41 | 0.19 | −1.28 | still weak (choppy small-cap RV, RVX a looser proxy) |

The lever lifting QQQ from un-tradeable (0.29) to 1.00 **out-of-sample is the key
validation** — the vrp-z edge is a structural property of index VRP, not SPX-overfit.

**Breadth — the earlier "diversification hurts" softens.** Equal-risk-weight under the
winner config (2011+): **SPX+QQQ Sharpe 1.59** (maxDD −0.67), SPX+QQQ+IWM 1.20. SPX-alone
still has the top Sharpe, but QQQ is now a *genuine* second sleeve (was dead weight), so
SPX+QQQ is a defensible way to add **capacity** at little Sharpe cost. IWM still drags.

## Deployable entry/exit signal

**Inputs (daily, EOD):** spot `S`; `IV = VIX/100` (QQQ→VXN, IWM→RVX); `RV20` = annualized
stdev of the last 20 daily log-returns; `vrp = IV − RV20`; `vrp_z` = z-score of `vrp` over
the trailing 252 days.

**ENTRY — every 5th trading day (weekly):**
1. `w = clamp(vrp_z / 0.5, 0, 1)` → vrp_z ≤ 0 ⇒ **skip**; vrp_z ≥ 0.5 ⇒ full; linear between.
2. If `w > 0`, open a **bull put spread** on the ~30-trading-day (~40–45 calendar DTE)
   expiry: **sell the 0.25Δ put, buy the 0.125Δ put** (wing = ½ short Δ). Contracts =
   `w × base`. (0.30Δ/0.35Δ push base return at ~equal Sharpe — delta is a return/cushion
   dial; 0.25Δ is the top-Sharpe cell and the one validated OOS on QQQ/IWM below.)
3. Run it on **SPX (primary) and QQQ (secondary)**; IWM optional. Equal-risk-weight.

**EXIT — hold to expiry.** The long wing *is* the stop (max loss = width − credit, defined
up front). No discretionary stop; **no 50% profit-take** (tested negative).

**Steady state:** weekly entries × ~6-week hold ⇒ up to ~6 rolling rungs per name when vol
is persistently rich; fewer/zero when vrp_z<0 gates you out. Leverage is a separate dial
(scales return and drawdown together; Sharpe unchanged).

## Caveats (synthesis)

- **Selection bias:** the winner config was chosen by sweeping 24 SPX cells, so the SPX
  2.0 is flattered; the QQQ 1.0 OOS and the consistent DTE30/ramp+ *pattern* are the honest
  signal — expect ~1.3–1.6 live on a fresh underlying, not 2.0.
- **Flat-vol model**, still conservative for the put spread (real put skew → real credit ≥
  modeled). 30-cal VIX across horizons → DTE≈20–30 is the clean band; DTE7 is artifact.
- **Real-fill NBBO** remains the only gap between "robust in a conservative model" and
  "traded."

## Verdict

**This is a real, drawdown-robust edge** — the first in the whole VRP investigation —
and the experiments **upgraded it from "narrow SPX, Sharpe ~0.9" to a deployable
index short-vol rule.** The macro short-vol **bull put spread** clears its breakeven
over 20 years *including 2008/2020/2022* and the conservative flat-vol model
*understates* it.

**Deploy this:** bull put spread, **0.25Δ short / 0.125Δ wing, ~30-trading-day expiry,
entered weekly, position sized by vrp-z** (`w = clamp(vrp_z/0.5, 0, 1)` — skip when vol
isn't rich, full size when clearly rich), **held to expiry** (the wing is the stop). Δ is
a free return/cushion dial — 0.30Δ/0.35Δ raise base return at ~equal Sharpe (~1.64).
- The **vrp-z gate is the dominant lever** — it lifts SPX to Sharpe ≈1.6 and **rescues
  QQQ from 0.27 to 1.00 out-of-sample**, proving the edge is structural index-VRP, not
  SPX-overfit.
- **SPX is primary, QQQ a genuine second sleeve** (SPX+QQQ ≈1.6); IWM still drags.
- **Rejected:** 50% profit-take (hurts), DTE=7 (flat-vol artifact), CSP (ROR≈0),
  always-on (the gate beats it on every cell).
- Iron condor remains the all-weather candidate pending real-fill confirmation of its
  call side.

**Next:** promote the vrp-z sizing + DTE≈30 winner into the engine as the default; build
the real-fill **NBBO recorder** (the only remaining gap to live trading).
