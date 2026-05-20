# CRI Methodology

Source of truth for the Crash Risk Indicator (CRI) math, calibration, and design decisions.

**Code:** `src/uw_scan/cards/cri_scoring.py`
**Scanner:** `src/uw_scan/scanners/cri.py`
**API:** `src/uw_scan/api/routers/regime.py`
**UI:** `web/components/regime/CriSubTab.tsx`
**Persistence:** `uw_scan.cri_snapshots` (JSONB `payload` column)

---

## 1. What CRI is

CRI is a 0–100 composite score that estimates how close the US equity market is to a *crash regime* on any given trading day. It is **not** a directional signal, **not** a general volatility regime indicator, and **not** a price-target-style forecast. It is a structured stack of four well-known stress signals — implied vol level, vol-of-vol, implied cross-stock correlation, and trend break — summed with bounded weights.

The score maps to four bands:

| Band | Range | Meaning |
|---|---|---|
| LOW | 0 ≤ score < 25 | Calm or normal regime |
| ELEVATED | 25 ≤ score < 50 | One or two stress dimensions firing |
| HIGH | 50 ≤ score < 75 | Multiple stress dimensions firing simultaneously |
| CRITICAL | 75 ≤ score ≤ 100 | All four firing; consistent with the worst historical drawdowns |

## 2. Component framework

Four components, each scoring 0–25:

| # | Component | Inputs | Sub-scores |
|---|---|---|---|
| 1 | VIX | level, 5-day RoC | level (0–15) + RoC (0–10) |
| 2 | VVIX | level, VVIX/VIX ratio, 5-day RoC | level (0–12) + ratio (0–7) + RoC (0–6) |
| 3 | Correlation | COR1M level, 5-day change | level (0–17) + spike (0–8) |
| 4 | Trend Break | SPX (cash close from `vol_index_daily`) distance below 100d MA — SPY in `daily_ohlc` is a fallback when SPX is unavailable | one-sided (0–25 when below MA, 0 when above) |

The sum is clipped to [0, 100]. No normalization or PCA — straight addition by design, so a single bar telling the story stays visible in the UI.

## 3. Calibration

Thresholds were chosen against the empirical distribution of each input on `uw_scan.vol_index_daily`, 2006-05-15 through 2026-05-15. Floor/ceiling were tightened in v3 (2026-05-20) to recover sensitivity that the v1/v2 calibration lost in the 14-18 VIX / 82-94 VVIX band:

| Signal | p25 | p50 | p75 | p90 | p95 | v1/v2 Floor | **v3 Floor** | Ceiling |
|---|---|---|---|---|---|---|---|---|
| VIX | 13.96 | 17.62 | 22.73 | 28.58 | 32.95 | 15 | **13** | 40 |
| VVIX | 82.45 | 90.84 | 102.09 | 115.26 | 122.32 | 85 | **80** | 130 |
| COR1M | 24.27 | 35.89 | 49.04 | 61.27 | 69.90 | 25 | 25 (unchanged) | 70 |

### VIX (v3)

```
level_score = clip((vix - 13) / (40 - 13) × 15, 0, 15)
roc_score   = clip(max(vix_5d_roc, 0) / 40 × 10, 0, 10)
```

v3 changes:
- **Floor 15 → 13** so the calm-but-elevated band (VIX 14-18, the modal range) generates positive signal. The v1 floor at 15 left the entire 14-18 band scoring 0 on level.
- **RoC denominator 60 → 40** so a +30% VIX week saturates the sub-score (a +40% week is the practical ceiling; +60% is so rare it's almost never observed). The v1/v2 denominator of 60 meant routine +5-10% RoC weeks scored under 2 points.

The RoC is one-sided: VIX dropping fast doesn't increase crash risk.

### VVIX (v3)

```
level_score = clip((vvix - 80) / (130 - 80) × 12, 0, 12)
ratio_score = clip((vvix_vix_ratio - 5) / (8 - 5) × 7, 0, 7)
roc_score   = clip(max(vvix_5d_roc, 0) / 25 × 6, 0, 6)
```

v3 change: **floor 85 → 80** to mirror the same tactical sensitivity the VIX scorer gained. VVIX rarely sits below 80; the prior 85 floor meant the 80-94 band was a dead zone.

**Three sub-scores because three different things matter:**

- **Level**: absolute VVIX. High = volatile uncertainty about future VIX.
- **Ratio (VVIX/VIX)**: per practitioner literature (Convex, MenthorQ, TradingView), normal range is 4.0–6.0 and >6.0 signals tail-hedging demand. The mechanism: when VVIX rises against a flat or declining VIX, someone is paying up for VIX call protection before stress is visible in spot. VVIX leads VIX in tail-hedging. The ratio dropping below 4 *during* a crash is a separate phenomenon and we don't try to capture it here — by then the level component is saturated anyway.
- **RoC (5-day)**: 5-day VVIX rate of change. Catches the *expansion* of tail-hedging demand even when level and ratio are still mid-range. This is the canonical leading signal the literature points to.

The 25% RoC ceiling corresponds roughly to a one-week 25% spike, comparable to early-stage stress moves in 2018Q4 and 2022.

### Correlation

```
level_score = clip((cor1m - 25) / (70 - 25) × 17, 0, 17)
spike_score = clip(max(cor1m_5d_change, 0) / 20 × 8, 0, 8)
```

COR1M's CBOE definition is the spread between SPX implied vol and the average single-name implied vol — high values mean the market is pricing in tight cross-sectional co-movement (a single-factor regime). Floor of 25 is roughly p25 of the historical distribution; ceiling of 70 is roughly p95 and coincides with the crash-trigger threshold of 60 firing.

### Trend Break (v3 — structural + tactical)

v3 splits the 0-25 component into two sub-scores:

```
# Structural (0-15): rises when SPX trades below 100d MA
if spx_distance_pct >= 0:
    structural = 0
else:
    structural = clip(|spx_distance_pct| / 10 × 15, 0, 15)

# Tactical (0-10): rises with drawdown from trailing-20-session high
if pullback_20d_pct >= 0:
    tactical = 0
else:
    tactical = clip(|pullback_20d_pct| / 4 × 10, 0, 10)

score = clip(structural + tactical, 0, 25)
```

**Why split:** v1/v2's single one-sided structural sub-score only fired when SPX was below the 100d MA. Historically SPX is above its MA ~70-75% of trading days, so the component was dormant by design. That dormancy is correct for crash detection but blind to tactical multi-session pullbacks (e.g. a -2% drop over 3 days while SPX is still +6% above its MA). v3's tactical sub-score captures that signal without false-positiving on uptrends: it saturates at -4% from the 20d rolling high, which is the practical low-end of "this drop warrants noticing." See [§8 v3 changelog](#8-validation) for the motivating data and the OOS trade-off.

**Tactical saturation rationale:** -4% from the 20d high is a non-trivial tactical pullback; deeper drawdowns add no marginal information to a regime monitor (the structural sub-score takes over via the MA breach). -4% was chosen over -3% and -6% during the v3 design conversation to land today's CRI at the user-requested 10-15 range under typical "noisy but not crashing" conditions.

The asymmetry below structural is intentional: a CRI that fires on uptrends is a CRI that cries wolf. The UI label "TREND BREAK" stays.

## 4. The crash trigger (separate from the composite)

Three simultaneous conditions, all required to "fire":

1. SPX < 100d MA
2. 20-day annualized realized vol > 25%
3. COR1M > 60

This is a binary regime detector, separate from the composite. The composite score can be high without the trigger firing (and vice versa, though rarely). The trigger is the operational signal; the composite is the gradient.

## 5. Web research summary

Conducted 2026-05-19, four parallel searches against practitioner and academic sources. Findings that informed design decisions:

- **VVIX/VIX ratio direction**: the *level* of the ratio is a known leading indicator. Normal range 4.0–6.0; >6.0 warning; >6.5 with VIX <18 strongly bearish (Convex, MenthorQ, TradingView indicator). The mechanism is rising VVIX against flat VIX = tail-hedging demand. This was initially flagged as a possible bug in the review (because the ratio *drops* during the crash itself), but the literature supports the code's pre-crash framing. **Decision: keep the direction, add RoC sub-score to also capture the expansion.**

- **VVIX historical range**: CBOE's own VVIX whitepaper (2006–2012 sample) reports mean ~86, range 60–145. Our DB (2006–2026) shows mean 93.48, median 90.84. The original VVIX floor of 90 sat at the historical median, meaning roughly 50% of all days produced zero VVIX level-score. **Decision: drop floor to 85, drop ceiling to 130, redistribute weight to (level 12 / ratio 7 / RoC 6).**

- **VIX thresholds**: practitioner framework cites <15 calm, 20–30 fear, 30+ panic. Code's 15 / 40 maps cleanly. **No change.**

- **COR1M behavior**: research (arXiv: implied correlation from VaR) confirms implied correlation runs higher in left tails than right tails. Crash-trigger threshold of 60 corresponds to ~p90 in our 20y history. **No change.**

- **Composite construction**: practitioner composites typically include VIX term structure (contango ↔ backwardation flip) and put/call ratio. CRI uses 4 components vs. typical 6–8. **Deferred to a follow-up spec** — adds data-source dependencies and breaks the 4×25=100 architecture.

### Sources

- CBOE — *Double the Fun with CBOE's VVIX Index* (whitepaper): https://cdn.cboe.com/resources/indices/documents/vvix-termstructure.pdf
- Convex — *Vix of VIX (VVIX): Definition & Market Analysis*: https://convextrade.com/glossary/vol-of-vol-skew
- MenthorQ — *The Relationship Between VVIX and VIX*: https://menthorq.com/guide/the-relationship-between-vvix-and-vix/
- SpotGamma — *VVIX Explained*: https://spotgamma.com/vvix-explained-what-the-volatility-index-tells-traders/
- Charles Schwab — *What Is VVIX and Why Does It Matter?*: https://www.schwab.com/learn/story/whats-vvix-and-why-does-it-matter
- Federal Reserve FEDS 2013-54 — *Volatility of Volatility and Tail Risk Premiums*: https://www.federalreserve.gov/econres/feds/volatility-of-volatility-and-tail-risk-premiums.htm
- ScienceDirect — *Volatility-of-volatility and tail risk hedging returns*: https://www.sciencedirect.com/science/article/abs/pii/S1386418115000403
- Gao & Pan (SAIF) — *Option-Implied Crash Index*: https://en.saif.sjtu.edu.cn/junpan/CIX.pdf
- AUT ACFR — *The Information Content of the Decomposed VVIX and VSKEW*: https://acfr.aut.ac.nz/__data/assets/pdf_file/0003/541902/ATR-Paper-Yahua-Roh-ATR-Xu-_-paper.pdf
- arXiv — *Implied correlation from VaR*: https://arxiv.org/pdf/1103.5655
- TradingView — *VVIX/VIX Ratio with Interpretation Levels* (community indicator): https://www.tradingview.com/script/FVF6lHU5/
- TradeEdgePro — *Tail Risk Indicators Traders Should Watch in 2026*: https://tradeedgepro.net/tail-risk-indicators-watch-2026/

## 6. UI reference markers

Each `ComponentBar` shows the score as a filled portion of a 0–25 track. Reference marks help users understand where the value sits relative to known thresholds:

| Component | Mid-mark (score units) | Mid-mark meaning |
|---|---|---|
| VIX | 5.0 | VIX ≈ 23 — between calm and fear |
| VVIX | 6.7 | VVIX ≈ 110 — practitioner warning level |
| Correlation | 13.0 | COR1M = 60 — crash-trigger threshold |
| Trend Break | 7.5 | SPX -3% below 100d MA — mild stress |

A prior-day score marker (small dot) sits on the track at the prior-day value so direction-of-travel is visible at a glance.

## 7. What we deliberately did not change

- **Payload JSON key `cri.components.momentum` stays as-is.** Renaming would invalidate every historical snapshot in `uw_scan.cri_snapshots` and break the API contract with no functional benefit. The label change is UI-only.
- **The 4×25=100 architecture stays.** Adding a 5th component or moving to a weighted PCA-style score would require re-bandscoring (LOW/ELEVATED/HIGH/CRITICAL) and is out of scope.
- **No percentile-based scoring (yet).** Replacing fixed thresholds with rolling percentiles is a defensible future direction but adds dependencies and changes the interpretability of "VIX 20 = 5 points" — deferred.

## 8. Validation

Two layers of validation exist:

**(a) Warm-store backtest** — `scripts/backtest_cri.py` recomputes CRI for every day in `vol_index_daily` ∩ `daily_ohlc`. Output: `docs/research/regime/cri-backtest.{md,csv}` with:
- Score distribution (mean, p25/50/75/90/95)
- Level distribution (LOW/ELEVATED/HIGH/CRITICAL)
- Hit-rate against named crash dates

The aligned window is bounded by the *shortest* series in the DB. `vol_index_daily` covers VIX 1990→2026, VVIX 2006→2026, COR1M 2006→2026, and SPX 1975→2026 (with VIX3M from 2009 as a sidecar for the term-structure tile). The backtest's effective floor is 2006 — the VVIX start — so the warm-store report now spans the GFC, Volmageddon, COVID, and 2022 rate-hike vol. The `spx_source` field on each persisted snapshot flags whether SPX or the SPY fallback fed the day's score.

**(b) 20y OOS validation** — `docs/research/regime/cri-validation.ipynb` is the canonical long-horizon test. It reads the parquet data lake at `~/market-warehouse/data-lake/bronze/asset_class=volatility/` for VIX/VVIX/COR1M and equity OHLC, runs a walk-forward split (train 2007-2015 / test 2016-2026), and reports ROC AUC + threshold-matched precision/recall against three crash-proxy labels (`label_dd5`, `label_vix30`, `label_dd10`).

**(c) OOS gate (CI-enforced)** — `tests/integration/regime/test_cri_oos_gate.py` reads `docs/research/regime/oos-summary.json` (regenerated by `backtest_cri.py --write-oos-summary`) and asserts the current composite version's AUC on dd5/dd10 stays within 0.02 of the v1 published baseline. The JSON is the authoritative source of current AUC numbers — this doc deliberately does not embed AUC values that could drift from the script output. Run `cat docs/research/regime/oos-summary.json` for the current table.

Honest finding from (b): VIX raw level alone captures most of the predictive signal for 5%/20-day drawdowns; CRI's value is in being a **structured, decomposable regime monitor** rather than a strict alpha generator. Read Section 9 of the notebook for the full accuracy breakdown and the caveats.

### v3 — 2026-05-20

**Motivation.** v1/v2 was calibrated for crash regime detection on the dd10 (SPX -10%-in-60d) horizon. Operator feedback during the 2026-05 calm-but-elevated vol weeks: the composite read 6/100 LOW during a ~2% SPX pullback over 3 sessions while VIX hovered 17-18 and 30d trailing VIX was actually higher than today (vix_zscore_30d at -0.28). The user wanted CRI to read 10-15/100 LOW-with-alert in that scenario without losing the crash-detection mandate.

**Changes.**
- VIX level floor 15 → 13; VIX RoC denominator 60 → 40
- VVIX level floor 85 → 80
- Trend Break reshape: structural (0-15, vs 100d MA) + tactical (0-10, vs 20d high, saturates at -4%)
- New `composite_version` field nested under `cri` in the snapshot payload, typed `Literal[1, 2, 3] | None`
- New top-level fields `pullback_20d_pct` (%) and `vix_delta_3d` (in **VIX points, not %** — same convention as `cor1m_5d_change`) surfaced for UI consumption
- Band cutoffs unchanged (25 / 50 / 75)
- Migration `050_cri_composite_version_backfill.sql` labels all pre-v3 historical snapshots as `composite_version=1`

**OOS results.** See `docs/research/regime/oos-summary.json` for the authoritative AUC table. Summary of the 2026-05-20 backtest:
- v3 dd5 AUC improved over v1 baseline (tactical pullback discrimination)
- v3 dd10 AUC dipped slightly below v1 baseline but well within the documented 0.02 tolerance (longer-horizon crash detection trades a small amount of AUC for tactical responsiveness — the explicit purpose of the calibration)

The OOS gate test in `tests/integration/regime/test_cri_oos_gate.py` enforces both bounds — CI blocks merge if either label drops more than 0.02 below v1.
