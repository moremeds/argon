# GARCH as argon's VRP realized-vol leg — VERDICT: do not ship

**Date:** 2026-07-29
**Scripts:** `scripts/research/garch_vs_rv21_forecast.py` (Stage A),
`scripts/research/garch_vrp_signal_ic.py` (Stage B)
**Artifacts:** `docs/research/garch-vrp-2026-07-29/{stage_a,stage_b}.summary.json`

## Verdict

**Do not replace argon's RV leg with a GARCH forecast.** GARCH forecasts forward
realized vol better on QLIKE/RMSE, but it carries a **+2.46 vol-point structural
level bias** whose sign tracks the vol regime (corr with annual realized vol
= **−0.85**). Since `vrp = iv − rv`, that bias lands directly on the traded
quantity and **inverts the VRP timing**: GARCH understates VRP in calm markets
(when the premium is real) and overstates it in crises (when selling is
dangerous).

Concretely, over the IV window the true realized premium on SPX was **+3.14 vol
points**. argon's current `rv21` measured **+2.87** (nearly right). GARCH would
have measured **+0.14** — i.e. "no premium, do not sell" during a period that
paid 3.1 points. That change would have shut off the SPX bull put spread, the
structure that currently works.

**If anything ships, ship EWMA, not GARCH** — see "The one shippable finding".

## Origin

Follow-up to the radon `garch_convergence.py` review. The original argument was
that argon's `vrp = iv − rv` is horizon-mismatched: `rv` is a *trailing 21d*
realized vol (`reports/volatility_series.py::_fill_rv_from_price`, window=21)
while `iv` looks ~30d *forward*. GARCH was proposed as the minimal fix because
its h-step forecast decays a shock toward the unconditional level at
`(alpha+beta)^h`.

**That argument was right in mechanism and wrong in magnitude — see "Where the
original reasoning was wrong".**

## Design

Two stages, deliberately ordered so the cheap decisive test runs first.

**Stage A — forecast horse race.** Uses NO implied vol, so it is not limited to
argon's thin 304-day IV panel: 96 tickers x 2012-2026, **n = 277,767**, walk-forward.

| estimator | definition |
|---|---|
| `rv21` | trailing 21d stdev of log returns x sqrt(252) — **argon today** |
| `ewma` | RiskMetrics lambda=0.94, flat forecast — recency weighting, NO mean reversion |
| `garch` | GARCH(1,1)-t, refit every 63 bars on an expanding window (cap 2500), conditional variance filtered forward daily, integrated 21 steps ahead |

`ewma` is the control that isolates *which* part of GARCH matters. Target is
`rv_fwd21(t) = stdev(r[t+1..t+21]) x sqrt(252)`.

Prices: `adj_close` from the market-warehouse bronze lake (splits handled).
Significance by **block bootstrap over non-overlapping 21-day date blocks** — the
forward windows overlap 21d, so a pooled t-test would overstate by ~sqrt(21).

**Stage B — signal IC.** Joins argon's real IV. Reported for completeness only;
see "Stage B has no power".

## Stage A results

n = 277,767 · 96 tickers · 2012-01-03 to 2026-04-16 · 172 blocks

| estimator | QLIKE | RMSE | Spearman | **bias (vol pts)** | **MAE** |
|---|---|---|---|---|---|
| `rv21` | −1.1885 | 0.1916 | 0.7343 | **−0.12** | 11.25 |
| `ewma` | −1.2898 | 0.1768 | 0.7638 | **+0.53** | **10.42** |
| `garch` | **−1.3295** | 0.1771 | **0.7725** | **+2.46** | 10.64 |

Paired block-bootstrap deltas (negative = first is better):

| comparison | ALL | ETF (11) | single-name (85) |
|---|---|---|---|
| garch vs rv21 | −0.144 **p=0.000** | −0.139 **p=0.000** | −0.145 **p=0.000** |
| garch vs ewma | −0.042 **p=0.008** | −0.065 **p=0.000** | −0.038 **p=0.013** |
| ewma vs rv21 | −0.102 **p=0.000** | −0.075 p=0.002 | −0.106 **p=0.000** |

GARCH beats `rv21` on QLIKE for **91/96 tickers**. On QLIKE alone the ordering is
unambiguous: **garch > ewma > rv21**, everywhere, significant.

### But QLIKE is the wrong loss for this decision

`QLIKE = log(s2) + a2/s2` is **asymmetric**: under-forecasting makes `a2/s2`
diverge, over-forecasting costs only linearly. A systematically *high* forecaster
is structurally "safe" under QLIKE. Switch to MAE and the ordering changes:
**ewma (10.42) < garch (10.64) < rv21 (11.25)**.

For a VRP signal the primary criterion is neither: it is **bias**, because
`vrp = iv − rv` is a level and the trade is sized off that level.

### The disqualifying result: regime-dependent level bias

Bias by year (forecast − realized forward RV, vol points):

| year | garch | ewma | rv21 | realized |
|---|---|---|---|---|
| 2012 | **+5.33** | +1.00 | +0.24 | 22.92 |
| 2013 | **+5.05** | +0.66 | +0.21 | 21.08 |
| 2014 | +4.00 | +0.04 | −0.32 | 21.51 |
| 2015 | +2.52 | −0.25 | −0.45 | 24.84 |
| 2016 | +4.14 | +1.46 | +0.91 | 24.09 |
| 2017 | +4.06 | +0.55 | −0.06 | 22.02 |
| 2018 | +0.41 | −0.94 | −1.38 | 31.69 |
| 2019 | +4.82 | +2.44 | +1.50 | 26.11 |
| 2020 | **−3.50** | +0.35 | −1.10 | 45.78 |
| 2021 | +3.58 | +0.65 | +0.10 | 31.27 |
| 2022 | −0.89 | +0.09 | −0.30 | 42.05 |
| 2023 | +3.73 | +1.22 | +0.34 | 33.32 |
| 2024 | +2.53 | +0.04 | −0.42 | 38.61 |
| 2025 | +2.06 | +1.23 | +0.18 | 43.77 |
| 2026 | −2.72 | −3.45 | −3.39 | 49.70 |

| estimator | corr(bias, realized regime) | bias spread |
|---|---|---|
| `rv21` | −0.597 | 4.89 pts |
| `ewma` | −0.469 | 5.89 pts |
| **`garch`** | **−0.847** | **8.83 pts** |

All three share the sign — high-vol years bias every forecaster low. **GARCH's
magnitude is roughly double.** Mechanism: mean reversion pulls toward an
unconditional `sigma_bar` estimated over a sample containing 2020 and 2022, so
calm-regime forecasts get dragged up.

Trading consequence, per estimator, on the IV window (2025-05-12..2026-04-16):

| | true VRP (iv − actual fwd RV) | `vrp_rv21` | `vrp_garch` |
|---|---|---|---|
| SPX (IV) x SPY (px) | **+3.14** | +2.87 | **+0.14** |
| SPY | +3.36 | +3.04 | +0.29 |
| QQQ | +4.04 | +3.84 | +0.91 |

## Stage B has no power — no conclusion drawn

argon's IV panel starts 2025-05-12 and the price lake ends 2026-05-15, so the
usable window is ~235 dates = **11 independent 21-day blocks**.

n = 21,606 · 96 tickers · z-window 20 (argon's `vrp_z_20` convention)

| signal | cross-sectional IC | 95% CI | Q5−Q1 |
|---|---|---|---|
| `z_rv21` | +0.0514 | [−0.0136, +0.0850] | +1.08 pts |
| `z_garch` | +0.0614 | [−0.0351, +0.0926] | +0.99 pts |
| `z_ewma` | +0.0535 | [−0.0210, +0.0859] | +0.85 pts |

Paired delta garch − rv21: **+0.0100, CI [−0.0428, +0.0388]**. Every interval
straddles zero. **This stage cannot distinguish the estimators and is not
evidence for either side.**

Note also that both signals contain the same `iv` term as the target
(`y = iv − rv_fwd`), which inflates the *absolute* IC of all three identically.
Only the *delta* is interpretable, and the delta is indistinguishable from zero.

## The one shippable finding: EWMA, not GARCH

`ewma` beats argon's current `rv21` on every accuracy metric, with p=0.000 on
QLIKE, at a cost of +0.53 pts of bias:

| | rv21 | ewma | change |
|---|---|---|---|
| MAE | 11.25 | **10.42** | **−7.4%** |
| RMSE | 0.1916 | **0.1768** | **−7.7%** |
| Spearman | 0.7343 | **0.7638** | +0.030 |
| bias | −0.12 | +0.53 | +0.65 pts worse |
| regime-bias corr | −0.597 | **−0.469** | better |

It needs **no fitting, no `arch` dependency, no refit schedule** — a ~5-line
recursion. Whether the +0.65 pts of bias is acceptable depends on the consumer:

* **`vrp_z_20` (sizing)** — a trailing z-score cancels a near-constant bias.
  EWMA is the better input here.
* **any raw-level VRP gate** — the bias lands directly on the threshold. Keep
  `rv21`, or recalibrate the threshold by +0.53.

**Not shipped. This is a recommendation pending a decision.**

## Where the original reasoning was wrong

The premise was that "backward 21d RV vs forward 30d IV" is a fatal horizon
mismatch. Measured over 14 years, **`rv21`'s bias against forward 21d RV is
−0.12 vol points** — very nearly unbiased. Volatility is persistent enough that
a random walk is a good forecast of a near-unit-root process. The mechanism was
real; the magnitude was overstated. `rv21` is a much better estimator than the
theory suggested.

## Errors made during this run — recorded so they are not repeated

1. **A single broken ticker inverted the single-name verdict.** NBIS (ex-Yandex,
   halted 2022-24) contributed 2,995 rows (1.1%). With it, single-name
   `garch vs rv21` read −0.062 p=0.107 and `garch vs ewma` read **+0.045 (GARCH
   losing)**. Without it: −0.145 p=0.000 and −0.038 p=0.013. **The median QLIKE
   said GARCH was winning the entire time** — the robust statistic was correct
   and the contaminated mean was read instead.

2. **An elegant wrong story was constructed to fit the contaminated data.** The
   claim was that GARCH has no event term, so scheduled earnings jumps cause
   fat-tailed failures on single names but not on indices — which "explained" the
   ETF/single-name gap perfectly. After the fix the gap is gone (ETF −0.139 vs
   single-name −0.145). **The explanation was post-hoc accommodation, not
   prediction.**

3. **The first filter targeted the wrong object.** A `stale_frac` (zero-return
   fraction) input filter did not catch NBIS: on 2024-11-25 its `stale_frac` was
   0.048 while `garch` forecast **0.0057% vol into a 135% realized move**
   (QLIKE 5.6e8). The halt sat in the *fit window*, poisoning omega, so the
   contamination lived in the fitted **params**, not in the bar. Only an
   **output-side floor** (`MIN_VOL = 3% annualized`) catches it. 137 bars
   panel-wide decided p=0.10 vs p=0.00.

4. **A calm/stressed bias split was discarded as a mechanical artifact.**
   Splitting bars on the target's own median produced symmetric ±5-point biases
   for all three estimators — that is regression to the mean from selecting on
   the outcome, not a finding. The year-level split is used instead.

## Production note if GARCH is ever revisited

GARCH fits fail catastrophically after trading halts (omega -> 0, conditional
variance collapses). Any live use needs an **output floor plus a fallback to
EWMA on rejection**, not silent trust in the fitted model.

## Untested directions

* **Walk-forward debiased GARCH** (subtract an expanding mean of past forecast
  errors, lagged 21d so only closed windows are used) scored the best MAE
  (**9.73**) and RMSE (**16.88**) of anything tried, but over-corrected bias to
  −1.22 because the bias itself shrinks over time and an expanding mean carries
  stale large errors forward. The correction window is a free parameter and only
  one configuration was tried — **stopped here deliberately to avoid overfitting
  a research artifact.**
* Shorter-sample `sigma_bar` (regime-local unconditional mean) as a
  bias fix — untested.
* Stage B is unresolvable until the IV panel has ~3 more years.

## Reproduce

```bash
uv run python scripts/research/garch_vs_rv21_forecast.py --start 2012-01-01 \
    --out-prefix /tmp/stage_a
uv run python scripts/research/garch_vs_rv21_forecast.py \
    --rescore /tmp/stage_a.per_obs.parquet --out-prefix /tmp/stage_a   # no refits
uv run python scripts/research/garch_vrp_signal_ic.py \
    --stage-a /tmp/stage_a.per_obs.parquet --alias SPX=SPY --out-prefix /tmp/stage_b
```

Stage A takes ~15 min (96 tickers x ~60 GARCH refits each). `--rescore` is instant.

## Data constraints found (reusable)

| source | span | note |
|---|---|---|
| market-warehouse bronze lake | 653 equities, SPY from 1993 | **ends 2026-05-15** (stale ~2.5mo) |
| `uw_scan.realized_volatility_history` | 131 tickers, 2025-05-12+ | **max 304 bars/ticker**, 0 tickers >= 500 |
| overlap used | **103 tickers** | 22 IV tickers absent from lake (SPX, XL*, SOXX, SLV, ...) |

Identical on the mini (`option_wizard`) and locally — the IV panel depth is a
hard ceiling, not a local-mirror artifact. SPX has IV but no lake price series;
`--alias SPX=SPY` pairs SPX implied vol with SPY realized vol (same index;
dividend-vs-total-return differences are noise at daily frequency).
