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
| 4 | Trend Break | SPX distance below 100d MA | one-sided (0–25 when below MA, 0 when above) |

The sum is clipped to [0, 100]. No normalization or PCA — straight addition by design, so a single bar telling the story stays visible in the UI.

## 3. Calibration

Thresholds were chosen against the empirical distribution of each input on `uw_scan.vol_index_daily`, 2006-05-15 through 2026-05-15:

| Signal | p25 | p50 | p75 | p90 | p95 | Floor | Ceiling | Source |
|---|---|---|---|---|---|---|---|---|
| VIX | 13.96 | 17.62 | 22.73 | 28.58 | 32.95 | **15** | **40** | Floor ≈ "calm boundary" (CBOE), ceiling ≈ p98 (panic) |
| VVIX | 82.45 | 90.84 | 102.09 | 115.26 | 122.32 | **85** | **130** | Floor ≈ p25; mid-mark 110 = practitioner warning (Convex, MenthorQ); ceiling near p98 |
| COR1M | 24.27 | 35.89 | 49.04 | 61.27 | 69.90 | **25** | **70** | Floor ≈ p25; mid-mark 60 = crash-trigger threshold (also p90+) |

### VIX

```
level_score = clip((vix - 15) / (40 - 15) × 15, 0, 15)
roc_score   = clip(max(vix_5d_roc, 0) / 60 × 10, 0, 10)
```

VIX 5d RoC > +60% (one-week doubling-ish) is rare enough to deserve full marks. The RoC is one-sided: VIX dropping fast doesn't increase crash risk.

### VVIX

```
level_score = clip((vvix - 85) / (130 - 85) × 12, 0, 12)
ratio_score = clip((vvix_vix_ratio - 5) / (8 - 5) × 7, 0, 7)
roc_score   = clip(max(vvix_5d_roc, 0) / 25 × 6, 0, 6)
```

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

### Trend Break (renamed from "Momentum")

```
if spx_distance_pct >= 0:
    score = 0
else:
    score = clip(|spx_distance_pct| / 10 × 25, 0, 25)
```

This is **not** a momentum signal in the standard sense. It is one-sided: zero when SPX is at or above its 100d MA, scaling up linearly as SPX drops below. At -10% below the MA the component saturates.

The asymmetry is intentional: a CRI that fires on uptrends is a CRI that cries wolf. Historically SPX is above its 100d MA on roughly 70–75% of trading days, so this component is dormant on most days *by design*. The UI label "TREND BREAK" makes that explicit instead of letting users expect graded response across both directions.

The original code labeled this "MOMENTUM" with a tooltip claiming "combined with VIX 5-day rate of change" — the tooltip described a richer formula than the code implements. Both are corrected here.

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

`scripts/backtest_cri.py` recomputes CRI for every day in `vol_index_daily` ∩ `daily_ohlc` (2006-05–2026-05). Output: `docs/research/regime/cri-backtest-2006-2026.{md,csv}` with:
- Score distribution (mean, p25/50/75/90/95, histogram)
- Level transition counts (LOW→ELEVATED, ELEVATED→HIGH, etc.)
- Hit-rate against named crash dates: 2008-09-15 (Lehman), 2010-05-06 (flash crash), 2011-08-08 (US downgrade), 2015-08-24 (Black Monday China), 2018-02-05 (volmageddon), 2018-12-24 (Q4 selloff), 2020-02-28 / 2020-03-16 (COVID), 2022-06-13 (rate-hike vol)

The backtest is **regenerated** when calibration changes and the diff is reviewed before merging.

Out-of-sample validation against 20 years of daily data showed VIX raw level alone captures most of the predictive signal for 5%/20-day drawdowns; CRI's value is in being a structured, decomposable regime monitor rather than a strict alpha. Read `docs/research/regime/cri-validation.ipynb` Section 9 for the honest accuracy breakdown.
