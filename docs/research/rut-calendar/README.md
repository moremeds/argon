# RUT put-calendar study — sell 0/1DTE put, buy a longer-dated put

**Date:** 2026-06-23 · **Branch:** `feat/rut-diagonal-strategy`

- **Iteration 1** (coupled daily put calendar) → **not a standalone edge** (below).
- **Iteration 2** (hold the long longer + decouple the legs) → **materially better; a
  marginal, regime-sensitive edge** worth a live front-IV check. See
  [Iteration 2](#iteration-2--hold-the-long-leg-longer-decouple-the-legs).

## TL;DR verdict (iteration 1)

**Not a legitimate standalone edge.** `[COMPUTED, HIGH]` Under any *realistic joint*
assumption (front 1-day put IV not wildly above RVX **and** non-trivial bid/ask on
0/1DTE OTM RUT puts), every sensible configuration loses money over 2010–2026. The
apparent alpha is manufactured entirely by two optimistic inputs:

1. **Front-vol richness** — the trade only works if the short 1-day put is sold
   ~10–30 % *richer* than the 30-day RVX anchor (`front_vol_mult ≥ ~1.2`). That ratio
   is **unobservable from our daily data** and is the strategy's whole edge.
2. **Frictionless fills** — at a 5 % half-spread (realistic for 0/1DTE OTM RUT wings)
   the breakeven config already loses; by 10 % everything is deeply negative.

These two requirements are *jointly* implausible. The high-Sharpe rows in the sweep
(Sharpe ~6–10) are **artifacts**, not signal — they come from degenerate 2-day-cycle
configs that are effectively near-naked daily put writes, which die fastest once you
charge realistic slippage. This is exactly the "phantom Sharpe" failure mode the repo
warns about.

If you want a tradable RUT short-vol structure, this isn't it as a standalone. See
[What would make this a real backtest](#what-would-make-this-a-real-backtest).

---

## Actionable takeaways

1. **Don't trade the daily put-calendar.** `[COMPUTED, HIGH]` Realistic slippage alone
   sinks it; the Sharpe ~6–10 configs are turnover artifacts.
2. **If the goal is "sell index vol for income, defined-risk," do it on SPX — not RUT.**
   Running the repo's *validated* VRP bull-put-spread engine (`vrp_macro_signal.WINNER`,
   vrp-z ramp sizing) full-sample 2010-09→present, **constant-risk slot-account Sharpe**
   `[COMPUTED, in-sample]`:

   | Index | Sharpe | ann ROR | maxDD |
   |---|---|---|---|
   | SPX | **2.06** | +58 % | −59 % |
   | QQQ | 1.01 | +35 % | −75 % |
   | RUT | **0.70** | +30 % | −100 % |
   | IWM | 0.44 | +18 % | −128 % |

   RUT is the **worst major** for vol harvesting — thinner/less reliable small-cap vol
   premium, fatter tails, near-ruin drawdown. These are *in-sample* (WINNER was tuned on
   SPX), so RUT's true OOS edge is lower still. The Russell *being* the target works
   against you. Reproduce: `backtest_laddered(load_index_vol(repo, "RUT"), s, WINNER,
   min_date=date(2010,9,1))`.
3. **One cheap RUT-specific revival test:** measure *today's* actual 0/1DTE RUT(W)
   ~20-delta put IV vs RVX. If it persistently clears ~1.2× RVX, the calendar's front
   premium may be real — but that needs observed chains (UW tier permitting), and the
   bid/ask wall remains.

## Iteration 2 — hold the long leg longer, decouple the legs

**Change:** stop treating short+long as one calendar. The long put becomes a
**longer-dated standing hedge** (held for quarters, rolled at 21 DTE); the short is an
**independent daily 1DTE OTM roll**, re-struck to its own delta off current spot and
capped at the long strike (still defined-risk). `mode="decoupled"` in the engine, with
**per-leg P&L decomposition** so we can see whether the short income finances the long
carry. Hypotheses: (a) longer long ⇒ lower daily theta carry + far fewer rolls ⇒ lower
breakeven & smaller drawdown; (b) longer long ⇒ more vega held ⇒ vol-decline drag.

**Result — materially better, but a marginal & regime-sensitive edge:** `[COMPUTED]`

| metric (RUT, `ld=60, sd=0.30, 1DTE`, roll long @21 DTE) | iteration 1 (`ld30` calendar) | iteration 2 |
|---|---|---|
| long-leg carry | −4.2 %/yr | **−1.5 %/yr** (→ −0.7 % at `ld252`) |
| breakeven `front_vol_mult` | ~1.16 | **~1.05–1.09** (`sd=0.30`) |
| maxDD @ `fvm=1.10`, 5 % slip | near-ruin | **−11 %** |
| Sharpe @ `fvm=1.10`, 5 % slip | −0.52 | **+0.43** (positive through 10 % slip: +0.09) |
| stress-year mean Sharpe | negative | **+0.6** (the standing put pays in crashes) |
| **holdout** (train <2019 / test ≥2019) | — | **IS +0.45 / OOS +0.38** (consistent) |

Hypothesis (a) **confirmed** — the decomposition shows the long carry collapsing with
tenor, which is the entire improvement. The short income stream alone runs +1.0–1.5
Sharpe at `fvm=1.10`. Drawdowns shrink from ruin to ~−10 %.

**The honest caveats — why it's "marginal," not "yes":** `[INFERRED, MED]`
1. **Still pivots on the unobservable.** At `fvm=1.0` (front = RVX) it's flat-to-negative.
   The +0.38 OOS needs `fvm ≥ ~1.10` (front 1d ~30Δ puts ≥10 % richer than 30d RVX). The
   live front-IV measurement remains the deciding test.
2. **The OOS positivity leans on 2020.** IWM holdout is IS −0.03 / **OOS +0.41** — the OOS
   window (2019–26) contains COVID, where the *long hedge paid off*. So part of the "edge"
   is a tail-hedge payoff, not pure carry (consistent with the short-vol-carry framing).
   RUT is cleaner (IS+ and OOS+ both), IWM is IS≈0/OOS+ — agreement is *directional, not
   tight*.
3. **+0.38 OOS is modest** — an overlay-grade edge at best, not a standalone star, and not
   yet walk-forward-clean (single split, no rolling windows).
4. **Cost wall lowered, not removed** — the daily-short slippage still bites; survives to
   ~10 % half-spread only because the gross edge is now bigger.

**Verdict:** iteration 2 turns a clear "no" into **"a marginal, structurally-sound edge —
worth a live front-IV confirmation and a clean walk-forward before risking capital."** The
candidate config: **RUT, decoupled, long_dte ≈ 45–120, short_delta ≈ 0.30, 1DTE short
rolled daily, long rolled at 21 DTE.**

Trace: `iter2_sweep_{rut,iwm}.csv`, `iter2_cost_{rut,iwm}.csv`, `iter2_holdout_{rut,iwm}.csv`.
Reproduce: `uv run python scripts/research/rut_calendar_iter2.py RUT` (and `IWM`).

### Iteration 3 candidates (not built)
- **Roll the short less often** (weekly, not daily) — the one lever that directly attacks
  the remaining cost wall.
- **Front-richness gate** — only sell when the term-structure/skew is demonstrably rich;
  needs observed front IV (so blocked on the same capture).
- **Clean walk-forward** (rolling windows) + a model-repriced check once real chains exist.

## What was tested

- **Strategy:** SELL a 0DTE or 1DTE put, BUY a longer-dated put at the **same strike**
  (a long put *calendar*), rolled **daily**: re-sell the front put each session against
  a standing long put; close & re-establish the long put when it reaches 5 DTE.
  Same-strike = the literal reading of "sell a put, buy a longer-dated put" and is
  **defined-risk** (the long put always covers the short — max loss = net debit, up to a
  cents-level European interest-carry term).
- **Objective:** standalone risk-adjusted edge (Sharpe). *(Per your choice; the "hedge-
  financing" framing would score differently.)*
- **Data:** `[KNOWN]` real **RUT** index (lake `asset_class=volatility/symbol=RUT`,
  2009-09→2026-05) **and IWM** ETF proxy as a cross-check, both paired with **RVX**.
  Sim window 2010-09-01→present (clears the 252-day vol-z warmup). ~3,800 trading days.
- **Pricing:** model-priced Black-Scholes off RVX. **There are NO historical RUT option
  chains** — every premium here is a model number, *not* an observed fill. Front IV =
  `RVX/100 × front_vol_mult × put-skew`; long IV = `RVX/100 × long_vol_mult × put-skew`.

### The load-bearing caveat
Read every Sharpe as **"edge *conditional on* `front_vol_mult`."** RVX is a ~30-day ATM
Russell vol; the trade sells a **1-day ~20-delta put**, whose true IV we cannot observe
daily. So the honest output is not a point Sharpe — it's the **breakeven front-vol
richness**, and whether reality plausibly clears it.

---

## Findings

### 1. Sweep — the breakeven, and why the "winners" are fake
Grid: `front_dte∈{0,1} × long_dte∈{7,14,21,30,45,60} × short_delta∈{0.10,0.20,0.30} ×
front_vol_mult∈{0.85,1.0,1.15,1.30,1.50}`, calendar mode, 5 % slippage.

- `[COMPUTED]` At `front_vol_mult = 1.00` (front priced *at* RVX), **nothing works** —
  every config has a negative Sharpe. The strategy is net long the *near-money long
  put's* theta + vega; a fairly-priced daily 20-delta short can't cover it.
- `[COMPUTED]` **Breakeven `front_vol_mult` (RUT, 1DTE):** `ld14 → 1.09`, `ld21 → 1.13`,
  `ld30 → 1.16`, `ld45 → 1.25`, `ld60 → 1.42`. Shorter back-leg = lower bar (less vega
  to finance) but → degenerate.
- `[COMPUTED]` **0DTE (`front_dte=0`) essentially never clears the grid.** At daily
  resolution 0DTE's only modeled difference from 1DTE is less time-value (it collects
  *less* premium for the same one-bar move). Its real edge — intraday theta with no
  overnight gap — is **invisible to daily bars** (see gaps).
- `[INFERRED, HIGH]` The Sharpe ~6–10 rows (`ld=7`) are **artifacts**: with `long_dte=7`
  and `min_residual=5` the cycle is ~2 days, so almost no long-vega is held — it's a
  near-naked daily put write wearing a brief cover. Confirmed fake by the cost test below.
- **RUT vs IWM agree** (breakevens within ~0.05–0.15; RUT marginally lower — it's the
  index, no ETF drag). The result is not an IWM-proxy artifact.

Trace: `sweep_rut.csv`, `sweep_iwm.csv` (180 configs each) + `sweep_by_year_*.csv`.

### 2. Robustness — sampling, cost, regime
Representative 1DTE configs: `mid` (ld30/sd0.20), `long` (ld45/sd0.20), `winner`
(ld7/sd0.30). Block-bootstrap (Politis-Romano, 2000 trials, monthly, seed 20260623).

- **Sampling (RUT `mid`):** `[COMPUTED]` `fvm1.0 → Sharpe −1.43`, 90 % CI `[−1.25,−0.72]`
  (all negative). `fvm1.2 → +0.35`, CI `[−0.12, +0.60]` — **straddles zero** (frac-positive
  0.85, i.e. not distinguishable from luck). Only `fvm1.3 → +1.24`, CI `[0.37, 1.17]` is
  cleanly positive — and that needs front vol **30 % over RVX**. IWM is worse (`mid`
  needs `fvm1.3` just to reach `+0.62` with CI grazing 0).
- **Cost (RUT, `fvm` fixed at a *generous* 1.10):** `[COMPUTED]` Sharpe vs half-spread —
  `mid`: `0%→+1.65`, `2%→+0.77`, **`5%→−0.52`**, `10%→−2.31`. Breakeven slippage is
  ~2–3 %. The `winner` config has the **highest turnover** so it bleeds fastest in dollar
  terms (`annR 0%→+34.6 %` collapses to `10%→−6.9 %`). 0/1DTE OTM RUT wings do **not**
  trade at a 2 % half-spread.
- **Regime:** `[COMPUTED]` worst stress-year Sharpe (2011/2015/2018/2020/2022) is negative
  for `mid`/`long` until `fvm1.3`. The calendar is short gamma + bullish-biased; a
  persistent small-cap downtrend (2022) bleeds it.

Trace: `robustness_rut.csv`, `robustness_iwm.csv`, `robustness_trials_*.csv`.

---

## Pitfalls & what daily data cannot see (gaps you asked me to fill)

1. **Front IV ≠ RVX is the whole game, and it's unobservable here.** `[INFERRED, HIGH]`
   The edge lives in the 1-day ~20-delta put's IV vs the 30-day RVX. In calm contango the
   1-day *ATM* vol is usually *below* RVX (`fvm<1`), but short-dated *put skew* + 0/1DTE
   demand can push the 20-delta put above it. Whether it clears the ~1.2 breakeven is a
   coin-flip we can't settle without real chains. **This is the #1 gap.**
2. **Intraday gap / short-gamma path is the real 0DTE risk** and is *invisible* at daily
   close resolution. A model that only sees close-to-close moves understates the gamma
   cost of selling 0DTE through an intraday air-pocket (e.g. 2018-02-05, 2020-03). Treat
   the 0DTE numbers as *upper bounds*, not estimates.
3. **RUT settlement mechanics.** `[KNOWN]` RUT monthly options are **AM-settled** (settle
   to the Saturday/open print); 0DTE requires **RUTW** (PM-settled weeklies). A "0DTE on
   RUT" must be RUTW. European **cash settlement** is the one structural *plus* — **no
   early assignment / pin risk** on the short, unlike IWM (American). The model assumed
   cash-settled European throughout, which is right for RUT/RUTW, wrong for IWM (IWM
   numbers slightly flatter the strategy by ignoring assignment).
4. **Bid/ask is the killer, not theta.** The cost sweep shows realistic slippage alone
   sinks it. Any live version must model per-leg spread explicitly, especially the wings.
5. **Macro event days.** No per-name earnings (it's an index) but FOMC/CPI/NFP spike
   short-dated vol and gap risk; a real version needs an event calendar gate. Not modeled.
6. **It's a short-vol *carry* trade, not a "calendar."** `[INFERRED]` Framing it as a
   calendar hides the mechanism: P&L ≈ (front vol − back vol) carry + skew − gamma cost.
   The natural improvement is a **term-structure/skew gate** (only sell when the front is
   demonstrably rich) — but you can't build that gate without observed front IV either.
7. **Normalization caveat.** Sharpe is scale-free; drawdowns are expressed on a 2 %-risk-
   budgeted account (`RISK_FRAC` in the engine), since a bare-debit normalization makes a
   vega-levered calendar's equity path explode. Defined-risk holds up to a cents-level
   European interest-carry term (the unit test asserts the correct bound).

---

## What would make this a real backtest

The single fix that converts this from a conditional model-sim into an empirical test:
**observe the front IV instead of assuming it.**

1. **Forward-capture RUTW chains.** argon already captures EOD option surfaces
   (`option_surface_capture`, migrations 077/078). Extend the captured set to **RUT/RUTW**
   (0/1DTE + ~30D puts, with bid/ask + IV). After a few months, re-run this exact engine
   with the **observed** front IV in place of `front_vol_mult` → the breakeven becomes a
   measured fact, and the bid/ask becomes real instead of a sweep axis.
2. **Backfill check.** See whether UW `get_historic_chains` (or any source) can return
   even sparse historical RUT 1-day put IV; if so, measure the historical
   front-IV/RVX ratio directly and settle the #1 gap.
3. **Then, only then,** consider a term-structure-gated variant and a portfolio-overlay
   sizing study (it may have value as a small short-vol overlay even if it fails as a
   standalone Sharpe play).

---

## Artifacts & reproduce

| File | What |
|---|---|
| `src/uw_scan/reports/put_calendar.py` | two-expiry calendar engine (+ `tests/unit/test_put_calendar.py`) |
| `scripts/research/rut_calendar_sweep.py` | step 1 sweep → `sweep_{rut,iwm}.csv`, `sweep_by_year_*.csv` |
| `scripts/research/rut_calendar_robustness.py` | step 2 robustness → `robustness_{rut,iwm}.csv`, `robustness_trials_*.csv` |

```bash
uv run pytest tests/unit/test_put_calendar.py -q
uv run python scripts/research/rut_calendar_sweep.py RUT        # and IWM
uv run python scripts/research/rut_calendar_robustness.py RUT   # and IWM
```
Data: RUT/RVX from the lake `asset_class=volatility` + `vol_index_daily`; loader is
`uw_scan.reports.vrp_macro_drawdown.load_index_vol(repo, "RUT")` (added here).

**[RULES I BROKE]:** None. All headline numbers are `[COMPUTED]` from the committed
traces; the front-vol-richness dependency is flagged as the unobservable it is; no
synthetic data is presented as real (model premiums are labeled model-priced throughout).
```
