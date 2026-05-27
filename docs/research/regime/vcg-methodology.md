# VCG — Volatility-Credit Gap Methodology

**Indicator**: VCG (Volatility-Credit Gap)
**Composite version**: 2 (`src/uw_scan/cards/vcg_scoring.py:COMPOSITE_VERSION = 2`)
**Last backtest**: 2026-05-25 v1 on 18.5-year HYG-bound history (4,708 days post-burn-in); v2 backfill pending in this branch.
**Status**: V2 = v1 math with cascade reorder plus absolute-vol-stress override. Core thresholds remain xenon-inherited unless noted in §3.

---

## 1. What VCG is

VCG is a residual-based regime indicator that orthogonalises credit-spread changes against expected volatility (VVIX) and current volatility (VIX). It answers: **does credit move differently than its vol-driven priors say it should?**

The output is a z-scored regression residual. Positive z = credit weakened MORE than vol explained (stress signal). Negative z = credit strengthened MORE than vol explained (capitulation / relief).

VCG is **descriptive**, not predictive: it does not forecast crashes the way CRI tries to. It surfaces moments where credit's behavior is anomalous given the vol environment — those moments are useful regime markers but require interpretation rather than mechanical signal-following.

VCG is also **regime-state**, not point-in-time: a single day's z is noisy. The label (`NORMAL`, `WATCH`, `EDR`, `RISK_OFF`, `BOUNCE`, `PANIC`, `SUPPRESSED`) is what matters; the underlying continuous score is sidecar context.

## 2. Mathematical specification

### 2.1 Rolling regression

Over a sliding 21-business-day window, fit:

```
Δlog(credit_t) = α + β₁·Δlog(VVIX_t) + β₂·Δlog(VIX_t) + ε_t
```

where:

- `credit_t` = adjusted-close price of the credit-ETF proxy at day t (HYG default; JNK / LQD optional)
- `VIX_t` = CBOE VIX close
- `VVIX_t` = CBOE VVIX close
- `Δlog` = first difference of natural log (continuous return)

The regression uses OLS via `numpy.linalg.lstsq`. Rank-deficient or non-finite windows are skipped (residual stays NaN).

### 2.2 Residual standardisation

Each day's residual is standardised across a 63-trading-day trailing window:

```
vcg_t = (ε_t − μ_63d(ε)) / σ_63d(ε)
```

Windows with fewer than 10 valid residuals or `σ < 1e-12` produce NaN.

### 2.3 Panic-π adjustment

When VIX is already elevated, the residual signal is suppressed:

```
π_t = clamp((VIX_t − 40) / (48 − 40), 0, 1)
vcg_adj_t = (1 − π_t) · vcg_t
```

So `vcg_adj` decays linearly to zero between VIX = 40 and VIX = 48. The motivation: at very high VIX, every part of the cross-section is panicking, and the residual signal — built to detect divergence from vol — is no longer meaningful as a separate signal. This adjustment is xenon-inherited and **not academically grounded**; see §5.3.

### 2.4 Sign discipline gate

A pair of economic priors gate the actionable signal:

- `β₁` (loading on Δlog VVIX) should be ≤ 0 — credit tends to weaken when expected vol rises
- `β₂` (loading on Δlog VIX) should be ≤ 0 — credit tends to weaken when current vol rises

If either coefficient flips positive, `sign_ok = False` and the day's interpretation is `SUPPRESSED`. This prevents a regression that has lost economic plausibility from driving regime labels.

### 2.5 Interpretation label

```
if vcg is NaN:                                      INSUFFICIENT_DATA
elif pi >= 1.0 (VIX >= 48):                         PANIC
elif vix_percentile_rank >= 0.95
  and vvix_percentile_rank >= 0.95:                 RISK_OFF
elif not sign_ok:                                   SUPPRESSED
elif vcg_adj > 2.5 and VIX > 28:                    RISK_OFF
elif vcg_adj > 2.0 and VIX > 25:                    EDR
elif vcg_adj < -3.5:                                BOUNCE
elif vcg_adj > 2.0:                                 WATCH
else:                                               NORMAL
```

V2 moved the PANIC branch above sign discipline so `regime=PANIC` cannot be paired with `interpretation=SUPPRESSED`. The new absolute-vol-stress branch also sits above sign discipline because it is level-based, not regression-sign based. The rest of the flag-based cascade remains v1-compatible: sign failure can still suppress RISK_OFF / EDR / WATCH labels driven only by `vcg_adj`.

### 2.6 Absolute-vol-stress override

`vol_extreme` is true when both VIX and VVIX are at or above the 95th percentile of their own 252-trading-day rolling histories. Percentile ranks use the Level-1 truth labeler's `strict_lt` tie rule and are `None` during the warmup.

When `vol_extreme` is true and `pi < 1.0`, v2 emits `RISK_OFF`. This aligns with the truth-labeler structure: simultaneous VIX/VVIX extremity is a tighter subset of truth-RISK_OFF, while PANIC remains reserved for the existing VIX panic-adjustment branch. If both branches are true, PANIC wins by cascade order.

## 3. Calibration constants and `COMPOSITE_VERSION`

| Constant | Value | Rationale | Empirical band (18y backtest) |
|---|---|---|---|
| `OLS_WINDOW` | 21 | Roughly 1 trading month; xenon-inherited. Short enough to track regime shifts, long enough to fit 3 betas without overfitting | 21 days × 4,708 = ~99k windows fit |
| `Z_WINDOW` | 63 | Roughly 3 trading months; xenon-inherited. Standardisation lookback for residual z | 63-day half-life means recent regimes dominate the z |
| `MIN_BARS` | 94 | OLS_WINDOW + Z_WINDOW + 10 (warmup) | First emitted index = day 94 |
| `VIX_PANIC_LOW` | 40 | π = 0 floor; xenon-inherited | π > 0 on 95 days of 4,708 (2.0%) |
| `VIX_PANIC_HIGH` | 48 | π = 1 ceiling; xenon-inherited | π = 1 on 37 days (0.8%) — see PANIC count |
| `VIX_FLOOR` | 28 | RO gate: VIX must exceed for RISK_OFF | 5 RO firings of 4,708 |
| `VIX_EDR` | 25 | EDR watch gate: VIX must exceed for EDR | 14 EDR firings (combined with RISK_OFF, EDR proper = 9) |
| `VCG_TRIGGER` | 2.0 | EDR / Watch threshold (vcg_adj > 2.0) | 38 WATCH + 9 EDR firings |
| `VCG_RO_TRIGGER` | 2.5 | RISK_OFF threshold (vcg_adj > 2.5 AND VIX > 28) | 5 RO firings |
| `BOUNCE_TRIGGER` | -3.5 | Counter-signal: vcg_adj < -3.5 with sign_ok | 5 BOUNCE firings |
| `VVIX_ELEVATED` | 100 | Severity tag (informational) | n/a — not a gate |
| `VVIX_EXTREME` | 120 | Severity tag (informational) | n/a — not a gate |

### v2 - Absolute-vol-stress override (2026-05-27)

| Constant | Value | Source |
|---|---|---|
| `VIX_PCT_PANIC` | 0.95 | `level1-thresholds.yaml` `P_PANIC` |
| `VVIX_PCT_PANIC` | 0.95 | `level1-thresholds.yaml` `P_PANIC` |
| `VOL_PERCENTILE_WINDOW` | 252 | `level1-thresholds.yaml` `rolling_window_days` |
| `VOL_PERCENTILE_TIE_RULE` | `"strict_lt"` | `level1-thresholds.yaml` `percentile_tie_rule` |

These values deliberately align with the Level-1 truth labeler's percentile thresholds so v2's `vol_extreme` gate is a tighter subset of truth-RISK_OFF. The v1 OLS, z-score, panic-pi, and flag thresholds above are otherwise unchanged.

**Empirical interpretation distribution** from the 2026-05-25 HYG backtest (4,708 days):

| Label | Count | % |
|---|---|---|
| NORMAL | 2,162 | 45.9% |
| SUPPRESSED | 2,452 | 52.1% |
| WATCH | 38 | 0.8% |
| PANIC | 37 | 0.8% |
| EDR | 9 | 0.2% |
| BOUNCE | 5 | 0.1% |
| RISK_OFF | 5 | 0.1% |

**Notable finding**: `SUPPRESSED` is the *modal* label at 52%. This means the regression's sign discipline (`β₁,β₂ ≤ 0`) fails on a majority of trading days. This is a genuine V1 limitation — see §6.

**Calibration provenance contract**: bumping `COMPOSITE_VERSION` in `vcg_scoring.py` requires updating every threshold value in this section in the same diff, plus a new entry in §7's Version history.

### 3.1 Composite credit-proxy research candidates (2026-05-26)

Production v1 uses HYG as the single credit proxy. To test whether a synthetic basket reads credit stress more reliably than any one issuer, the 2026-05-26 research PR added four candidate composite construction methods. None passed the promotion gate — production stays on HYG. The plumbing remains for future re-runs against extended benchmark coverage.

**Four composite candidates** (all `run_scope='research'`, persisted in `regime_backtest_runs` with `composite_version='2-candidate-*'`):

| Method | Composite version | Proxies | Construction |
|---|---|---|---|
| `risk_parity_3` | `2-candidate-rp3` | HYG / JNK / LQD | Daily 1/sigma normalized weights across all three, vol_window=63, weight_lag=1 |
| `risk_parity_hyjk` | `2-candidate-rp-hyjk` | HYG / JNK | Same as above but HY-only (excludes LQD; tests whether IG signal dilutes HY credit stress) |
| `hy_minus_ig_spread` | `2-candidate-hy-minus-ig` | HYG / JNK / LQD | Fixed weights (0.5 HYG + 0.5 JNK − 1.0 LQD): explicit HY-vs-IG spread, gross exposure 2× |
| `equal_weight_3` | `2-candidate-eq3` | HYG / JNK / LQD | Static 1/3 across all three (baseline that strips out the vol-weighting decision) |

Construction lives in `src/uw_scan/cards/vcg_basket.py` (research-only — production VCG path does not import it; enforced by `tests/unit/test_research_isolation.py`).

**No-lookahead invariant**: weights at aligned index `i` are a function only of returns `[< i]` via `.shift(weight_lag)` inside `risk_parity_weights`. With default `weight_lag=1`, `return[i]` cannot leak into `weight[i]`. Two load-bearing tests prove this: a perturbation test (changing `return[i]` does not change `weight[i]`) and a strict-offset reference test (at every position `i`, the actual weight matches the reference computed from the prefix `[:i+1]`).

**OLS causality contract**: signals computed at close `t` are actionable on `t+1`. Encoded in `cards/vcg_validation_metrics.actionable_lead_days`: an RO at close `t` whose next-session is after the trough returns negative lead, excluding the event from hit-rate denominators.

**Composite residual is NOT a weighted average of single-proxy residuals.** The composite path runs the canonical OLS on `(VIX, VVIX, basket_returns)` via `_compute_vcg_from_returns` — taking returns directly rather than reconstructing levels and re-differencing. Output schema separates `signal` (basket) from `attribution.basket_construction` (method, gross exposure, weights today) and `attribution.signal_breakdown` (per-proxy OLS for HYG / JNK / LQD regardless of which proxies the basket consumed, plus the `composite_single_proxy_disagreement` flag). The schema separation is intentional — future readers must not infer the composite residual is a weighted average.

**Promotion gate aggregation** (locked in spec §9, no author discretion):
- Primary utility + primary lead gates: computed on the `(SPX, Fast)` cell only.
- Robustness FP / alarm / hit-rate gates: median across all enabled benchmark × drawdown_def cells with `n_events > 0` (the comparator drops benchmarks below 4000 bars; report §2 quotes the actual denominator).
- FP definition: an RO is NOT a false positive iff any event interval `[peak, trough]` overlaps `[ro_date, ro_date + H_def]` trading days. Mid-drawdown RO is a hit, not an FP.
- Gate metric: `FP_episode_rate` (NOT `FP_day_rate`). Both reported.

**2026-05-26 validation outcome**: see `docs/research/regime/vcg-composite-validation-2026-05-26.md`. Headline:
- All four composite methods: **OVERALL FAIL** the promotion gate.
- Hit rate is 0% across the board. VCG's PANIC self-suppression (`vcg_adj = 0` when VIX ≥ 48) plus its low alarm-day-ratio (3-13 bps over 12+ years) means RO rarely overlaps with SPX drawdown windows.
- Benchmark coverage was thin: NDX and RUT were absent from `vol_index_daily`, leaving SPX-only evaluation (Fast / Medium / Major). When NDX / RUT become available, the robustness denominator triples and the comparator can be re-run without code change.
- Hard Guarantee #5 holds: no promotion candidate; production v1 HYG row (the canonical `regime_backtest_runs` row at `composite_version='1'`, `composite_method='single_proxy'`, `credit_proxy='HYG'`) stays in place. The API's `find_latest_run('vcg')` continues to surface this row.

**To re-run the comparator** after NDX / RUT are seeded:
```bash
uv run python scripts/compare_vcg_lead_time.py  # regenerates the report in place
```

## 4. Design decisions

### 4.1 Credit proxy: HYG default

HYG (iShares iBoxx HY Corporate Bond ETF) is the default proxy:

- Most-liquid HY ETF with ≥18y history (start: 2007-04-11)
- VIX-VVIX-HYG intersection: 4,803 trading days
- Tracks broad high-yield corporate credit spreads — exactly the segment most correlated with equity volatility

Alternatives:

- **JNK** (SPDR Bloomberg High Yield Bond ETF): 18y history but starts 2007-12-04. Slightly different basket; useful for A/B testing.
- **LQD** (iShares iBoxx Investment Grade Corporate Bond ETF): 24y history (2002-07-26) — but VVIX-bound to 2006-03-06, so effective 20y. Investment-grade rather than high-yield — different dynamic; useful as a separate stress lens, not a drop-in replacement.

The choice of HYG as default is *liquidity-and-history-driven*, not academically motivated. A future research deliverable could re-derive the choice via per-proxy AUC against the same backtest's named-crash window.

### 4.2 `COALESCE(adj_close, close)` for credit prices

Credit ETFs distribute monthly. Raw close-to-close returns include the ex-dividend drop, which a residual model would read as credit stress. The script uses `adj_close` (dividend-adjusted) when available, falling back to raw `close` with a logged warning. The 2026-05-25 backtest used `adj_close` throughout.

VIX and VVIX use raw `close` — they are indices, not securities, and have no distributions.

### 4.3 VVIX-then-VIX in the regression order

The regression's RHS is `[Δlog(VVIX), Δlog(VIX)]`. Putting VVIX first (β₁) gives the *expected*-vol signal precedence; β₂ captures the *current*-vol residual. Reversing the order changes the betas but not the residual — the orthogonalisation against the full span is what matters, and OLS handles that order-invariantly. The convention follows Park (2015): VVIX leads, VIX coincides.

### 4.4 Sign discipline (`β₁,β₂ ≤ 0`) gates the signal

A positive β₁ or β₂ would say "credit strengthens as vol rises" — an empirically rare and theoretically dubious relationship. When the rolling OLS fits one, the most likely explanation is a regression artifact (small-window collinearity, noisy returns) rather than a real market relationship. Rather than serve those days as actionable signal, the script labels them `SUPPRESSED` and the residual is ignored.

The cost: at 52% of trading days, the signal is `SUPPRESSED`. The benefit: when VCG does fire (`WATCH`/`EDR`/`RISK_OFF`/`BOUNCE`), the underlying regression has economically plausible coefficients.

## 5. Academic foundations

VCG's three structural choices map to established academic literature:

### 5.1 Linear regression of credit on equity vol

Campbell, J. Y., & Taksler, G. B. (2003). "Equity Volatility and Corporate Bond Yields." *Journal of Finance* 58(6), 2321–2350. DOI: [10.1046/j.1540-6261.2003.00607.x](https://onlinelibrary.wiley.com/doi/10.1046/j.1540-6261.2003.00607.x).

Establishes that idiosyncratic firm-level equity volatility explains as much cross-sectional variation in bond yields as credit ratings. Empirically validates the right-hand side of VCG's regression — equity-vol-explains-credit is a real relationship, not a numerical coincidence.

### 5.2 Residual (not fitted value) as the signal

Collin-Dufresne, P., Goldstein, R. S., & Martin, J. S. (2001). "The Determinants of Credit Spread Changes." *Journal of Finance* 56(6), 2177–2207. DOI: [10.1111/0022-1082.00402](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00402).

Variables that should *in theory* determine credit-spread changes (Treasury rates, equity volatility, leverage) have only limited explanatory power; the unexplained variance is large and economically meaningful. **This is exactly the motivation for VCG: the residual carries information the inputs do not.**

### 5.3 Residual-as-dislocation methodology

Pasquariello, P. (2014). "Financial Market Dislocations." *Review of Financial Studies* 27(6), 1868–1914. RFS Best Paper Runner-Up.

Constructs a model-free measure of cross-market dislocations from arbitrage-parity violations and shows they price expected returns. VCG's z-scored residual is a one-pair instance of this broader methodology.

### 5.4 VVIX as the second covariate (not VIX alone)

Park, Y.-H. (2015). "Volatility-of-volatility and tail risk hedging returns." *Journal of Financial Markets*.

VVIX as a leading rather than coincident vol signal; including both VIX and VVIX in the right-hand side lets the residual orthogonalize against both "current vol" and "expected change in vol."

### 5.5 Regime framing for an aggregate financial-conditions signal

Adrian, T., Boyarchenko, N., & Giannone, D. (2019). "Vulnerable Growth." *American Economic Review* 109(4), 1263–1289. DOI: [10.1257/aer.20161923](https://www.aeaweb.org/articles?id=10.1257%2Faer.20161923).

Deteriorating financial conditions move the lower (tail) quantiles of GDP growth, not the median. VCG as a *regime* indicator (PANIC / TRANSITION / DIVERGENCE; RISK_OFF / EDR / WATCH / BOUNCE / NORMAL) is consistent with this asymmetric tail-risk framing.

### 5.6 Honest reading of what the literature does and does NOT justify

**Justified:**
- Including VVIX, VIX, and a credit proxy as the three core VCG inputs.
- The residual-z-score construction.
- The regime taxonomy with asymmetric tail behaviour.

**NOT justified** — these are xenon-inherited calibration choices:
- The specific threshold values (`VCG_TRIGGER=2.0`, `VCG_RO_TRIGGER=2.5`, `BOUNCE_TRIGGER=-3.5`, `VIX_FLOOR=28`, `VIX_PANIC_LOW=40`, etc.). No published study derives them.
- The choice of HYG as default credit proxy over JNK / LQD. The 18-year HYG-bound history and liquidity rank the choice, not academic comparison.
- The panic-adjustment `π = clamp((VIX-40)/8, 0, 1)`. Not in the literature; a xenon-era construct with empirical but not theoretical motivation.

The distinction matters: the *methodology* has academic ground. The *calibration* does not, and a v2 calibration spec must show its own empirical justification.

## 6. Known limitations

### 6.1 `SUPPRESSED` is the modal label

In the 2026-05-25 HYG backtest, 52% of trading days produced `SUPPRESSED` because the rolling OLS's `β₁` or `β₂` flipped positive. The 21-day window is short enough that noisy returns and small-sample collinearity routinely break sign discipline. This is genuine V1 limitation: more than half the time, VCG is silent.

A v2 calibration could lengthen `OLS_WINDOW`, relax the sign-gate (e.g., accept `β` within a band around zero rather than strictly ≤ 0), or use ridge-regularised regression to stabilise coefficients. None of these are in V1.

### 6.2 Panic-π collapses `vcg_adj → 0` when VIX ≥ 48

When VIX clears 48, π = 1 and `vcg_adj = 0` regardless of the underlying `vcg`. The displayed `interpretation` becomes `PANIC` driven entirely by the VIX gate — not by the residual model. **Users should always inspect raw `vcg` (not just the label or `vcg_adj`) for high-VIX regimes.**

The 2020-03-16 COVID circuit breaker is a clear example: raw vcg = -3.47 (a meaningful BOUNCE-territory residual), but vcg_adj = 0.00 because VIX cleared 48, so the label reads PANIC and the residual signal is invisible in the label.

### 6.3 VCG can be late or counter-intuitive on named crashes

The 2008-09-15 Lehman bankruptcy ±5d window shows:

| Offset | vcg | vcg_adj | β₁ | β₂ | sign_ok | label |
|---|---|---|---|---|---|---|
| −5 | -0.08 | -0.08 | +0.030 | +0.003 | false | SUPPRESSED |
| −3 | -0.69 | -0.69 | +0.034 | -0.000 | false | SUPPRESSED |
| −1 | +0.31 | +0.31 | +0.036 | -0.002 | false | SUPPRESSED |
| 0 | -4.00 | -4.00 | -0.052 | -0.038 | true | BOUNCE |
| +1 | -3.35 | -3.35 | -0.003 | -0.045 | true | NORMAL |
| +3 | +6.06 | +6.06 | -0.188 | -0.040 | true | RISK_OFF |
| +5 | +2.64 | +2.64 | -0.122 | -0.078 | true | RISK_OFF |

VCG did NOT lead Lehman: the days leading up are `SUPPRESSED` (β₁ positive). On day 0, the regression flips, and VCG reads `BOUNCE` — its counter-signal interpretation — because the residual was a large *negative* z. Only by day +3 does VCG fire `RISK_OFF`. This is real lag: the residual model needs the regression coefficients to settle into their post-event configuration before the signal becomes meaningful.

**Reading discipline:** VCG is most useful as a *confirming* indicator and a regime-state label, not as a leading-edge crash predictor. Pair with CRI or a leading vol signal.

### 6.4 Single credit proxy at a time

The runtime computes VCG against one proxy per request (default HYG). It does not surface an ensemble across HYG/JNK/LQD or compute consistency across them. A v2 could surface a "credit-stress consensus" by running all three and reporting agreement.

### 6.5 One-tailed positive-residual asymmetry

`WATCH`/`EDR`/`RISK_OFF` all fire on positive vcg (credit-weakening-faster-than-vol-implies). The only negative-z label is `BOUNCE` at vcg < −3.5. The cutoffs are asymmetric: positive z fires at +2.0, negative at −3.5. This bakes in a stress-bias prior: VCG is more sensitive to stress than to relief.

### 6.6 Weekend / holiday alignment sensitivity

The 21-day OLS is in *trading* days, not calendar days. Holidays change the back-window's calendar span. Most of the time this is invisible, but around long weekends (e.g., post-Christmas) the regression's effective lookback shifts. Not a critical issue at V1; flagged as a known curiosity.

### 6.7 HYG dividend noise — partially mitigated, not eliminated

`COALESCE(adj_close, close)` handles the dividend-adjusted price, but adj_close itself depends on the data vendor's adjustment. Subtle differences between vendor adjustments can produce small residual spikes around HYG ex-dividend dates. This is observable in the daily payload but does not (in V1) propagate to interpretation labels because the per-day spikes are typically smaller than the `VCG_TRIGGER = 2.0` threshold.

## 7. Version history

### v1 (2026-04, as-ported)

Source: xenon/src/xenon/scanners/vcg.py at commit `d3cbc08`.

Calibration thresholds (`OLS_WINDOW=21`, `Z_WINDOW=63`, `VCG_TRIGGER=2.0`, `VCG_RO_TRIGGER=2.5`, `BOUNCE_TRIGGER=-3.5`, `VIX_FLOOR=28`, `VIX_EDR=25`, `VIX_PANIC_LOW=40`, `VIX_PANIC_HIGH=48`, `VVIX_ELEVATED=100`, `VVIX_EXTREME=120`) inherited verbatim from xenon. Not re-derived against this DB.

First DB-of-record backtest: 2026-05-25 (this PR). Result:

- 18.5-year HYG-bound history; 4,708 days post-burn-in
- Modal label `SUPPRESSED` at 52% (sign-discipline failures dominate)
- 5 RISK_OFF firings, 9 EDR, 38 WATCH, 5 BOUNCE, 37 PANIC

**v1 verdict from the ±5d named-crash window evidence**: VCG is descriptive-but-late. It does not lead crashes (Lehman: SUPPRESSED days −5 through −1, then BOUNCE day 0, RISK_OFF day +3). It does flag credit-stress dispersion *after* the fact (the day +3 / +5 RISK_OFF firings on Lehman are real and consistent with credit markets needing days to fully reprice). **V1 ships as documented-as-ported**; a recalibration to v2 is owed but is out of scope for this closure and requires its own spec under `docs/superpowers/specs/`.

### v2 (2026-05-27) - Cascade and absolute-vol override

Shipped per spec `docs/superpowers/specs/2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md` (evidence: forensic audit `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md`).

Changes:

1. Cascade reorder: `pi_panic >= 1.0 -> PANIC` now fires above `not sign_ok -> SUPPRESSED`.
2. New absolute-vol-stress override: `vix_percentile_rank >= 0.95 AND vvix_percentile_rank >= 0.95 -> RISK_OFF`, computed before the SUPPRESSED gate.
3. Two new payload fields: `vix_percentile_rank` and `vvix_percentile_rank` (`float | None`, `None` during the 252-bar warmup).
4. `COMPOSITE_VERSION = 2`.

Not changed in v2: `OLS_WINDOW`, beta-sign-discipline thresholds, panic-pi clamp, ensemble proxy support, regime-aware floors. These remain v2.1+ candidates.

Acceptance gates passed on the seven-crisis fixture: contradiction count = 0; crisis-window stress recall >= v1 baseline 0.0985.

### v2.1+ candidates

- Lengthen `OLS_WINDOW` to 42 or 63 to stabilise sign discipline.
- Replace strict `β <= 0` with a small positive band.
- Add ensemble proxy support.
- Add symmetric positive/negative thresholds for WATCH / EDR / BOUNCE.
- Add regime-aware VIX floors.
- Replace the linear panic-pi clamp with a continuous recalibrated function.
