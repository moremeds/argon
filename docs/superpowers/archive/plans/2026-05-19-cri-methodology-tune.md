# CRI Methodology Tune — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-calibrate the Crash Risk Indicator (CRI) so its component scores produce meaningful gradation across normal volatility regimes, rename the misleading "Momentum" label, add visual reference markers to the component bars, document the math/research/decisions in a single source of truth, and validate the composite against 20 years of historical data.

**Architecture:** All math lives in `src/uw_scan/cards/cri_scoring.py` (pure functions). Persistence stays in the existing `cri_snapshots` JSONB payload — no DB migration needed. The Pydantic contract gains one new optional field (`vvix_5d_roc`). The UI changes are confined to `web/components/regime/CriSubTab.tsx` (`ComponentBar` gets reference markers + the Momentum label becomes "TREND BREAK"). A new standalone backtest script `scripts/backtest_cri.py` reads the 20y `vol_index_daily` + `daily_ohlc` tables and writes a Markdown report under `docs/research/regime/`. A new methodology doc captures the full review, web research, and design decisions as the source of truth.

**Tech Stack:** Python 3.13 / numpy / Pydantic v2 / FastAPI for the API side. React 19 / TypeScript / hand-rolled SVG for the UI. pytest for tests. psycopg 3 for DB reads in the backtest script.

**Scope guard:** This plan covers recommendations #1–#6 from the methodology review (calibration constants, UI reference markers, "Momentum" rename, VVIX/VIX ratio direction documentation, VVIX 5d-RoC sub-score, 20y backtest). Recommendation #7 (adding VIX term structure + put/call ratio as new components) is **explicitly deferred** to a follow-up spec — it expands data sources, breaks the 4×25=100 component symmetry, and deserves its own design pass.

**Non-goals:**
- Renaming the payload JSON key `cri.components.momentum`. The label changes in the UI only; the JSON contract stays stable so historical snapshots remain readable.
- Adding new CBOE data sources (term structure, put/call).
- Re-architecting CRI as a percentile-based scoring system (could be a future spec; out of scope here).

**Background:**
- The review that triggered this plan is in conversation context (CRI showing 5/100 with VIX 18.43, VVIX 92.94, COR1M 10.83, SPY +7.26% vs 100d MA).
- Empirical thresholds were checked against `vol_index_daily` (n=5,021–9,186 daily observations, 2006-2026).
- Web research validated VVIX/VIX ratio direction (practitioner consensus: 5–6 normal, >6 warning) and VVIX historical mean (~86 per CBOE 2006-2012 whitepaper, 93 in our DB through 2026).

---

## File map

**Create:**
- `docs/research/regime/cri-methodology.md` — methodology source of truth (review findings + web research + decisions)
- `docs/research/regime/CLAUDE.md` — pointer doc telling future readers where things live
- `scripts/backtest_cri.py` — standalone backtest CLI
- `docs/research/regime/cri-backtest-2006-2026.md` — generated backtest report (committed snapshot)
- `docs/research/regime/cri-backtest-2006-2026.csv` — generated backtest data (committed snapshot)
- `tests/unit/test_backtest_cri.py` — smoke test for the backtest script

**Modify:**
- `src/uw_scan/cards/cri_scoring.py` — `score_vvix_component` signature + math; `compute_cri` signature; `run_analysis` payload (adds `vvix_5d_roc`)
- `src/uw_scan/api/schemas.py` — `CriResponse.vvix_5d_roc`, `CriHistoryEntry.vvix_5d_roc`
- `tests/unit/test_cri_scoring.py` — update existing VVIX/compute_cri tests; add RoC tests
- `tests/integration/test_cri_scanner.py` — assert new fields appear in payload
- `web/components/regime/CriSubTab.tsx` — `ComponentBar` reference markers + "TREND BREAK" label + tooltip text
- `web/lib/types.ts` — regenerated from OpenAPI
- `web/tests/unit/CriSubTab.test.tsx` — update existing `MOMENTUM` assertion to `TREND BREAK`; add marker tests. (NOT `regime-page.test.tsx` — that file mocks `CriSubTab` entirely so it can't assert internal markup.)

---

## Phase 0: Branch + scope confirmation

### Task 0: Create feature branch

**Files:**
- None (branching only)

- [ ] **Step 1: Create branch and confirm clean tree**

Run:
```bash
git checkout -b feat/cri-methodology-tune
git status
```
Expected: branch `feat/cri-methodology-tune` checked out. Existing uncommitted files (`web/next-env.d.ts`, `docs/Section62_Metals_Futures_Products.pdf`, `docs/reviews/`, etc.) are unrelated noise from prior sessions — leave them untouched.

- [ ] **Step 2: Sanity-check the existing test suite passes**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py -v
```
Expected: all tests PASS (this is the baseline; the plan modifies these tests in later tasks).

---

## Phase 1: Methodology documentation (source of truth)

The doc lands first because every code change downstream cites a specific section. Future-me reading this file should understand *why* every threshold is what it is.

### Task 1: Write `docs/research/regime/cri-methodology.md`

**Files:**
- Create: `docs/research/regime/cri-methodology.md`
- Create: `docs/research/regime/CLAUDE.md`

- [ ] **Step 1: Write the methodology doc**

Create `docs/research/regime/cri-methodology.md` with this exact content:

```markdown
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
```

- [ ] **Step 2: Write the CLAUDE.md pointer**

Create `docs/research/regime/CLAUDE.md`:

```markdown
# docs/research/regime — CRI methodology research

## Files

- `cri-methodology.md` — **source of truth** for CRI math, calibration, and design decisions. Read this before changing any threshold in `src/uw_scan/cards/cri_scoring.py`.
- `cri-backtest-2006-2026.{md,csv}` — generated by `scripts/backtest_cri.py`. Regenerate after any calibration change and review the diff.

## When to update

- After changing any constant in `cri_scoring.py`: update §3 of `cri-methodology.md` with the new threshold and rationale.
- After running the backtest: commit the regenerated `cri-backtest-2006-2026.{md,csv}` so reviewers can see the impact.
```

- [ ] **Step 3: Verify the docs render cleanly**

Run:
```bash
ls docs/research/regime/
wc -l docs/research/regime/cri-methodology.md
```
Expected: both files exist; methodology doc is ~200 lines.

- [ ] **Step 4: Commit (milestone)**

```bash
git add docs/research/regime/cri-methodology.md docs/research/regime/CLAUDE.md
git commit -m "docs(cri): methodology source of truth — review findings + web research"
```

---

## Phase 2: Math + scoring (Python, TDD)

### Task 2: Add VVIX 5d-RoC to `run_analysis` payload

**Files:**
- Modify: `src/uw_scan/cards/cri_scoring.py:280-365` (`run_analysis` function)
- Test: `tests/unit/test_cri_scoring.py`

The RoC value lands in the payload first as a *data point only*. The scoring function consumes it in Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_cri_scoring.py` (place after the existing `run_analysis` test if there is one, otherwise near the end):

```python
def test_run_analysis_exposes_vvix_5d_roc() -> None:
    """run_analysis should emit vvix_5d_roc alongside vix_5d_roc."""
    n = 140
    aligned = {
        "VIX": np.full(n, 18.0),
        "VVIX": np.linspace(80.0, 100.0, n),  # rising 25% over the window
        "SPY": np.full(n, 500.0),
        "COR1M": np.full(n, 30.0),
    }
    common_dates = [f"2024-01-{i:02d}" for i in range(1, n + 1)]
    payload = run_analysis(aligned, common_dates)
    assert "vvix_5d_roc" in payload
    # last 5 sessions: VVIX moves from ~99.3 to ~100 → ~0.7% RoC
    assert 0.0 < payload["vvix_5d_roc"] < 2.0
```

- [ ] **Step 2: Run test, confirm it fails**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py::test_run_analysis_exposes_vvix_5d_roc -v
```
Expected: FAIL with `KeyError: 'vvix_5d_roc'` or `assert "vvix_5d_roc" in payload`.

- [ ] **Step 3: Add VVIX RoC computation in `run_analysis`**

Open `src/uw_scan/cards/cri_scoring.py`. Find the line that computes `vix_5d_roc` (around line 262–266 in the current file):

```python
    # VIX 5-day RoC (%)
    if len(vix) >= 6 and vix[-6] > 0:
        vix_5d_roc = (vix[-1] / vix[-6] - 1) * 100
    else:
        vix_5d_roc = 0.0
```

Immediately below it, add the VVIX RoC block (mirrors the VIX one):

```python
    # VVIX 5-day RoC (%) — leading indicator of tail-hedging demand
    if len(vvix) >= 6 and vvix[-6] > 0:
        vvix_5d_roc = (vvix[-1] / vvix[-6] - 1) * 100
    else:
        vvix_5d_roc = 0.0
```

Then in the `return` dict at the end of `run_analysis`, add the new field alongside `vix_5d_roc` (around line 342):

```python
        "vix_5d_roc": round(float(vix_5d_roc), 1),
        "vvix_5d_roc": round(float(vvix_5d_roc), 1),
```

- [ ] **Step 4: Also expose vvix_5d_roc and cor1m_5d_change per-row in the history list**

In `run_analysis`, find the per-day history loop (around line 314–335). Add per-day VVIX RoC and COR1M 5d-change computations inside the loop, mirroring `day_vix_roc`:

```python
        if i >= 5 and vvix[i - 5] > 0:
            day_vvix_roc = (vvix[i] / vvix[i - 5] - 1) * 100
        else:
            day_vvix_roc = 0.0
        if i >= 5 and not math.isnan(float(cor1m_values[i - 5])):
            day_cor1m_5d_chg = float(cor1m_values[i]) - float(cor1m_values[i - 5])
        else:
            day_cor1m_5d_chg = 0.0
```

And add both to the `history.append({...})` dict:

```python
                "vix_5d_roc": round(float(day_vix_roc), 1),
                "vvix_5d_roc": round(float(day_vvix_roc), 1),
                "cor1m_5d_change": round(float(day_cor1m_5d_chg), 2),
```

(The per-row `cor1m_5d_change` lets the UI's `priorComponentScore` helper correctly reproduce the correlation **spike** sub-score — without it, the prior-day dot under-estimates on COR1M spike days.)

- [ ] **Step 5: Run test, confirm it passes**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py::test_run_analysis_exposes_vvix_5d_roc -v
```
Expected: PASS.

- [ ] **Step 6: Run full file to check no regression**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py -v
```
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/cards/cri_scoring.py tests/unit/test_cri_scoring.py
git commit -m "feat(cri): expose vvix_5d_roc in payload + history"
```

---

### Task 3: Rebalance `score_vvix_component` — new floor/ceiling + RoC sub-score

**Files:**
- Modify: `src/uw_scan/cards/cri_scoring.py:89-95` (`score_vvix_component`)
- Modify: `src/uw_scan/cards/cri_scoring.py:133-159` (`compute_cri` to pass RoC through)
- Modify: `src/uw_scan/cards/cri_scoring.py:280+` (`run_analysis` call into `compute_cri`)
- Test: `tests/unit/test_cri_scoring.py`

- [ ] **Step 1: Write failing tests for the new signature and bounds**

Update the existing VVIX tests in `tests/unit/test_cri_scoring.py`. The current `test_score_vvix_zero_at_baseline` and `test_score_vvix_max_at_extreme` use the old 2-arg signature — replace them and add RoC-specific tests.

Find:
```python
def test_score_vvix_zero_at_baseline() -> None:
    assert score_vvix_component(90.0, 5.0) == pytest.approx(0.0)


def test_score_vvix_max_at_extreme() -> None:
    # VVIX 140 → level 17; ratio 8 → ratio 8; total 25
    assert score_vvix_component(140.0, 8.0) == pytest.approx(25.0)
```

Replace with:
```python
def test_score_vvix_zero_at_baseline() -> None:
    # VVIX 85, ratio 5.0, RoC 0 → all sub-scores 0
    assert score_vvix_component(85.0, 5.0, 0.0) == pytest.approx(0.0)


def test_score_vvix_max_at_extreme() -> None:
    # VVIX 130 → level 12; ratio 8 → ratio 7; RoC 25 → roc 6; total 25
    assert score_vvix_component(130.0, 8.0, 25.0) == pytest.approx(25.0)
    assert score_vvix_component(200.0, 10.0, 50.0) == pytest.approx(25.0)


def test_score_vvix_level_only() -> None:
    # VVIX 110, ratio 5.0, RoC 0 → level only
    # (110-85)/45 * 12 = 25/45 * 12 = 6.67
    assert score_vvix_component(110.0, 5.0, 0.0) == pytest.approx(6.67, abs=0.01)


def test_score_vvix_roc_only() -> None:
    # VVIX 85, ratio 5.0, RoC 12.5 → roc only
    # 12.5/25 * 6 = 3.0
    assert score_vvix_component(85.0, 5.0, 12.5) == pytest.approx(3.0, abs=0.01)


def test_score_vvix_roc_one_sided() -> None:
    # Negative RoC should not add (or subtract) any points
    assert score_vvix_component(85.0, 5.0, -50.0) == pytest.approx(0.0)


def test_score_vvix_nan_inputs() -> None:
    assert score_vvix_component(float("nan"), 5.0, 0.0) == 0.0
    assert score_vvix_component(95.0, float("nan"), 0.0) == 0.0
    # NaN RoC should be treated as 0, not zero-out the whole score
    assert score_vvix_component(110.0, 5.0, float("nan")) == pytest.approx(6.67, abs=0.01)
```

- [ ] **Step 2: Run tests, confirm they fail**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py -k vvix -v
```
Expected: FAILs (signature mismatch — old func takes 2 args, tests pass 3).

- [ ] **Step 3: Rewrite `score_vvix_component`**

Open `src/uw_scan/cards/cri_scoring.py`. Find:

```python
def score_vvix_component(vvix: float, vvix_vix_ratio: float) -> float:
    """Score VVIX component (0-25)."""
    if math.isnan(vvix) or math.isnan(vvix_vix_ratio):
        return 0.0
    level_score = np.clip((vvix - 90.0) / (140.0 - 90.0) * 17.0, 0.0, 17.0)
    ratio_score = np.clip((vvix_vix_ratio - 5.0) / (8.0 - 5.0) * 8.0, 0.0, 8.0)
    return float(np.clip(level_score + ratio_score, 0.0, 25.0))
```

Replace with:

```python
def score_vvix_component(
    vvix: float, vvix_vix_ratio: float, vvix_5d_roc: float
) -> float:
    """Score VVIX component (0-25).

    Three sub-scores; see docs/research/regime/cri-methodology.md §3 for rationale.
      - level  (0-12): VVIX absolute level, clipped 85→130
      - ratio  (0-7):  VVIX/VIX ratio, clipped 5→8 (practitioner warning band)
      - roc    (0-6):  VVIX 5d rate-of-change, one-sided, clipped 0→25%

    NaN policy: missing VVIX or ratio collapses the whole score to 0
    (calibration assumes both are present). NaN RoC is treated as 0 — it's
    an enhancement, not a gate.
    """
    if math.isnan(vvix) or math.isnan(vvix_vix_ratio):
        return 0.0
    if math.isnan(vvix_5d_roc):
        vvix_5d_roc = 0.0
    level_score = np.clip((vvix - 85.0) / (130.0 - 85.0) * 12.0, 0.0, 12.0)
    ratio_score = np.clip((vvix_vix_ratio - 5.0) / (8.0 - 5.0) * 7.0, 0.0, 7.0)
    roc_score = np.clip(max(vvix_5d_roc, 0.0) / 25.0 * 6.0, 0.0, 6.0)
    return float(np.clip(level_score + ratio_score + roc_score, 0.0, 25.0))
```

- [ ] **Step 4: Update `compute_cri` to plumb RoC through**

Find:

```python
def compute_cri(
    vix: float,
    vix_5d_roc: float,
    vvix: float,
    vvix_vix_ratio: float,
    corr: float,
    corr_5d_change: float,
    spx_distance_pct: float,
) -> dict[str, Any]:
```

Add `vvix_5d_roc` after `vvix_vix_ratio`:

```python
def compute_cri(
    vix: float,
    vix_5d_roc: float,
    vvix: float,
    vvix_vix_ratio: float,
    vvix_5d_roc: float,
    corr: float,
    corr_5d_change: float,
    spx_distance_pct: float,
) -> dict[str, Any]:
```

And update the call inside:

```python
    vvix_score = score_vvix_component(vvix, vvix_vix_ratio, vvix_5d_roc)
```

- [ ] **Step 5: Update `run_analysis` to pass the new arg**

In `run_analysis`, find the `compute_cri(...)` call (around line 287). Add `vvix_5d_roc=float(vvix_5d_roc)` after `vvix_vix_ratio`:

```python
    cri = compute_cri(
        vix=vix_now,
        vix_5d_roc=float(vix_5d_roc),
        vvix=vvix_now,
        vvix_vix_ratio=float(vvix_vix_ratio),
        vvix_5d_roc=float(vvix_5d_roc),
        corr=cor1m_now,
        corr_5d_change=cor1m_5d_change,
        spx_distance_pct=float(spx_distance_pct),
    )
```

- [ ] **Step 6: Update existing `compute_cri` tests**

Find existing compute_cri tests in `tests/unit/test_cri_scoring.py` (search for `compute_cri(`). They pass positional args missing `vvix_5d_roc`. Add `0.0` (or whatever's appropriate) in the new slot.

For example, if the test looks like:

```python
def test_compute_cri_calm_market() -> None:
    result = compute_cri(
        vix=15.0, vix_5d_roc=0.0,
        vvix=90.0, vvix_vix_ratio=5.0,
        corr=25.0, corr_5d_change=0.0,
        spx_distance_pct=5.0,
    )
    assert result["score"] == 0.0
```

Update to:

```python
def test_compute_cri_calm_market() -> None:
    result = compute_cri(
        vix=15.0, vix_5d_roc=0.0,
        vvix=85.0, vvix_vix_ratio=5.0, vvix_5d_roc=0.0,
        corr=25.0, corr_5d_change=0.0,
        spx_distance_pct=5.0,
    )
    assert result["score"] == 0.0
```

Note the VVIX baseline shifted from 90 → 85 to match the new floor.

- [ ] **Step 7: Run all VVIX + compute_cri tests, confirm they pass**

Run:
```bash
uv run pytest tests/unit/test_cri_scoring.py -v
```
Expected: all PASS.

- [ ] **Step 8: Spot-check with today's actual values**

Run a Python REPL via uv:
```bash
uv run python -c "
from uw_scan.cards.cri_scoring import score_vvix_component
# Today's values: VVIX 92.94, ratio 5.04
# Old score: 1.11/25
# Expected new score: level=(92.94-85)/45*12 = 2.12; ratio=(5.04-5)/3*7 = 0.09; roc unknown — pass 0
print('VVIX score (RoC=0):', score_vvix_component(92.94, 5.04, 0.0))
print('VVIX score (RoC=10):', score_vvix_component(92.94, 5.04, 10.0))
"
```
Expected output:
```
VVIX score (RoC=0): ~2.2
VVIX score (RoC=10): ~4.6
```

(Up from 1.1 today — modest but meaningful gain in normal regime gradation.)

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/cards/cri_scoring.py tests/unit/test_cri_scoring.py
git commit -m "feat(cri): rebalance VVIX scoring — lower floor + RoC sub-score"
```

---

### Task 4: Extend Pydantic models for the new field

**Files:**
- Modify: `src/uw_scan/api/schemas.py:396-417` (`CriResponse`)
- Modify: `src/uw_scan/api/schemas.py:385-393` (`CriHistoryEntry`)

- [ ] **Step 1: Add `vvix_5d_roc` to `CriResponse`**

Open `src/uw_scan/api/schemas.py`. Find the `CriResponse` class. Below the `vix_5d_roc` line, add:

```python
    vvix_5d_roc: float | None = None
```

- [ ] **Step 2: Add `vvix_5d_roc` and `cor1m_5d_change` to `CriHistoryEntry`**

In the same file, find `CriHistoryEntry`. Below `vix_5d_roc`, add both fields:

```python
    vvix_5d_roc: float | None = None
    cor1m_5d_change: float | None = None
```

`cor1m_5d_change` enables the UI's prior-day dot for the Correlation bar to include the spike sub-score (otherwise the dot under-estimates on COR1M spike days; see Task 5 `priorComponentScore`).

- [ ] **Step 3: Run the OpenAPI snapshot test — it will fail (expected)**

Run:
```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: FAIL with a diff in `components.schemas.CriResponse` and `CriHistoryEntry` showing the new `vvix_5d_roc` property. This is the contract guard at `tests/integration/api/test_openapi_snapshot.py` — adding API fields is intentional, so the snapshot needs to be regenerated.

- [ ] **Step 4: Regenerate the snapshot**

The snapshot file is JSON at `tests/integration/api/openapi.snapshot.json`. There is no `--update-snapshots` flag (this is a hand-rolled snapshot test, not pytest-snapshot). Regenerate it by:

```bash
uv run python -c "
import json
from pathlib import Path
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app

app = create_app()
client = TestClient(app)
spec = client.get('/openapi.json').json()
Path('tests/integration/api/openapi.snapshot.json').write_text(json.dumps(spec, indent=2, sort_keys=True))
print('snapshot regenerated')
"
```

If `create_app` is named differently in `src/uw_scan/api/server.py`, grep for `FastAPI(` and use the right factory name. As a fallback, hit a running API directly:

```bash
curl -s http://localhost:8400/openapi.json | python -m json.tool --sort-keys > tests/integration/api/openapi.snapshot.json
```

- [ ] **Step 5: Re-run the snapshot test to confirm it now passes**

Run:
```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: PASS.

- [ ] **Step 6: Add scanner integration assertions for the new payload fields**

The existing assertions in `tests/integration/test_cri_scanner.py` only check legacy fields like `latest["vix"]`. Add explicit assertions that the new fields appear at the top level and per-row in `history`. Near the end of the existing test function (or as a new test in the same file), add:

```python
def test_cri_scanner_emits_new_payload_fields(populated_repo) -> None:
    """vvix_5d_roc and cor1m_5d_change must appear in the persisted snapshot
    so the UI can compute prior-day component dots without falling back to 0."""
    # Reuse the existing fixture pattern in this file — populated_repo or whatever
    # fixture name the existing test_cri_scanner_persists_snapshot uses.
    snap = fetch_latest_snapshot(populated_repo)  # use the file's existing helper
    assert "vvix_5d_roc" in snap, "top-level vvix_5d_roc missing"
    assert snap["history"], "history is empty — fixture broke"
    last_history = snap["history"][-1]
    assert "vvix_5d_roc" in last_history, "per-row vvix_5d_roc missing"
    assert "cor1m_5d_change" in last_history, "per-row cor1m_5d_change missing"
```

If `fetch_latest_snapshot` and `populated_repo` aren't the actual names in this file, mirror whatever the existing tests use (read `tests/integration/test_cri_scanner.py:1-80` first to align). The point: assert presence of the new fields, not specific values — values change with calibration.

- [ ] **Step 7: Run the CRI scanner integration test**

```bash
uv run pytest tests/integration/test_cri_scanner.py -v
```
Expected: PASS, including the new test.

- [ ] **Step 8: Regenerate `web/lib/types.ts` NOW (before UI work in Phase 3)**

The UI helper in Task 5 references `prior.vvix_5d_roc` and `prior.cor1m_5d_change`. If we wait until after the UI commit to regenerate types, TypeScript compilation breaks in between. Regenerate now:

```bash
# Start the API in the background just for type generation
uv run uvicorn uw_scan.api.server:app --port 8400 &
_API_PID=$!
sleep 2
curl -sf http://127.0.0.1:8400/openapi.json > /dev/null && echo "API up"

cd web && npm run gen:types && cd ..

# Verify the new fields appear
grep -E "vvix_5d_roc|cor1m_5d_change" web/lib/types.ts | head -10

# Stop the API
kill $_API_PID 2>/dev/null
```

Expected: both `vvix_5d_roc?: number | null;` and `cor1m_5d_change?: number | null;` show up in the `CriResponse` and `CriHistoryEntry` shapes.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/api/schemas.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(cri): add vvix_5d_roc + cor1m_5d_change to API contract"
```

---

## Phase 3: UI (TypeScript)

Types were already regenerated in Phase 2 Task 4 Step 8, so `web/lib/types.ts` is current. If you skipped that step, do it before proceeding — the UI helper depends on the new fields being typed.

### Task 5: Add reference markers to `ComponentBar`

**Files:**
- Modify: `web/components/regime/CriSubTab.tsx:68-101` (`ComponentBar`)

- [ ] **Step 1: Define the reference data**

Open `web/components/regime/CriSubTab.tsx`. Below the `COMPONENT_TOOLTIPS` constant (around line 22–29), add:

```tsx
// Reference markers per component. Values are in *score units* (0–25 scale).
// Keyed by the JSON component slot (matches cri.components keys), NOT the
// display label — so renaming MOMENTUM → TREND BREAK in Task 6 doesn't
// silently break the lookup.
// Source: docs/research/regime/cri-methodology.md §6
type ComponentSlot = "vix" | "vvix" | "correlation" | "momentum";
const COMPONENT_REFERENCES: Record<
  ComponentSlot,
  { mid: { score: number; label: string } }
> = {
  vix: { mid: { score: 5.0, label: "VIX 23" } },
  vvix: { mid: { score: 6.7, label: "VVIX 110" } },
  correlation: { mid: { score: 13.0, label: "COR1M 60" } },
  momentum: { mid: { score: 7.5, label: "-3% MA" } },
};
```

- [ ] **Step 2: Update `ComponentBar` signature**

Find the existing component (around line 68):

```tsx
function ComponentBar({
  label,
  score,
  live,
}: {
  label: string;
  score: number;
  live: boolean;
}) {
```

Replace with:

```tsx
function ComponentBar({
  label,
  slot,
  score,
  priorScore,
  live,
}: {
  label: string;
  slot: ComponentSlot;
  score: number;
  priorScore?: number | null;
  live: boolean;
}) {
```

The new `slot` prop decouples the reference lookup from the display label so the rename in Task 6 is safe.

- [ ] **Step 3: Render the markers**

Inside `ComponentBar`, replace the existing track div with the new version that includes inline `position: relative` (the existing CSS at `web/app/globals.css:5059` does NOT set position, so the absolutely-positioned markers need an explicit relative ancestor) and the marker + prior-dot overlays:

```tsx
      <div className="regime-bar-track" style={{ position: "relative" }}>
        <div
          className="regime-bar-fill"
          style={{ width: `${pct}%`, background: barColor }}
        />
        {(() => {
          const ref = COMPONENT_REFERENCES[slot];
          if (!ref) return null;
          const midPct = (ref.mid.score / 25) * 100;
          return (
            <div
              className="regime-bar-tick"
              style={{
                position: "absolute",
                left: `${midPct}%`,
                top: 0,
                bottom: 0,
                width: 1,
                background: "var(--text-muted)",
                opacity: 0.5,
              }}
              title={ref.mid.label}
            />
          );
        })()}
        {priorScore != null && Number.isFinite(priorScore) ? (
          <div
            className="regime-bar-prior"
            style={{
              position: "absolute",
              left: `${(Math.max(0, Math.min(25, priorScore)) / 25) * 100}%`,
              top: "50%",
              transform: "translate(-50%, -50%)",
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--text-primary)",
              opacity: 0.7,
            }}
            title={`Prior: ${priorScore.toFixed(1)}`}
          />
        ) : null}
      </div>
```

The `Math.max(0, Math.min(25, priorScore))` clamps the dot inside the track even if a future scoring change accidentally produces an out-of-band value.

- [ ] **Step 4: Wire `priorScore` from history**

Find where `ComponentBar` is invoked in `CriSubTab.tsx` (search for `<ComponentBar`). Each call site passes `label={"VIX"}`, etc. Update to also pass `priorScore`. The prior score values live in `data.history[history.length - 2]` — but the history doesn't store component sub-scores. We have two options:

**Option A (cheap, presented here):** compute prior-day component scores client-side from the history entry's raw values. Add a helper near the top of the file:

```tsx
function priorComponentScore(
  prior: CriHistoryEntry | undefined,
  slot: ComponentSlot,
): number | null {
  if (!prior) return null;
  // Mirror the Python scoring math; floors/ceilings must match cri-methodology.md §3.
  // If any required input is null/missing, return null (don't draw a misleading dot).
  const clip = (x: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, x));
  const round1 = (x: number) => Math.round(x * 10) / 10;
  if (slot === "vix") {
    if (prior.vix == null || prior.vix_5d_roc == null) return null;
    const lvl = clip(((prior.vix - 15) / 25) * 15, 0, 15);
    const roc = clip((Math.max(prior.vix_5d_roc, 0) / 60) * 10, 0, 10);
    return round1(lvl + roc);
  }
  if (slot === "vvix") {
    if (prior.vvix == null || prior.vix == null || prior.vix <= 0) return null;
    const ratio = prior.vvix / prior.vix;
    const lvl = clip(((prior.vvix - 85) / 45) * 12, 0, 12);
    const r = clip(((ratio - 5) / 3) * 7, 0, 7);
    // vvix_5d_roc was added in this PR — older history entries won't have it.
    // Treat absence as 0 (level + ratio are still meaningful by themselves).
    const rocRaw = prior.vvix_5d_roc ?? 0;
    const roc = clip((Math.max(rocRaw, 0) / 25) * 6, 0, 6);
    return round1(lvl + r + roc);
  }
  if (slot === "correlation") {
    if (prior.cor1m == null) return null;
    const lvl = clip(((prior.cor1m - 25) / 45) * 17, 0, 17);
    // cor1m_5d_change was added in this PR — older history entries fall back to 0
    const chg = prior.cor1m_5d_change ?? 0;
    const spike = clip((Math.max(chg, 0) / 20) * 8, 0, 8);
    return round1(lvl + spike);
  }
  if (slot === "momentum") {
    if (prior.spx_vs_ma_pct == null) return null;
    const d = prior.spx_vs_ma_pct;
    if (d >= 0) return 0;
    return round1((Math.min(Math.abs(d), 10) / 10) * 25);
  }
  return null;
}
```

At each `<ComponentBar>` call, add the `slot` and `priorScore` props (keep the existing `label` as "MOMENTUM" for now — Task 6 changes it):

```tsx
<ComponentBar
  label="VIX"
  slot="vix"
  score={cri.components.vix}
  priorScore={priorComponentScore(priorHistory, "vix")}
  live={live}
/>
<ComponentBar
  label="VVIX"
  slot="vvix"
  score={cri.components.vvix}
  priorScore={priorComponentScore(priorHistory, "vvix")}
  live={live}
/>
<ComponentBar
  label="CORRELATION"
  slot="correlation"
  score={cri.components.correlation}
  priorScore={priorComponentScore(priorHistory, "correlation")}
  live={live}
/>
<ComponentBar
  label="MOMENTUM"
  slot="momentum"
  score={cri.components.momentum}
  priorScore={priorComponentScore(priorHistory, "momentum")}
  live={live}
/>
```

Where `priorHistory` is `data.history?.[data.history.length - 2]` (compute once near the top of the parent component).

- [ ] **Step 5: Run vitest**

Run:
```bash
cd web && npm run test -- regime-page
```
Expected: existing tests still PASS. (Some may need updating for the new structure — fix inline if needed.)

- [ ] **Step 6: Commit**

```bash
git add web/components/regime/CriSubTab.tsx
git commit -m "feat(regime): add reference markers + prior-day dot to CRI component bars"
```

---

### Task 6: Rename "Momentum" → "TREND BREAK" + fix tooltip

**Files:**
- Modify: `web/components/regime/CriSubTab.tsx` (label + tooltip text)

- [ ] **Step 1: Update the tooltip text**

In `web/components/regime/CriSubTab.tsx`, find `COMPONENT_TOOLTIPS` (around line 22):

```tsx
const COMPONENT_TOOLTIPS: Record<string, string> = {
  VIX: "...",
  VVIX: "...",
  CORRELATION: "...",
  MOMENTUM:
    "SPX distance below 100-day MA combined with VIX 5-day rate of change. Captures trend stress + vol acceleration.",
};
```

Replace the MOMENTUM entry with:

```tsx
  "TREND BREAK":
    "SPX distance below the 100-day MA. One-sided: scores 0 when SPX is at or above the MA; saturates at -10% below. Designed to fire only on confirmed downtrends, not parabolic uptrends.",
```

- [ ] **Step 2: Update the VVIX tooltip too (drift from new RoC sub-score)**

In the same `COMPONENT_TOOLTIPS`, replace the VVIX entry with:

```tsx
  VVIX: "Vol-of-VIX — expected volatility of VIX itself. Three sub-scores: absolute level (85→130), VVIX/VIX ratio (5→8 = practitioner warning band), and 5-day rate-of-change (rising VVIX vs flat VIX is the canonical lead signal of tail-hedging demand).",
```

- [ ] **Step 3: Update the component label at the call site**

Find the `<ComponentBar label="MOMENTUM" ... />` call set up in Task 5. Change just the `label` string:

```tsx
<ComponentBar
  label="TREND BREAK"
  slot="momentum"
  score={cri.components.momentum}
  priorScore={priorComponentScore(priorHistory, "momentum")}
  live={live}
/>
```

The JSON `cri.components.momentum` key and the `slot="momentum"` lookup key both stay stable — only the user-facing label rotates. This means `COMPONENT_REFERENCES` (keyed by slot) and `priorComponentScore` (slot-typed) both keep working without changes.

- [ ] **Step 4: Update SECTION_TOOLTIPS to match**

In the same file, find `SECTION_TOOLTIPS["CRI COMPONENTS"]`:

```tsx
"CRI COMPONENTS":
    "Crash Risk Index broken into 4 sub-scores (0-25 each, 100 total). VIX/VVIX measure implied vol stress. Correlation tracks COR1M herding. Momentum captures SPX trend breakdown.",
```

Replace with:

```tsx
"CRI COMPONENTS":
    "Crash Risk Index broken into 4 sub-scores (0-25 each, 100 total). VIX/VVIX measure implied vol stress. Correlation tracks COR1M herding. Trend Break fires when SPX trades below its 100-day MA. See docs/research/regime/cri-methodology.md for calibration details.",
```

- [ ] **Step 5: Update the existing CriSubTab test that asserts "MOMENTUM"**

Open `web/tests/unit/CriSubTab.test.tsx`. Find the assertion (around line 137):

```tsx
expect(screen.getByText("MOMENTUM")).not.toBeNull();
```

Replace with:

```tsx
expect(screen.getByText("TREND BREAK")).not.toBeNull();
```

Also update the test description on the surrounding `it(...)` block from `"renders all four component bars (VIX/VVIX/CORRELATION/MOMENTUM)"` to `"renders all four component bars (VIX/VVIX/CORRELATION/TREND BREAK)"` so it doesn't lie.

- [ ] **Step 6: Add a marker-rendering smoke test**

In the same `CriSubTab.test.tsx`, add a new test that confirms a reference tick renders on at least one component bar:

```tsx
it("renders reference tick marks on component bars", () => {
  const { container } = render(<CriSubTabView data={POPULATED} />);
  // Each ComponentBar has a .regime-bar-tick child via the new inline marker
  const ticks = container.querySelectorAll(".regime-bar-tick");
  // We render 4 component bars; each gets exactly one mid-mark tick
  expect(ticks.length).toBe(4);
});
```

(If the existing test file imports `render` from `@testing-library/react`, no new import is needed; otherwise add it.)

- [ ] **Step 7: Run vitest**

```bash
cd web && npm run test
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/components/regime/CriSubTab.tsx web/tests/unit/CriSubTab.test.tsx
git commit -m "feat(regime): rename Momentum→Trend Break, fix tooltip drift"
```

---

## Phase 4: Post-UI typecheck

### Task 7: Final TypeScript + lint pass

Types were regenerated in Phase 2 Task 4 Step 8. Now verify the UI work in Phase 3 is type-clean.

**Files:**
- None (verification only)

- [ ] **Step 1: TypeScript check**

```bash
cd web && npm run typecheck
```
Expected: PASS. If a new `CriHistoryEntry` binding complains about an unknown property, fix it where it binds (don't loosen the type).

- [ ] **Step 2: Lint**

```bash
cd web && npm run lint
```
Expected: PASS.

- [ ] **Step 3: Vitest full pass**

```bash
cd web && npm run test
```
Expected: PASS. Tasks 5–6 update component tests; if anything failed, fix the test, not the production code.

---

## Phase 5: Backtest validation

### Task 8: Build the standalone backtest script

**Files:**
- Create: `scripts/backtest_cri.py`
- Test: `tests/unit/test_backtest_cri.py`

- [ ] **Step 1: Write a smoke test for the script's pure components**

Create `tests/unit/test_backtest_cri.py`:

```python
"""Smoke tests for scripts/backtest_cri.py — pure-function helpers only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


def _load_backtest_module():
    """Load scripts/backtest_cri.py as a module without invoking main()."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "backtest_cri.py"
    spec = importlib.util.spec_from_file_location("backtest_cri", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compute_cri_for_window_returns_score() -> None:
    bt = _load_backtest_module()
    # Synthetic 150-day calm window
    n = 150
    aligned = {
        "VIX": np.full(n, 14.0),
        "VVIX": np.full(n, 80.0),
        "SPY": np.linspace(400.0, 450.0, n),  # gently rising
        "COR1M": np.full(n, 20.0),
    }
    common_dates = [f"2020-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    payload = bt.compute_cri_for_window(aligned, common_dates)
    assert "cri" in payload
    assert 0 <= payload["cri"]["score"] <= 100
    # Calm regime: should be very low
    assert payload["cri"]["score"] < 10


def test_summarize_distribution_has_required_keys() -> None:
    bt = _load_backtest_module()
    scores = [0.5, 1.0, 4.0, 12.0, 25.0, 50.0, 75.0, 90.0]
    summary = bt.summarize_distribution(scores)
    for key in ("mean", "p25", "p50", "p75", "p90", "p95", "level_counts"):
        assert key in summary
    # Band boundaries: LOW < 25, ELEVATED < 50, HIGH < 75, CRITICAL >= 75
    # 0.5, 1.0, 4.0, 12.0 → LOW (4)
    # 25.0 → ELEVATED (1)
    # 50.0 → HIGH (1)
    # 75.0, 90.0 → CRITICAL (2)
    assert summary["level_counts"]["LOW"] == 4
    assert summary["level_counts"]["ELEVATED"] == 1
    assert summary["level_counts"]["HIGH"] == 1
    assert summary["level_counts"]["CRITICAL"] == 2
```

- [ ] **Step 2: Run test, confirm it fails (script doesn't exist yet)**

Run:
```bash
uv run pytest tests/unit/test_backtest_cri.py -v
```
Expected: FAIL with `FileNotFoundError` or `ModuleNotFoundError`.

- [ ] **Step 3: Write `scripts/backtest_cri.py`**

Create `scripts/backtest_cri.py`:

```python
#!/usr/bin/env python3
"""Backtest CRI across the full available history.

Reads:
  - vol_index_daily for VIX, VVIX, COR1M
  - daily_ohlc for SPY

Recomputes CRI for every aligned trading day. Writes:
  - docs/research/regime/cri-backtest-2006-2026.csv (one row per day)
  - docs/research/regime/cri-backtest-2006-2026.md (summary report)

Usage:
  uv run python scripts/backtest_cri.py
  uv run python scripts/backtest_cri.py --start 2006-01-01 --end 2026-05-15
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

# Allow running without `uv pip install -e .` by adding src to the path.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import cri_scoring  # noqa: E402
from uw_scan.config import Settings  # noqa: E402

log = logging.getLogger("backtest_cri")

NAMED_CRASH_DATES = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}


def fetch_aligned_series(
    conn: psycopg.Connection, schema: str, start: _date, end: _date
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch and align all four series on shared dates."""
    series: dict[str, dict[_date, float]] = {}
    with conn.cursor() as cur:
        for sym in ("VIX", "VVIX", "COR1M"):
            cur.execute(
                f"SELECT trade_date, close FROM {schema}.vol_index_daily "
                "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY trade_date",
                (sym, start, end),
            )
            series[sym] = {r[0]: float(r[1]) for r in cur.fetchall()}

        cur.execute(
            f"SELECT date, close FROM {schema}.daily_ohlc "
            "WHERE ticker = 'SPY' AND date BETWEEN %s AND %s "
            "AND close IS NOT NULL ORDER BY date",
            (start, end),
        )
        series["SPY"] = {r[0]: float(r[1]) for r in cur.fetchall()}

    common = set(series["VIX"].keys())
    for sym in ("VVIX", "COR1M", "SPY"):
        common &= set(series[sym].keys())
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in series
    }
    return aligned, [d.isoformat() for d in sorted_dates]


def compute_cri_for_window(
    aligned: dict[str, np.ndarray], common_dates: list[str]
) -> dict[str, Any]:
    """Pure passthrough to cri_scoring.run_analysis (kept here for testability)."""
    return cri_scoring.run_analysis(aligned, common_dates)


def rolling_compute(
    aligned: dict[str, np.ndarray], common_dates: list[str], window: int = 150
) -> list[dict[str, Any]]:
    """Slide a `window`-day lookback over the full history, computing CRI per day.

    Returns a list of {date, score, level, vix_c, vvix_c, corr_c, trend_c, fired}.
    """
    out: list[dict[str, Any]] = []
    n = len(common_dates)
    for i in range(window, n):
        win_aligned = {sym: arr[i - window : i + 1] for sym, arr in aligned.items()}
        win_dates = common_dates[i - window : i + 1]
        try:
            p = cri_scoring.run_analysis(win_aligned, win_dates)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("backtest day %s skipped: %s", common_dates[i], repr(exc))
            continue
        cri = p["cri"]
        out.append(
            {
                "date": common_dates[i],
                "score": cri["score"],
                "level": cri["level"],
                "vix_c": cri["components"]["vix"],
                "vvix_c": cri["components"]["vvix"],
                "corr_c": cri["components"]["correlation"],
                "trend_c": cri["components"]["momentum"],
                "fired": p["crash_trigger"]["fired"],
                "vix": p["vix"],
                "vvix": p["vvix"],
                "cor1m": p["cor1m"],
                "spx_distance_pct": p["spx_distance_pct"],
            }
        )
    return out


def summarize_distribution(scores: list[float]) -> dict[str, Any]:
    arr = np.array(scores, dtype=float)
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "level_counts": dict(
            Counter([cri_scoring.cri_level(s) for s in scores])
        ),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log.info("wrote %d rows to %s", len(rows), path)


def write_report(rows: list[dict[str, Any]], path: Path) -> None:
    summary = summarize_distribution([r["score"] for r in rows])
    named_hits = []
    by_date = {r["date"]: r for r in rows}
    for d, name in NAMED_CRASH_DATES.items():
        if d in by_date:
            r = by_date[d]
            named_hits.append((d, name, r["score"], r["level"], r["fired"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("# CRI Backtest — 2006-2026\n\n")
        f.write(
            "Generated by `scripts/backtest_cri.py`. Re-run after any calibration change.\n\n"
        )
        f.write(f"**N days:** {summary['n']}  \n")
        f.write(f"**Date range:** {rows[0]['date']} → {rows[-1]['date']}\n\n")
        f.write("## Score distribution\n\n")
        f.write("| Stat | Value |\n|---|---|\n")
        for k in ("mean", "min", "p25", "p50", "p75", "p90", "p95", "p99", "max"):
            f.write(f"| {k} | {summary[k]:.2f} |\n")
        f.write("\n## Level distribution\n\n")
        f.write("| Level | Count | % |\n|---|---|---|\n")
        total = summary["n"]
        for lvl in ("LOW", "ELEVATED", "HIGH", "CRITICAL"):
            count = summary["level_counts"].get(lvl, 0)
            f.write(f"| {lvl} | {count} | {count / total * 100:.1f}% |\n")
        f.write("\n## Named crash dates\n\n")
        f.write("| Date | Event | CRI score | Level | Trigger fired |\n")
        f.write("|---|---|---|---|---|\n")
        for d, name, score, level, fired in named_hits:
            f.write(f"| {d} | {name} | {score:.1f} | {level} | {fired} |\n")
        if not named_hits:
            f.write("| _no aligned data for any named date_ | | | | |\n")
    log.info("wrote report to %s", path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2006-01-01")
    p.add_argument("--end", default=_date.today().isoformat())
    p.add_argument("--out-csv", default="docs/research/regime/cri-backtest-2006-2026.csv")
    p.add_argument("--out-md", default="docs/research/regime/cri-backtest-2006-2026.md")
    args = p.parse_args()

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        aligned, dates = fetch_aligned_series(conn, settings.db_schema, start, end)
    log.info("aligned %d trading days", len(dates))

    # rolling_compute defaults to a 150-day window — guard against the case
    # where we have enough data for the MA+VOL minimum but not enough for the
    # rolling lookback, which would silently produce zero rows and crash
    # write_report on `rows[0]`.
    rolling_window = 150
    min_required = max(rolling_window + 1, cri_scoring.MA_WINDOW + cri_scoring.VOL_WINDOW)
    if len(dates) < min_required:
        log.error("not enough data: %d days, need at least %d", len(dates), min_required)
        return 1

    rows = rolling_compute(aligned, dates, window=rolling_window)
    if not rows:
        log.error("rolling_compute produced no rows — check window/data alignment")
        return 1
    write_csv(rows, _PROJECT_ROOT / args.out_csv)
    write_report(rows, _PROJECT_ROOT / args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Settings API used above:** `Settings.from_env()` returns a populated Settings; `settings.db_dsn()` (note: it's a method, not a property) builds the libpq-style DSN string; `settings.db_schema` is the schema attribute. Same pattern as `src/uw_scan/worker/scheduler.py:231`.

- [ ] **Step 4: Run the smoke test**

Run:
```bash
uv run pytest tests/unit/test_backtest_cri.py -v
```
Expected: PASS.

- [ ] **Step 5: Run the backtest against the real DB**

Run:
```bash
uv run python scripts/backtest_cri.py
```
Expected: writes `docs/research/regime/cri-backtest-2006-2026.{csv,md}`. Should complete in <60 s for ~5,000 days.

- [ ] **Step 6: Inspect the output**

Run:
```bash
head -80 docs/research/regime/cri-backtest-2006-2026.md
```

Manual sanity checks:
- Mean CRI in [3, 15]: most days should be calm or near-calm.
- LOW percentage > 70%: most days are uneventful by design.
- Named crash dates (2008-09-15, 2020-02-28, 2018-02-05) should show CRI ≥ 25 (ELEVATED) or higher.
- If 2020-03-16 shows score < 50, that's a real calibration finding — note it for a follow-up.

- [ ] **Step 7: Commit the script + the generated artifacts**

```bash
git add scripts/backtest_cri.py tests/unit/test_backtest_cri.py \
        docs/research/regime/cri-backtest-2006-2026.md \
        docs/research/regime/cri-backtest-2006-2026.csv
git commit -m "feat(cri): backtest script + 2006-2026 baseline report"
```

---

## Phase 6: End-to-end verification

### Task 9: Manual browser verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run the scheduler once to refresh today's CRI snapshot**

The CRI scanner has to run once with the new code to produce a snapshot using the new scoring. Easiest path: trigger via the API:

```bash
curl -X POST http://localhost:8400/api/regime/scan -H "Content-Type: application/json" -d '{"scanner": "cri"}'
```

Or run the scanner directly:

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.scanners.cri import run

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    rid = run(conn, schema=s.db_schema)
    print('row_id:', rid)
"
```

- [ ] **Step 2: Open the regime page in the browser**

Navigate to `http://localhost:3001/regime`.

- [ ] **Step 3: Verify the new UI elements**

Check:
- The fourth component bar is labeled "TREND BREAK" (not "MOMENTUM").
- Each component bar has a thin vertical tick somewhere along the track (the reference marker).
- If there's prior-day history, a small dot appears on each bar at the previous day's score.
- VVIX score is meaningfully different from before (should be ~2.2 instead of 1.1 for the same input).
- Tooltips on each component label now reflect the new copy.

- [ ] **Step 4: Verify the composite score moved**

Today's expected score with new calibration (rough):
- VIX: ~3.3 (unchanged)
- VVIX: ~2.2 (up from 1.1)
- Correlation: ~0.3 (unchanged — COR1M too low to score)
- Trend Break: 0.0 (unchanged — SPX above MA)
- **Total: ~5.8/100** (up from 4.7)

The change is modest because today's market is genuinely calm; the meaningful difference is in mid-stress regimes that we'll see in the backtest report.

- [ ] **Step 5: Spot-check the backtest report against known events**

Open `docs/research/regime/cri-backtest-2006-2026.md`. Verify:
- 2008-09-15 (Lehman) shows ELEVATED or HIGH.
- 2020-03-16 (COVID circuit breaker) shows HIGH or CRITICAL.
- 2018-02-05 (volmageddon) shows ELEVATED at minimum.

If any of these underperforms, note it but **don't tune in this PR** — that's a follow-up methodology decision.

- [ ] **Step 6: Run the full test suite once more**

```bash
uv run pytest
cd web && npm run test
cd .. && cd web && npm run typecheck && npm run lint
```
Expected: all PASS.

---

## Phase 7: Open the PR

### Task 10: Open PR with a structured description

**Files:**
- None (git operations only)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/cri-methodology-tune
```

- [ ] **Step 2: Open PR via gh**

```bash
gh pr create --title "feat(cri): re-calibrate components, add VVIX RoC, rename Momentum, add backtest" --body "$(cat <<'EOF'
## Summary

Implements recommendations #1–#6 from the CRI methodology review (2026-05-19). Item #7 (VIX term structure + put/call ratio as new components) is deferred to a follow-up spec.

**Changes by phase:**

1. **Documentation:** `docs/research/regime/cri-methodology.md` is the new source of truth — math, calibration rationale, web research summary, design decisions, deferred items.
2. **VVIX scoring rebalance:** floor 90→85, ceiling 140→130, sub-scores rebalanced level(0-12) + ratio(0-7) + new RoC(0-6). Captures 'rising VVIX vs flat VIX' lead signal per practitioner consensus.
3. **Pydantic models:** added `vvix_5d_roc` to `CriResponse` and `CriHistoryEntry`. Additive change — no break in API contract.
4. **UI reference markers:** each `ComponentBar` now shows a mid-mark for the practitioner warning threshold (VIX 23, VVIX 110, COR1M 60, SPX -3% MA) plus a prior-day dot.
5. **Rename:** "MOMENTUM" → "TREND BREAK" in the UI. Payload JSON key `cri.components.momentum` stays stable so historical snapshots remain readable.
6. **Tooltip fixes:** VVIX and Trend Break tooltips no longer describe formulas that the code doesn't implement.
7. **Backtest:** `scripts/backtest_cri.py` recomputes CRI across 20y. Output checked in at `docs/research/regime/cri-backtest-2006-2026.{md,csv}`.

## Calibration impact (today's data)

| Component | Before | After | Notes |
|---|---|---|---|
| VIX | 3.3 | 3.3 | unchanged |
| VVIX | 1.1 | 2.2 | floor lowered + RoC sub-score |
| Correlation | 0.3 | 0.3 | unchanged (COR1M at p5 — genuinely benign) |
| Trend Break | 0.0 | 0.0 | unchanged (SPX above MA) |
| **Total** | **4.7** | **~5.8** | modest in this regime; meaningful in mid-stress |

## Test plan

- [ ] `uv run pytest tests/unit/test_cri_scoring.py` — pure-function tests, all green
- [ ] `uv run pytest tests/integration/test_cri_scanner.py` — scanner end-to-end with new payload fields
- [ ] `uv run pytest tests/unit/test_backtest_cri.py` — backtest helper smoke tests
- [ ] `uv run python scripts/backtest_cri.py` — generates committed artifacts
- [ ] `cd web && npm run typecheck && npm run lint && npm run test` — frontend clean
- [ ] Manual browser check on `/regime` — verify "TREND BREAK" label, reference markers, prior-day dot

## Deferred (separate spec)

- **Item #7:** Add VIX term structure (contango/backwardation) + put/call ratio as new CRI components. Requires new data sources and breaks the 4×25=100 architecture. Will write a separate spec.
- **Percentile-based scoring:** Replace fixed thresholds with rolling 5y percentiles. Defensible but changes interpretability — separate spec.
- **Revisit named-date hit-rates:** If the backtest report shows any named crash date underperforming, follow-up PR to tune that specific threshold.
EOF
)"
```

- [ ] **Step 3: Verify CI runs**

Watch for CI to complete. Address any failures inline before requesting review.

---

## Summary of deliverables

| Deliverable | Path |
|---|---|
| Methodology source of truth | `docs/research/regime/cri-methodology.md` |
| Subdir CLAUDE.md | `docs/research/regime/CLAUDE.md` |
| VVIX scoring rewrite | `src/uw_scan/cards/cri_scoring.py` |
| Pydantic model updates | `src/uw_scan/api/schemas.py` |
| Updated unit tests | `tests/unit/test_cri_scoring.py` |
| UI reference markers + label rename | `web/components/regime/CriSubTab.tsx` |
| Regenerated types | `web/lib/types.ts` |
| Backtest CLI | `scripts/backtest_cri.py` |
| Backtest tests | `tests/unit/test_backtest_cri.py` |
| Backtest output (committed) | `docs/research/regime/cri-backtest-2006-2026.{md,csv}` |
