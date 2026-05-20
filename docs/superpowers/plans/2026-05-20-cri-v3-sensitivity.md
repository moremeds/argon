# CRI v3 — Tactical Sensitivity + VIX Velocity Tile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise CRI sensitivity to tactical (2-4% / 3-day) drawdowns without breaking the composite's 4×25 contract, and surface VIX velocity as a new mean-reversion tile.

**Architecture:** Bump composite to **v3** with three calibration changes — (a) reshape Trend Break (`momentum`) into structural-break + tactical-pullback sub-scores, (b) lower VIX/VVIX level floors, (c) steepen VIX 5d RoC. Add `compute_pullback_20d` and `compute_vix_delta_3d` to `cards/mean_reversion.py`. UI gets a 4th tile and a 2-line readout under Trend Break. OOS backtest must keep dd5/dd10 AUC ≥ v1 before merge.

**Tech Stack:** Python 3.13 + numpy / pandas, FastAPI + Pydantic v2, psycopg 3, Next.js 16 + React 19, Vitest + Playwright, pytest.

**Branch:** Extend the open PR branch `feat/cri-methodology-tune` (PR #58). Do NOT spawn a sibling branch off main. (Mitigation for review-quality risk: Step 9.4 below rewrites the PR description into three labelled sections — v2 / v3-calibration / v3-tactical — with per-commit reading order so reviewers can binary-search a regression.)

**Expected today's CRI after recalibration:** ~13/100, level LOW (band cutoffs unchanged at 25/50/75). Composite version stored as `3`.

---

## Calibration deltas (locked)

| Lever | v1 / v2 | v3 |
|---|---|---|
| VIX level floor | 15 | **13** |
| VIX level ceiling | 40 | 40 (unchanged) |
| VIX 5d RoC denom | 60% | **40%** |
| VVIX level floor | 85 | **80** |
| VVIX level ceiling | 130 | 130 (unchanged) |
| Trend Break: structural (vs 100d MA) sub-score cap | 25 | **15** |
| Trend Break: tactical pullback (vs 20d high) sub-score cap | n/a | **10** |
| Tactical pullback saturation | n/a | **-4% → 10/10 (linear)** |
| Composite version field | absent | **`composite_version: 3`** |

**Tactical pullback formula:** `min(max(-(spy_today / max(spy[-20:]) - 1) * 100, 0) / 4 * 10, 10)`. Reads 4.9 at -1.97% today.

**Band cutoffs unchanged.** 25 → ELEVATED, 50 → HIGH, 75 → CRITICAL.

---

## File map

| Path | Action | Why |
|---|---|---|
| `src/uw_scan/cards/mean_reversion.py` | Modify | Add `compute_pullback_20d`, `compute_vix_delta_3d` pure functions |
| `src/uw_scan/cards/cri_scoring.py` | Modify | Apply calibration deltas; reshape `score_momentum_component`; thread pullback through `compute_cri`; bump `composite_version`; surface `pullback_20d_pct` + `vix_delta_3d` in `run_analysis` payload |
| `src/uw_scan/scanners/cri.py` | Modify | No new DB work — pullback derived from existing SPX/SPY array; VIX delta from existing VIX array |
| `src/uw_scan/api/schemas.py` | Modify | Add `pullback_20d_pct: float \| None`, `vix_delta_3d: float \| None`, `composite_version: int \| None` to `CriResponse` |
| `tests/unit/test_mean_reversion.py` | Modify | TDD: 6 new tests (3 per helper) |
| `tests/unit/test_cri_scoring.py` | Modify | TDD: recalibration boundary tests + composite_version assertion + pullback integration |
| `tests/integration/test_cri_scanner.py` | Modify | TDD: e2e snapshot includes pullback / vix_delta / composite_version=3 |
| `tests/integration/api/openapi.snapshot.json` | Regen | Snapshot picks up 3 new fields |
| `scripts/backtest_cri.py` | Modify | Use v3 scorers; output `cri-backtest-v3.csv` |
| `docs/research/regime/oos-summary.json` | Modify | Add v3 dd5 / dd10 row; **gate: v3 AUC must ≥ v1** |
| `docs/research/regime/cri-methodology.md` | Modify | §3 (component math) + §8 (changelog) describe v3 |
| `docs/research/regime/cri-backtest.{md,csv}` | Regen | Refresh full-history backtest with v3 scorers |
| `web/lib/types.ts` | Regen via `npm run gen:types` | Pull in schema additions |
| `web/components/regime/MeanReversionTiles.tsx` | Modify | Add 4th tile: "VIX Δ (3d)" |
| `web/components/regime/CriSubTab.tsx` | Modify | (a) Add 1-line readout under Trend Break (b) Update `priorComponentScore` lines 59-87 for ALL FOUR slots — VIX floor 15→13 + RoC denom 60→40; VVIX floor 85→80; correlation unchanged; momentum reshape to structural-15 + tactical-10 (uses new `prior.pullback_20d_pct` field) |
| `web/app/globals.css` | Modify | 4-up grid for `.regime-meanrev-row` |
| `web/tests/unit/MeanReversionTiles.test.tsx` | Modify | Expect 4 tiles |
| `web/tests/unit/CriSubTab.priorScore.test.tsx` | Create | Vitest covering the 4 recalibrated `priorComponentScore` branches against fixed history fixtures |
| `migrations/2026-05-20-cri-composite-version-backfill.sql` | Create | Idempotent `UPDATE uw_scan.cri_snapshots SET payload = jsonb_set(payload, '{cri,composite_version}', '1') WHERE payload->'cri'->>'composite_version' IS NULL` so historical rows are explicitly labeled v1 (otherwise replay/version-filter UI returns empty for >99% of history) |

---

## Task 0 — DB backfill: label historical snapshots as `composite_version=1`

**Files:**
- Create: `migrations/2026-05-20-cri-composite-version-backfill.sql`

Without this, replay UI / version-filtered queries return empty for the >99% of `cri_snapshots` rows that pre-date v3. The migration is idempotent and is the first thing to apply so the rest of the work runs against correctly-labelled data.

- [ ] **Step 0.1: Create migration file**

Write `migrations/2026-05-20-cri-composite-version-backfill.sql`:

```sql
-- Backfill composite_version=1 on snapshots written before the v3 calibration.
-- Idempotent: the WHERE clause filters out rows that already carry a version,
-- so re-running this migration is a no-op.
UPDATE uw_scan.cri_snapshots
SET payload = jsonb_set(
    payload,
    '{cri,composite_version}',
    '1'::jsonb,
    true
)
WHERE payload->'cri'->>'composite_version' IS NULL;
```

- [ ] **Step 0.2: Apply migration**

Run: `bash scripts/migrate.sh`
Expected: idempotent — re-running is a no-op per the standing migration rule.

- [ ] **Step 0.3: Verify the backfill**

Run:

```bash
uv run python -c "
import psycopg, json
from uw_scan.config import Settings
with psycopg.connect(Settings().db_dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(\"SELECT COUNT(*) FROM uw_scan.cri_snapshots WHERE payload->'cri'->>'composite_version' IS NULL\")
        missing = cur.fetchone()[0]
        cur.execute(\"SELECT COUNT(*) FROM uw_scan.cri_snapshots WHERE payload->'cri'->>'composite_version' = '1'\")
        v1 = cur.fetchone()[0]
        print(f'missing version: {missing} (expect 0)')
        print(f'v1 rows: {v1}')
"
```

Expected: `missing version: 0`, `v1 rows: ≈230` (all pre-v3 rows now explicitly v1).

- [ ] **Step 0.4: Commit**

```bash
git add migrations/2026-05-20-cri-composite-version-backfill.sql
git commit -m "chore(migrations): backfill composite_version=1 on historical CRI snapshots"
```

---

## Task 1 — Mean-reversion helpers: `compute_pullback_20d` + `compute_vix_delta_3d`

**Files:**
- Create test cases in: `tests/unit/test_mean_reversion.py`
- Modify: `src/uw_scan/cards/mean_reversion.py`

- [ ] **Step 1.1: Write failing tests for `compute_pullback_20d`**

Append to `tests/unit/test_mean_reversion.py`:

```python
import numpy as np

from uw_scan.cards.mean_reversion import (
    compute_pullback_20d,
    compute_vix_delta_3d,
)


class TestComputePullback20d:
    def test_returns_zero_when_today_is_the_20d_high(self):
        prices = np.array([100.0] * 19 + [110.0])
        assert compute_pullback_20d(prices) == 0.0

    def test_returns_negative_drawdown_pct_from_rolling_high(self):
        # 20d window high = 110, today = 107.8 → -2.0%
        prices = np.array([100.0] * 18 + [110.0, 107.8])
        result = compute_pullback_20d(prices)
        assert abs(result - (-2.0)) < 1e-9

    def test_uses_last_20_observations_when_more_provided(self):
        # 25 prices; older 110 outside last-20 must be ignored.
        # Last 20 (indices 5..24) = [100]*18 + [105, 99.75]; high=105, today=99.75.
        # Expected: (99.75 / 105 - 1) * 100 = -5.0
        prices = np.array([110.0] * 5 + [100.0] * 18 + [105.0, 99.75])
        result = compute_pullback_20d(prices)
        assert abs(result - (-5.0)) < 1e-9

    def test_returns_nan_when_fewer_than_20_prices(self):
        prices = np.array([100.0] * 19)
        assert np.isnan(compute_pullback_20d(prices))
```

- [ ] **Step 1.2: Run tests; expect ImportError**

Run: `uv run pytest tests/unit/test_mean_reversion.py::TestComputePullback20d -v`
Expected: collection error / `ImportError: cannot import name 'compute_pullback_20d'`.

- [ ] **Step 1.3: Implement `compute_pullback_20d`**

Append to `src/uw_scan/cards/mean_reversion.py`:

```python
def compute_pullback_20d(prices: np.ndarray) -> float:
    """Today's drawdown from the trailing-20-session high, in % points.

    Returns 0.0 when today *is* the 20d high, negative otherwise.
    NaN when fewer than 20 closes are available.
    """
    if prices is None or len(prices) < 20:
        return float("nan")
    window = prices[-20:]
    high = float(np.max(window))
    today = float(window[-1])
    if high <= 0:
        return float("nan")
    return float((today / high - 1) * 100)
```

- [ ] **Step 1.4: Run pullback tests; expect 4 PASS**

Run: `uv run pytest tests/unit/test_mean_reversion.py::TestComputePullback20d -v`
Expected: 4 passed.

- [ ] **Step 1.5: Write failing tests for `compute_vix_delta_3d`**

Append to `tests/unit/test_mean_reversion.py`:

```python
class TestComputeVixDelta3d:
    def test_returns_absolute_change_over_3_sessions(self):
        vix = np.array([17.0, 17.2, 17.5, 17.26, 17.4, 17.9, 18.06])
        # today=18.06, t-3=17.26 → +0.80
        result = compute_vix_delta_3d(vix)
        assert abs(result - 0.80) < 1e-9

    def test_handles_negative_delta(self):
        vix = np.array([20.0, 19.5, 19.0, 18.5])
        # today=18.5, t-3=20.0 → -1.5
        result = compute_vix_delta_3d(vix)
        assert abs(result - (-1.5)) < 1e-9

    def test_returns_nan_when_fewer_than_4_observations(self):
        vix = np.array([17.0, 17.5, 18.0])
        assert np.isnan(compute_vix_delta_3d(vix))
```

- [ ] **Step 1.6: Run tests; expect ImportError**

Run: `uv run pytest tests/unit/test_mean_reversion.py::TestComputeVixDelta3d -v`
Expected: ImportError.

- [ ] **Step 1.7: Implement `compute_vix_delta_3d`**

Append to `src/uw_scan/cards/mean_reversion.py`:

```python
def compute_vix_delta_3d(vix: np.ndarray) -> float:
    """Absolute change in VIX over the last 3 sessions, in points.

    Positive = vol expanding. Returns NaN with fewer than 4 observations.
    """
    if vix is None or len(vix) < 4:
        return float("nan")
    today = float(vix[-1])
    t_minus_3 = float(vix[-4])
    if np.isnan(today) or np.isnan(t_minus_3):
        return float("nan")
    return today - t_minus_3
```

- [ ] **Step 1.8: Run all mean-reversion tests; expect all PASS**

Run: `uv run pytest tests/unit/test_mean_reversion.py -v`
Expected: all tests passed (previous + 7 new).

- [ ] **Step 1.9: Commit**

```bash
git add tests/unit/test_mean_reversion.py src/uw_scan/cards/mean_reversion.py
git commit -m "feat(regime): add compute_pullback_20d + compute_vix_delta_3d helpers"
```

---

## Task 2 — CRI scoring v3: recalibrate + reshape momentum

**Files:**
- Modify: `tests/unit/test_cri_scoring.py`
- Modify: `src/uw_scan/cards/cri_scoring.py:86-92` (VIX scorer)
- Modify: `src/uw_scan/cards/cri_scoring.py:95-116` (VVIX scorer)
- Modify: `src/uw_scan/cards/cri_scoring.py:130-136` (Trend Break scorer)
- Modify: `src/uw_scan/cards/cri_scoring.py:154-181` (`compute_cri`)
- Modify: `src/uw_scan/cards/cri_scoring.py:265-432` (`run_analysis` — payload fields + composite_version)

- [ ] **Step 2.1: Write failing tests for VIX floor + RoC recalibration**

Append to `tests/unit/test_cri_scoring.py`:

```python
class TestVixComponentV3:
    def test_floor_lowered_to_13(self):
        # VIX 13 should now score 0; VIX 14 should score >0.
        # Derivation: (14-13)/(40-13)*15 = 15/27 ≈ 0.556
        from uw_scan.cards.cri_scoring import score_vix_component
        assert score_vix_component(13.0, 0.0) == 0.0
        score = score_vix_component(14.0, 0.0)
        assert abs(score - (15.0 / 27.0)) < 1e-6

    def test_roc_denominator_steepened_to_40(self):
        # VIX RoC of 40% saturates the RoC sub-score at 10/10.
        # Derivation: max(40, 0)/40 * 10 = 10
        from uw_scan.cards.cri_scoring import score_vix_component
        score = score_vix_component(13.0, 40.0)  # level=0 at floor, roc saturated
        assert abs(score - 10.0) < 1e-6
```

- [ ] **Step 2.2: Run tests; expect FAIL**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestVixComponentV3 -v`
Expected: 2 failures (current floor=15 means VIX 14 scores 0; current denom=60 means 40% RoC scores 6.67/10).

- [ ] **Step 2.3: Apply VIX recalibration**

Edit `src/uw_scan/cards/cri_scoring.py:90-91`:

```python
def score_vix_component(vix: float, vix_5d_roc: float) -> float:
    """Score VIX component (0-25). vix_5d_roc is in %."""
    if math.isnan(vix) or math.isnan(vix_5d_roc):
        return 0.0
    level_score = np.clip((vix - 13.0) / (40.0 - 13.0) * 15.0, 0.0, 15.0)
    roc_score = np.clip(max(vix_5d_roc, 0.0) / 40.0 * 10.0, 0.0, 10.0)
    return float(np.clip(level_score + roc_score, 0.0, 25.0))
```

- [ ] **Step 2.4: Re-run VIX tests; expect PASS**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestVixComponentV3 -v`
Expected: 2 passed.

- [ ] **Step 2.5: Write failing test for VVIX floor lowered to 80**

Append to `tests/unit/test_cri_scoring.py`:

```python
class TestVvixComponentV3:
    def test_floor_lowered_to_80(self):
        from uw_scan.cards.cri_scoring import score_vvix_component
        assert score_vvix_component(80.0, 5.5, 0.0) == 0.0
        # VVIX 82 should now score a positive level component
        assert score_vvix_component(82.0, 5.5, 0.0) > 0.0
```

- [ ] **Step 2.6: Run test; expect FAIL**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestVvixComponentV3 -v`
Expected: failure (current floor=85 means VVIX 82 scores 0 on level).

- [ ] **Step 2.7: Apply VVIX recalibration**

Edit `src/uw_scan/cards/cri_scoring.py:113`:

```python
    level_score = np.clip((vvix - 80.0) / (130.0 - 80.0) * 12.0, 0.0, 12.0)
```

- [ ] **Step 2.8: Re-run VVIX test; expect PASS**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestVvixComponentV3 -v`
Expected: passed.

- [ ] **Step 2.9: Write failing tests for momentum (Trend Break) reshape**

Append to `tests/unit/test_cri_scoring.py`:

```python
class TestMomentumComponentV3:
    def test_structural_break_capped_at_15(self):
        # SPX -10% below MA used to score 25; now caps at 15.
        # Derivation: abs(-10)/10 * 15 = 15
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=-10.0, pullback_20d_pct=0.0)
        assert abs(score - 15.0) < 1e-6

    def test_tactical_pullback_alone_can_fire_when_above_ma(self):
        # SPX +6% above MA → structural=0; -3% pullback → tactical = 3/4 * 10 = 7.5
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=6.0, pullback_20d_pct=-3.0)
        assert abs(score - 7.5) < 1e-6

    def test_tactical_pullback_saturates_at_minus_4pct(self):
        # Pullback of -6% (deeper than -4% saturation) → tactical capped at 10
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=0.0, pullback_20d_pct=-6.0)
        assert abs(score - 10.0) < 1e-6

    def test_total_capped_at_25(self):
        # structural=15 (capped) + tactical=10 (capped) = 25 (component cap)
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=-20.0, pullback_20d_pct=-10.0)
        assert abs(score - 25.0) < 1e-6

    def test_structural_15_plus_nonzero_tactical_below_cap(self):
        # Boundary case: structural saturated at 15, tactical=5 → total=20 (not 25)
        # Catches a bug where the cap might short-circuit before adding tactical.
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=-10.0, pullback_20d_pct=-2.0)
        assert abs(score - 20.0) < 1e-6

    def test_today_real_world_scenario(self):
        # SPX +6.22% above MA → structural=0; -1.97% pullback → tactical = 1.97/4 * 10 = 4.925
        from uw_scan.cards.cri_scoring import score_momentum_component
        score = score_momentum_component(spx_distance_pct=6.22, pullback_20d_pct=-1.97)
        assert abs(score - 4.925) < 0.01
```

- [ ] **Step 2.10: Run tests; expect 5 FAIL**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestMomentumComponentV3 -v`
Expected: 5 failures + `TypeError` for unexpected kwarg.

- [ ] **Step 2.11: Reshape momentum scorer**

Edit `src/uw_scan/cards/cri_scoring.py:130-136`:

```python
def score_momentum_component(
    spx_distance_pct: float,
    pullback_20d_pct: float = 0.0,
) -> float:
    """Score Trend Break component (0-25) — structural + tactical.

    Structural sub-score (0-15): rises as SPX falls below 100d MA, saturated
    at -10% below MA.
    Tactical sub-score (0-10): rises with drawdown from trailing-20-session
    high, saturated at -4% (linear).

    The split surfaces tactical pullbacks while preserving the crash-focused
    structural signal. See docs/research/regime/cri-methodology.md §3 (v3).
    """
    if math.isnan(spx_distance_pct):
        structural = 0.0
    elif spx_distance_pct >= 0:
        structural = 0.0
    else:
        structural = float(np.clip(abs(spx_distance_pct) / 10.0 * 15.0, 0.0, 15.0))

    if pullback_20d_pct is None or math.isnan(pullback_20d_pct) or pullback_20d_pct >= 0:
        tactical = 0.0
    else:
        tactical = float(np.clip(abs(pullback_20d_pct) / 4.0 * 10.0, 0.0, 10.0))

    return float(np.clip(structural + tactical, 0.0, 25.0))
```

- [ ] **Step 2.12: Run momentum tests; expect PASS**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestMomentumComponentV3 -v`
Expected: 5 passed.

- [ ] **Step 2.13: Thread pullback through `compute_cri` + add `composite_version`**

Edit `src/uw_scan/cards/cri_scoring.py:154-181`:

```python
COMPOSITE_VERSION = 3


def compute_cri(
    vix: float,
    vix_5d_roc: float,
    vvix: float,
    vvix_vix_ratio: float,
    vvix_5d_roc: float,
    corr: float,
    corr_5d_change: float,
    spx_distance_pct: float,
    pullback_20d_pct: float = 0.0,
) -> dict[str, Any]:
    """Composite 0-100 score from the four components.

    The momentum component now receives both structural (vs 100d MA) and
    tactical (vs 20d high) inputs. See `score_momentum_component`.
    """
    vix_score = score_vix_component(vix, vix_5d_roc)
    vvix_score = score_vvix_component(vvix, vvix_vix_ratio, vvix_5d_roc)
    corr_score = score_correlation_component(corr, corr_5d_change)
    momentum_score = score_momentum_component(spx_distance_pct, pullback_20d_pct)
    total = float(
        np.clip(vix_score + vvix_score + corr_score + momentum_score, 0.0, 100.0)
    )
    return {
        "score": round(total, 1),
        "level": cri_level(total),
        "composite_version": COMPOSITE_VERSION,
        "components": {
            "vix": round(vix_score, 1),
            "vvix": round(vvix_score, 1),
            "correlation": round(corr_score, 1),
            "momentum": round(momentum_score, 1),
        },
    }
```

- [ ] **Step 2.14: Write test for composite_version + run_analysis payload fields**

Append to `tests/unit/test_cri_scoring.py`:

```python
class TestCompositeVersionV3:
    def test_compute_cri_includes_composite_version_3(self):
        from uw_scan.cards.cri_scoring import compute_cri
        result = compute_cri(
            vix=18.0, vix_5d_roc=5.0, vvix=95.0, vvix_vix_ratio=5.3,
            vvix_5d_roc=2.0, corr=27.0, corr_5d_change=1.0,
            spx_distance_pct=6.0, pullback_20d_pct=-2.0,
        )
        assert result["composite_version"] == 3
        assert "momentum" in result["components"]


class TestRunAnalysisPayloadV3:
    def test_payload_includes_pullback_20d_and_vix_delta_3d(self):
        import numpy as np
        from uw_scan.cards.cri_scoring import run_analysis
        n = 110
        spx = np.linspace(6000, 7000, n)
        spx[-1] = spx[-3] * 0.98  # -2% from 3d back
        vix = np.linspace(15, 18, n)
        vvix = np.linspace(85, 95, n)
        cor = np.full(n, 26.0)
        aligned = {"VIX": vix, "VVIX": vvix, "SPX": spx, "SPY": spx, "COR1M": cor}
        dates = [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)]
        out = run_analysis(aligned, dates)
        assert "pullback_20d_pct" in out
        assert "vix_delta_3d" in out
        assert out["cri"]["composite_version"] == 3
```

- [ ] **Step 2.15: Run new tests; expect FAIL for run_analysis payload**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestCompositeVersionV3 tests/unit/test_cri_scoring.py::TestRunAnalysisPayloadV3 -v`
Expected: composite_version PASS (already wired in step 2.13); run_analysis payload FAIL.

- [ ] **Step 2.16: Surface new fields in `run_analysis`**

Edit `src/uw_scan/cards/cri_scoring.py:265-432` — three concrete changes:

(a) Add imports at top of file:

```python
from uw_scan.cards.mean_reversion import (
    compute_pullback_20d,
    compute_vix_delta_3d,
    compute_vrp,
    vix_vix3m_ratio,
    vix_zscore_30d,
)
```

(b) After `realized_vol = compute_realized_vol(spy, VOL_WINDOW)` (line 323), compute new metrics:

```python
    pullback_20d_pct = compute_pullback_20d(spy)
    vix_delta_3d = compute_vix_delta_3d(vix)
```

(c) Update the `compute_cri(...)` call to pass `pullback_20d_pct=pullback_20d_pct if not math.isnan(pullback_20d_pct) else 0.0`.

(d) Add to the returned dict (alongside `vrp`, `vix_zscore_30d`, `vix_vix3m_ratio`):

```python
        "pullback_20d_pct": round(pullback_20d_pct, 2) if not math.isnan(pullback_20d_pct) else None,
        "vix_delta_3d": round(vix_delta_3d, 2) if not math.isnan(vix_delta_3d) else None,
```

- [ ] **Step 2.17: Run payload test; expect PASS**

Run: `uv run pytest tests/unit/test_cri_scoring.py::TestRunAnalysisPayloadV3 -v`
Expected: passed.

- [ ] **Step 2.18: Run full unit test file; expect all PASS (no regression)**

Run: `uv run pytest tests/unit/test_cri_scoring.py -v`
Expected: all tests passed (including previous SPX-preference + mean-reversion-field tests).

- [ ] **Step 2.19: Commit**

```bash
git add tests/unit/test_cri_scoring.py src/uw_scan/cards/cri_scoring.py
git commit -m "feat(regime): CRI v3 — recalibrate floors, tactical pullback sub-score, composite_version=3"
```

---

## Task 2.5 — Split `cri_scoring.py` to keep module budget healthy

**Files:**
- Create: `src/uw_scan/cards/cri_scorers.py`
- Modify: `src/uw_scan/cards/cri_scoring.py`
- Verify: existing imports `from uw_scan.cards.cri_scoring import ...` still resolve

Motivation: `cri_scoring.py` is 432 lines before Task 2 and lands at ~460-470 after. The 500-line budget is a soft target with a hard 1000-line ceiling. Adding follow-on work (v4 backtest harness, ablation hooks per Task 4.2b, future sub-scores) without splitting now means we breach the policy on the next change. Splitting now is cheap; splitting later means reverting tests under pressure.

Split by domain seam (one module per cohesive set of methods) per the module-size memory.

- [ ] **Step 2.5.1: Move scorers + composite into `cri_scorers.py`**

Create `src/uw_scan/cards/cri_scorers.py` and move into it from `cri_scoring.py`:
- `COMPOSITE_VERSION`, `MA_WINDOW`, `VOL_WINDOW`, `CTA_VOL_TARGET`, `CTA_MAX_EXPOSURE`, `CTA_AUM_BN`, `CRASH_REALIZED_VOL_THRESHOLD`, `CRASH_COR1M_THRESHOLD`
- `compute_realized_vol`, `cor1m_level_and_change`
- `score_vix_component`, `score_vvix_component`, `score_correlation_component`, `score_momentum_component`
- `cri_level`, `compute_cri`, `cta_exposure_model`, `crash_trigger`

`cri_scoring.py` retains: imports, `run_analysis(...)`, and re-exports of every name above so external imports `from uw_scan.cards.cri_scoring import compute_cri, COMPOSITE_VERSION` keep resolving:

```python
from uw_scan.cards.cri_scorers import (  # noqa: F401 — re-export for back-compat
    COMPOSITE_VERSION,
    CRASH_COR1M_THRESHOLD,
    CRASH_REALIZED_VOL_THRESHOLD,
    CTA_AUM_BN,
    CTA_MAX_EXPOSURE,
    CTA_VOL_TARGET,
    MA_WINDOW,
    VOL_WINDOW,
    compute_cri,
    compute_realized_vol,
    cor1m_level_and_change,
    cri_level,
    crash_trigger,
    cta_exposure_model,
    score_correlation_component,
    score_momentum_component,
    score_vix_component,
    score_vvix_component,
)
```

- [ ] **Step 2.5.2: Run all unit tests; expect PASS (no import breakage)**

Run: `uv run pytest tests/unit/test_cri_scoring.py -v`
Expected: every test passes — re-exports preserve the import surface used by tests.

- [ ] **Step 2.5.3: Verify both modules fit comfortably under 500 lines**

Run: `wc -l src/uw_scan/cards/cri_scorers.py src/uw_scan/cards/cri_scoring.py`
Expected: each file < 350 lines (with room for follow-on growth).

- [ ] **Step 2.5.4: Commit**

```bash
git add src/uw_scan/cards/cri_scorers.py src/uw_scan/cards/cri_scoring.py
git commit -m "refactor(regime): split scorers from cri_scoring; preserve import surface"
```

---

## Task 3 — Scanner integration: surface new fields in snapshot

**Files:**
- Modify: `tests/integration/test_cri_scanner.py`
- (NO changes to `src/uw_scan/scanners/cri.py` — see Step 3.3)
- Modify: `src/uw_scan/api/schemas.py` (add fields to nested `CriBlock`, NOT top-level `CriResponse`)

**Important context** (verified at review time): `scanners/cri.py:130-134` calls `payload = cri_scoring.run_analysis(...)` and persists the **entire** payload dict via `snap_repo.insert_snapshot(payload=payload, ...)`. There is no per-field selection. So once Step 2.16 has `run_analysis` return `pullback_20d_pct` and `vix_delta_3d`, they auto-persist. The only Task 3 work is (a) the integration test, and (b) the schema additions in the right struct.

**Important context 2**: `composite_version` lives at `cri.composite_version` (nested inside the CRI block returned by `compute_cri`), NOT at the top level. Verified by reading the dict shape in `compute_cri` at Step 2.13. The schema field add must therefore land on `CriBlock` (lines ~398-421 of `schemas.py`), NOT on the top-level `CriResponse`.

- [ ] **Step 3.1: Write failing integration test**

The existing tests in `tests/integration/test_cri_scanner.py` use the `seeded_db_empty_cards` fixture and call `cri_scanner.run(conn, schema=repo._schema)` then read via `CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()`. Mirror that pattern exactly:

```python
def test_snapshot_exposes_v3_pullback_vix_delta_and_version(
    seeded_db_empty_cards,
):
    """v3 payload exposes pullback_20d_pct, vix_delta_3d, and cri.composite_version=3."""
    repo = seeded_db_empty_cards
    conn = repo._conn
    _seed_vol(conn, repo._schema)  # follow existing helper used at top of file
    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None

    snap_repo = CriSnapshotRepository(conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    payload = latest["payload"] if "payload" in latest else latest

    # composite_version is nested under cri (NOT top-level)
    assert payload["cri"]["composite_version"] == 3

    # The new mean-reversion / pullback fields are top-level on the payload
    assert "pullback_20d_pct" in payload
    assert "vix_delta_3d" in payload
    assert payload["pullback_20d_pct"] is None or isinstance(payload["pullback_20d_pct"], (int, float))
    assert payload["vix_delta_3d"] is None or isinstance(payload["vix_delta_3d"], (int, float))
```

(If the existing `_seed_vol` helper or `fetch_latest` return shape differs, copy the exact pattern from `test_run_persists_snapshot_when_data_is_sufficient` at `test_cri_scanner.py:57-90` and adapt the assertions.)

- [ ] **Step 3.2: Run test; expect FAIL**

Run: `uv run pytest tests/integration/test_cri_scanner.py::test_snapshot_exposes_v3_pullback_vix_delta_and_version -v`
Expected: failure — `cri.composite_version` missing until Task 2.13 lands, then `pullback_20d_pct`/`vix_delta_3d` missing until Task 2.16 lands.

- [ ] **Step 3.3: NO scanner code changes**

Confirmed during review: `scanners/cri.py:130-134` persists the full `run_analysis` output dict via `insert_snapshot(payload=payload)`. Since Step 2.16 already adds the new fields to that dict and Step 2.13 already nests `composite_version` inside the `cri` block, no work is needed here.

Skip to Step 3.4.

- [ ] **Step 3.4: Add fields to schema (correct location: nested `CriBlock`, top-level for pullback / delta)**

Read `src/uw_scan/api/schemas.py` and locate `class CriBlock` (around line 398). Add `composite_version` INSIDE `CriBlock`, with a Literal type to prevent typo'd drift:

```python
class CriBlock(BaseModel):
    score: float
    level: str
    composite_version: Literal[1, 2, 3] | None = None
    components: CriComponents = Field(default_factory=CriComponents)
```

Locate `class CriResponse` (around line 421). Add `pullback_20d_pct` and `vix_delta_3d` at the TOP LEVEL (they are siblings of `vrp`, `vix_zscore_30d`, `vix_vix3m_ratio`), with Pydantic field validators that coerce non-finite floats (NaN/Inf) to `None` as defense in depth:

```python
    pullback_20d_pct: float | None = None
    vix_delta_3d: float | None = None

    @field_validator("pullback_20d_pct", "vix_delta_3d", mode="after")
    @classmethod
    def _coerce_nonfinite_to_none(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not math.isfinite(v):
            return None
        return v
```

Make sure `from typing import Literal` and `from pydantic import field_validator` and `import math` are imported at the top of the file (check existing imports first; only add what's missing).

- [ ] **Step 3.5: Run scanner integration tests; expect PASS**

Run: `uv run pytest tests/integration/test_cri_scanner.py -v`
Expected: all tests passed.

- [ ] **Step 3.6: Regenerate OpenAPI snapshot**

The repo's snapshot test (`tests/integration/api/test_openapi_snapshot.py`) is a **hand-written comparison** — it loads `openapi.snapshot.json` from disk and `assert ==`s against `client.get("/openapi.json").json()`. There is no `pytest --snapshot-update` flag. Regenerate by running:

```bash
uv run python -c "
import json, pathlib
from fastapi.testclient import TestClient
from uw_scan.api.server import app
out = TestClient(app).get('/openapi.json').json()
pathlib.Path('tests/integration/api/openapi.snapshot.json').write_text(json.dumps(out, indent=2) + '\n')
"
```

Then `git diff tests/integration/api/openapi.snapshot.json` and verify the change is exactly:
- `pullback_20d_pct` and `vix_delta_3d` added to `CriResponse` schema with `nullable: true`
- `composite_version` added to `CriBlock` schema with `enum: [1, 2, 3]` and `nullable: true`
- No other schema additions/removals.

Re-run the snapshot test to confirm it now passes: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`

- [ ] **Step 3.7: Regenerate web types**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run gen:types`
Verify `web/lib/types.ts` `CriResponse` interface now includes the three new fields.

- [ ] **Step 3.8: Commit**

```bash
git add tests/integration/test_cri_scanner.py src/uw_scan/scanners/cri.py src/uw_scan/api/schemas.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(regime): persist pullback_20d, vix_delta_3d, composite_version=3 in CRI snapshot"
```

---

## Task 4 — OOS validation gate (automated pytest + symmetry + ablation)

**Files:**
- Modify: `scripts/backtest_cri.py` (no scorer code injection — see context below)
- Create: `tests/integration/regime/test_cri_oos_gate.py`
- Modify: `docs/research/regime/oos-summary.json` (script writes; do not hand-edit)
- Modify: `docs/research/regime/cri-backtest.{md,csv}` (script writes)

**Important context** (verified at review time): `scripts/backtest_cri.py:108,126` calls `cri_scoring.run_analysis(aligned, common_dates)` — NOT `compute_cri` directly. Since Step 2.16 wires `compute_pullback_20d` into `run_analysis`, the backtest auto-picks-up v3 once Task 2 lands. **Do NOT inject `from uw_scan.cards.mean_reversion import compute_pullback_20d` into the script — that snippet would be dead code.**

This task closes three integrity gaps from the security review:
- **Asymmetry**: v1 was a frozen literal (0.620 / 0.647) in the doc, v3 was freshly recomputed. The fix: recompute v1 in the same run on the same labels, assert it matches the stored value within tolerance, then compare v3.
- **Manual prose stop**: replaced by a pytest under `tests/integration/regime/`. CI enforces the gate.
- **Documentation as fabrication vector**: the backtest script writes `oos-summary.json` directly; the methodology doc references the JSON instead of embedding numbers.

- [ ] **Step 4.1: Add `--write-oos-summary` mode to the backtest script**

In `scripts/backtest_cri.py`, after the existing CSV write, add a function that:
1. Loads the freshly written `cri-backtest.csv`.
2. Computes dd5 / dd10 labels (`pct_change(5).shift(-5) * 100 < -5` and same for dd10).
3. Computes AUC of `score` against each label using `sklearn.metrics.roc_auc_score`.
4. ALSO loads the v1 archived per-day scores (from a frozen reference CSV — see Step 4.2 for how to produce it) and computes its AUC on the same label series so v1 and v3 are scored identically.
5. Writes `oos-summary.json` in this shape:

```json
{
  "generated_at": "2026-05-20T...",
  "labels": {"dd5": "SPX 5d return < -5%", "dd10": "SPX 10d return < -10%"},
  "versions": [
    {"label": "CRI v1", "version": 1, "auc_dd5": 0.620, "auc_dd10": 0.647, "n_observations": <n>},
    {"label": "CRI v3", "version": 3, "auc_dd5": <measured>, "auc_dd10": <measured>, "n_observations": <n>,
     "notes": "VIX floor 13, RoC denom 40, VVIX floor 80, tactical-pullback sub-score (-4% sat)"}
  ]
}
```

CLI: `uv run python scripts/backtest_cri.py --output docs/research/regime/cri-backtest --write-oos-summary docs/research/regime/oos-summary.json`.

- [ ] **Step 4.2: Produce a frozen v1 reference scoring CSV**

To compare v1 and v3 symmetrically, we need v1 scores on every historical date. Do ONE of:
- (preferred) Pull `score` from the existing in-DB v1 snapshots — after Task 0 backfills, these rows are labeled v1.
- (fallback) Temporarily revert `cri_scorers.py` to the pre-Task-2 calibration via a feature flag (`UW_SCAN_CRI_VERSION=1` env var) and run the backtest once to produce `cri-backtest-v1-reference.csv`. Restore v3 immediately after.

Pick the DB-pull option. Add a `--v1-reference-from-db` flag to the backtest that emits `cri-backtest-v1-reference.csv` from `uw_scan.cri_snapshots WHERE payload->'cri'->>'composite_version' = '1'`.

- [ ] **Step 4.2b: Ablation table for lever isolation**

If the gate fails (Step 4.4), root-causing requires single-lever AUC runs. Building these now (when the data + scorers are already in memory) is ~30 minutes; building them post-failure means another full backtest pass.

Add a `--write-ablation` flag that emits a `ablation` array inside `oos-summary.json` with these rows (each computed by calling `compute_cri` with all v3 levers EXCEPT one held at v1):

| Label | VIX floor | VIX RoC denom | VVIX floor | Tactical sub-score |
|---|---|---|---|---|
| v1 (frozen) | 15 | 60 | 85 | off |
| v3-vix-only | 13 | 40 | 85 | off |
| v3-vvix-only | 15 | 60 | 80 | off |
| v3-tactical-only | 15 | 60 | 85 | on |
| v3-full | 13 | 40 | 80 | on |

For each row, compute dd5 + dd10 AUC. The output supports answering "which lever moved the score?" without another backtest.

- [ ] **Step 4.3: Run the backtest end-to-end**

```bash
uv run python scripts/backtest_cri.py \
    --output docs/research/regime/cri-backtest \
    --write-oos-summary docs/research/regime/oos-summary.json \
    --v1-reference-from-db \
    --write-ablation
```

Expected outputs:
- `docs/research/regime/cri-backtest.csv` (v3 scores, ~4873 rows)
- `docs/research/regime/cri-backtest.md` (markdown summary)
- `docs/research/regime/oos-summary.json` (v1, v3, ablation rows — script-written, not hand-edited)

- [ ] **Step 4.4: Write the OOS gate pytest**

Create `tests/integration/regime/test_cri_oos_gate.py`:

```python
"""OOS gate: v3 calibration must not degrade crash-detection AUC vs v1.

Replaces the manual "stop and re-tune" prose with an enforceable CI invariant.
Reads docs/research/regime/oos-summary.json (script-written) and asserts the
versions[] array carries the right shape and AUC relationships.
"""
import json
from pathlib import Path

import pytest

OOS_PATH = Path(__file__).resolve().parents[2] / "docs" / "research" / "regime" / "oos-summary.json"

# v1 historical baselines (the published numbers we are protecting).
# Drift from these requires an explicit JSON edit + this constant edit.
V1_DD5_BASELINE = 0.620
V1_DD10_BASELINE = 0.647
BASELINE_TOLERANCE = 0.005  # ±0.5 AUC point — catches frozen-literal drift


@pytest.fixture(scope="module")
def oos_summary() -> dict:
    if not OOS_PATH.exists():
        pytest.skip(f"{OOS_PATH} missing — regenerate via scripts/backtest_cri.py")
    return json.loads(OOS_PATH.read_text())


def _find(versions: list[dict], version: int) -> dict:
    matches = [v for v in versions if v.get("version") == version]
    assert matches, f"version={version} not present in oos-summary.json"
    return matches[0]


def test_v1_recomputed_auc_matches_published_baseline(oos_summary):
    """Catches the asymmetry where v1 was frozen-literal while v3 was recomputed."""
    v1 = _find(oos_summary["versions"], 1)
    assert abs(v1["auc_dd5"] - V1_DD5_BASELINE) <= BASELINE_TOLERANCE, (
        f"v1 dd5 AUC drifted from published baseline: {v1['auc_dd5']} vs {V1_DD5_BASELINE}"
    )
    assert abs(v1["auc_dd10"] - V1_DD10_BASELINE) <= BASELINE_TOLERANCE


def test_v3_does_not_degrade_dd5_auc(oos_summary):
    v1 = _find(oos_summary["versions"], 1)
    v3 = _find(oos_summary["versions"], 3)
    assert v3["auc_dd5"] >= v1["auc_dd5"], (
        f"v3 dd5 AUC ({v3['auc_dd5']:.3f}) < v1 ({v1['auc_dd5']:.3f}). "
        "v3 loses crash-detection ground on the 5d horizon — do NOT merge."
    )


def test_v3_does_not_degrade_dd10_auc(oos_summary):
    v1 = _find(oos_summary["versions"], 1)
    v3 = _find(oos_summary["versions"], 3)
    assert v3["auc_dd10"] >= v1["auc_dd10"], (
        f"v3 dd10 AUC ({v3['auc_dd10']:.3f}) < v1 ({v1['auc_dd10']:.3f}). "
        "v3 loses crash-detection ground on the 10d horizon — do NOT merge."
    )
```

- [ ] **Step 4.5: Run the gate**

Run: `uv run pytest tests/integration/regime/test_cri_oos_gate.py -v`

**If any test fails:** STOP. The gate exists exactly so a tired operator does not merge a degraded composite. Possible remediations:
- v1 recompute mismatches stored baseline → label-definition drift somewhere; check `pct_change(N).shift(-N)` vs `shift(-N-1)` in the script.
- v3 dd5 or dd10 below v1 → loosen the most aggressive lever first. Check `oos-summary.json` ablation rows (Step 4.2b): the lever whose isolated-AUC drop is largest is the regression source. Most likely candidate: tactical-pullback saturation; raising from -4% to -5% reduces sensitivity but preserves crash-AUC.

- [ ] **Step 4.6: Commit (only if gate passed)**

```bash
git add scripts/backtest_cri.py docs/research/regime/oos-summary.json docs/research/regime/cri-backtest.csv docs/research/regime/cri-backtest.md tests/integration/regime/test_cri_oos_gate.py
git commit -m "feat(regime): OOS gate as pytest with v1 symmetry + lever-ablation table"
```

---

## Task 5 — Methodology docs

**Files:**
- Modify: `docs/research/regime/cri-methodology.md` §3 (component math) and §8 (changelog)

- [ ] **Step 5.1: Update §3**

In `cri-methodology.md` §3 (component math), under the **Trend Break** subsection, replace the existing formula description with:

```markdown
**Trend Break (0–25) — structural + tactical (v3)**

Splits into two sub-scores:

- **Structural break (0–15):** rises linearly with `|SPX_today/SPX_100d_MA − 1|` when SPX is below the 100d MA, saturating at −10%. Captures regime breakdown.
- **Tactical pullback (0–10):** rises linearly with the drawdown from the trailing-20-session high, saturating at −4%. Fires even when SPX is above the 100d MA — captures choppy multi-session sell-offs that wouldn't have shown up in v1/v2.

Total Trend Break = clip(structural + tactical, 0, 25).
```

In the **VIX** subsection, update the floor (15 → 13) and RoC denominator (60 → 40).

In the **VVIX** subsection, update the level floor (85 → 80).

- [ ] **Step 5.2: Add §8 v3 changelog entry (referencing JSON, NOT embedding numbers)**

Append to §8:

```markdown
### v3 — 2026-05-20

**Motivation:** v1/v2 calibrated for 10%-in-60d drawdown detection; multi-session 2-4% pullbacks scored near-zero (composite ≤ 6/100) even when accompanied by mild VIX expansion. Operator feedback: needs to read as 10-15/100 LOW-with-alert during tactical stress without losing the crash-detection mandate.

**Changes:**
- VIX level floor 15 → 13; RoC denominator 60% → 40%
- VVIX level floor 85 → 80
- Trend Break reshape: structural sub-score (0–15) + tactical pullback sub-score (0–10, saturating at −4% from 20d high)
- New `composite_version` field nested under the `cri` block of the snapshot payload, typed `Literal[1, 2, 3] | None`
- New `pullback_20d_pct` (%) and `vix_delta_3d` (VIX points, **not %**) fields surfaced at the top level of the snapshot for UI consumption
- Band cutoffs unchanged (25 / 50 / 75)

**OOS validation:** see `docs/research/regime/oos-summary.json` for the authoritative AUC table (v1, v3, and per-lever ablation). The gate test at `tests/integration/regime/test_cri_oos_gate.py` enforces v3 AUC ≥ v1 on dd5 AND dd10 — CI blocks merge if degraded.
```

Also update §3 (component math): under the **Trend Break** subsection add the explicit note that **`vix_delta_3d` is in VIX points, not percent** (mirrors `cor1m_5d_change` convention; differs from `vix_5d_roc` which is %).

- [ ] **Step 5.3: Commit**

```bash
git add docs/research/regime/cri-methodology.md
git commit -m "docs(regime): document CRI v3 calibration and OOS validation"
```

---

## Task 6 — UI: 4th mean-reversion tile (VIX Δ 3d)

**Files:**
- Modify: `web/tests/unit/MeanReversionTiles.test.tsx`
- Modify: `web/components/regime/MeanReversionTiles.tsx`
- Modify: `web/app/globals.css` (grid spacing)

- [ ] **Step 6.1: Update failing vitest**

Edit `web/tests/unit/MeanReversionTiles.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeanReversionTiles } from "@/components/regime/MeanReversionTiles";

describe("MeanReversionTiles", () => {
  it("renders four tiles including VIX Δ (3d)", () => {
    render(
      <MeanReversionTiles
        vrp={7.01}
        vixZ={-0.28}
        vixVix3mRatio={0.855}
        vixDelta3d={0.8}
      />,
    );
    expect(screen.getByText(/VRP/)).toBeInTheDocument();
    expect(screen.getByText(/VIX Z/)).toBeInTheDocument();
    expect(screen.getByText(/VIX\/VIX3M/)).toBeInTheDocument();
    expect(screen.getByText(/VIX Δ/)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.80/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6.2: Run test; expect FAIL**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run test -- MeanReversionTiles`
Expected: failure — component doesn't accept `vixDelta3d` and doesn't render the 4th tile.

- [ ] **Step 6.3: Add 4th tile to component**

Read `web/components/regime/MeanReversionTiles.tsx` to find the existing 3-tile shape, then:

1. Add `vixDelta3d?: number | null` to the props interface.
2. Append a 4th tile after the VIX/VIX3M tile:

```tsx
<div className="regime-tile" data-testid="tile-vix-delta-3d">
  <div className="regime-tile-label">
    VIX Δ (3d)
    <InfoTooltip text="Absolute change in VIX over the last 3 sessions, in points. Positive = vol expanding fast." />
  </div>
  <div
    className="regime-tile-value"
    style={{ color: vixDeltaColor(vixDelta3d) }}
  >
    {vixDelta3d == null
      ? "—"
      : (vixDelta3d > 0 ? "+" : "") + vixDelta3d.toFixed(2)}
  </div>
</div>
```

3. Add helper `vixDeltaColor`:

```tsx
function vixDeltaColor(delta: number | null | undefined): string {
  if (delta == null) return "var(--text-muted)";
  if (delta >= 3) return "var(--negative)";   // big expansion
  if (delta >= 1) return "var(--warning)";    // moderate
  if (delta <= -2) return "var(--positive)";  // compression
  return "var(--text-primary)";
}
```

- [ ] **Step 6.4: Update CSS grid for 4 columns**

Edit `web/app/globals.css` — find `.regime-meanrev-row`:

```css
.regime-meanrev-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin: var(--space-3) 0;
}

@media (max-width: 768px) {
  .regime-meanrev-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
```

- [ ] **Step 6.5: Pass new prop from `CriSubTab`**

Read `web/components/regime/CriSubTab.tsx` and find `<MeanReversionTiles ... />`. Add `vixDelta3d={data.vix_delta_3d ?? null}`.

- [ ] **Step 6.6: Run vitest; expect PASS**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run test -- MeanReversionTiles`
Expected: passed.

- [ ] **Step 6.7: Commit**

```bash
git add web/tests/unit/MeanReversionTiles.test.tsx web/components/regime/MeanReversionTiles.tsx web/components/regime/CriSubTab.tsx web/app/globals.css
git commit -m "feat(regime-ui): add VIX Δ (3d) tile to mean-reversion row"
```

---

## Task 7 — UI: priorComponentScore v3 alignment + tactical-pullback readout

**Files:**
- Modify: `web/components/regime/CriSubTab.tsx:51-89` (the `priorComponentScore` helper — all FOUR slots)
- Modify: `web/components/regime/CriSubTab.tsx` (~672 area — add Trend Break subtext)
- Create: `web/tests/unit/CriSubTab.priorScore.test.tsx`
- Modify: `web/app/globals.css`

**Critical context** (caught in review): `CriSubTab.tsx:51-89` re-implements the Python scoring math client-side so the prior-day dot can be drawn on each ComponentBar. The helper currently hardcodes **v1 calibration in all four slots** — `(prior.vix - 15) / 25` on line 61, `(prior.vvix - 85) / 45` on line 68, `Math.abs(d) / 10) * 25` for momentum on line 86. After v3 ships, every component's prior-arrow drifts by 20-40% unless this helper is updated alongside.

The helper also doesn't read `prior.pullback_20d_pct` for the new tactical sub-score. The `CriHistoryEntry` shape needs to be extended (verify via `web/lib/types.ts` after Step 3.7's `gen:types`) — the 20-session history list at the end of `run_analysis`'s payload (`spx_vs_ma_pct` etc.) should carry `pullback_20d_pct` too. **If not, that's a Step 7.0 below to add it in `run_analysis`.**

- [ ] **Step 7.0: Confirm `prior.pullback_20d_pct` is available in CriHistoryEntry**

Read the 20-session history loop at `src/uw_scan/cards/cri_scoring.py:351-394` (will be slightly different line numbers after Task 2 lands). Each entry currently has `vix`, `vvix`, `spy`, `cor1m`, `realized_vol`, `spx_vs_ma_pct`, `vix_5d_roc`, `vvix_5d_roc`, `cor1m_5d_change`. **Add `pullback_20d_pct` to each entry** by computing `compute_pullback_20d(spy[:i + 1])` inside the loop. Without this, the prior-day dot for the tactical sub-score can't be drawn (will fall through to 0).

Update the History entry's typed model in `src/uw_scan/api/schemas.py` to include `pullback_20d_pct: float | None`, then regen types in Step 3.7. Add a unit test in `tests/unit/test_cri_scoring.py` asserting each history entry has the new field.

- [ ] **Step 7.1: Write failing vitest for v3 priorComponentScore**

Create `web/tests/unit/CriSubTab.priorScore.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
// priorComponentScore is not currently exported — expose it for testing
// by adding `export` to the function declaration in Step 7.2.
import { priorComponentScore } from "@/components/regime/CriSubTab";

describe("priorComponentScore (v3 calibration)", () => {
  it("VIX: applies new floor 13 and RoC denom 40", () => {
    // VIX=18, RoC=4.6 → level=(18-13)/27*15=2.78, roc=4.6/40*10=1.15 → 3.9
    const score = priorComponentScore(
      { vix: 18, vix_5d_roc: 4.6 } as any,
      "vix",
    );
    expect(score).toBeCloseTo(3.9, 1);
  });

  it("VVIX: applies new floor 80", () => {
    // VVIX=95, VIX=18, ratio=5.28, no roc → lvl=(95-80)/50*12=3.6, ratio=(5.28-5)/3*7=0.65, roc=0
    const score = priorComponentScore(
      { vvix: 95, vix: 18, vvix_5d_roc: 0 } as any,
      "vvix",
    );
    expect(score).toBeCloseTo(4.3, 1);
  });

  it("correlation: unchanged (no v3 calibration delta)", () => {
    // cor1m=27, change=0 → lvl=(27-25)/45*17=0.756, spike=0 → 0.8
    const score = priorComponentScore(
      { cor1m: 27, cor1m_5d_change: 0 } as any,
      "correlation",
    );
    expect(score).toBeCloseTo(0.8, 1);
  });

  it("momentum: structural-15 + tactical-10 split", () => {
    // Above MA (+6%) + pullback -2% → structural=0, tactical=2/4*10=5 → 5.0
    const score = priorComponentScore(
      { spx_vs_ma_pct: 6.0, pullback_20d_pct: -2.0 } as any,
      "momentum",
    );
    expect(score).toBeCloseTo(5.0, 1);
  });

  it("momentum: below MA + pullback combines both sub-scores", () => {
    // -5% below MA → structural=abs(-5)/10*15=7.5; -3% pullback → tactical=3/4*10=7.5; total=15
    const score = priorComponentScore(
      { spx_vs_ma_pct: -5.0, pullback_20d_pct: -3.0 } as any,
      "momentum",
    );
    expect(score).toBeCloseTo(15.0, 1);
  });
});
```

- [ ] **Step 7.2: Run vitest; expect FAIL**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run test -- CriSubTab.priorScore`
Expected: failure (function not exported + v1 math still in place).

- [ ] **Step 7.3: Update `priorComponentScore` for v3 (all four slots)**

Edit `web/components/regime/CriSubTab.tsx:51-89`. Add `export` to the function so it's testable, then update the math:

```tsx
export function priorComponentScore(
  prior: CriHistoryEntry | undefined,
  slot: ComponentSlot,
): number | null {
  if (!prior) return null;
  const clip = (x: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, x));
  const round1 = (x: number) => Math.round(x * 10) / 10;

  if (slot === "vix") {
    // v3: floor 13, RoC denom 40
    if (prior.vix == null || prior.vix_5d_roc == null) return null;
    const lvl = clip(((prior.vix - 13) / 27) * 15, 0, 15);
    const roc = clip((Math.max(prior.vix_5d_roc, 0) / 40) * 10, 0, 10);
    return round1(lvl + roc);
  }

  if (slot === "vvix") {
    // v3: floor 80 (ratio band 5-8 and roc/25 unchanged)
    if (prior.vvix == null || prior.vix == null || prior.vix <= 0) return null;
    const ratio = prior.vvix / prior.vix;
    const lvl = clip(((prior.vvix - 80) / 50) * 12, 0, 12);
    const r = clip(((ratio - 5) / 3) * 7, 0, 7);
    const rocRaw = prior.vvix_5d_roc ?? 0;
    const roc = clip((Math.max(rocRaw, 0) / 25) * 6, 0, 6);
    return round1(lvl + r + roc);
  }

  if (slot === "correlation") {
    // v3: unchanged
    if (prior.cor1m == null) return null;
    const lvl = clip(((prior.cor1m - 25) / 45) * 17, 0, 17);
    const chg = prior.cor1m_5d_change ?? 0;
    const spike = clip((Math.max(chg, 0) / 20) * 8, 0, 8);
    return round1(lvl + spike);
  }

  if (slot === "momentum") {
    // v3: structural (vs 100d MA, 0-15) + tactical (vs 20d high, 0-10, cap at -4%)
    if (prior.spx_vs_ma_pct == null) return null;
    const d = prior.spx_vs_ma_pct;
    const structural = d >= 0 ? 0 : clip((Math.abs(d) / 10) * 15, 0, 15);
    const pullback = prior.pullback_20d_pct ?? 0;
    const tactical =
      pullback >= 0 ? 0 : clip((Math.abs(pullback) / 4) * 10, 0, 10);
    return round1(clip(structural + tactical, 0, 25));
  }

  return null;
}
```

- [ ] **Step 7.4: Run vitest; expect PASS**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run test -- CriSubTab.priorScore`
Expected: 5 passed.

- [ ] **Step 7.5: Add tactical-pullback subtext under Trend Break component card**

In `CriSubTab.tsx` near line 672 where `score={components.momentum}` is rendered, add a 1-line subtext element underneath:

```tsx
{data.pullback_20d_pct != null && data.pullback_20d_pct < 0 && (
  <div className="regime-component-subtext" data-testid="trend-break-pullback-line">
    Pullback: {data.pullback_20d_pct.toFixed(2)}% from 20d high
  </div>
)}
```

Add CSS in `globals.css`:

```css
.regime-component-subtext {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: var(--space-1);
}
```

- [ ] **Step 7.6: Manually verify in the browser**

Navigate to `http://localhost:3001/regime` → CRI sub-tab. Verify:
- Trend Break card shows "Pullback: -1.97% from 20d high"
- Prior-day dot positions on each ComponentBar look reasonable (no jumps of >5 points between today and yesterday on calm days)

- [ ] **Step 7.7: Commit**

```bash
git add web/components/regime/CriSubTab.tsx web/tests/unit/CriSubTab.priorScore.test.tsx web/app/globals.css src/uw_scan/cards/cri_scoring.py src/uw_scan/api/schemas.py tests/unit/test_cri_scoring.py
git commit -m "feat(regime-ui): align priorComponentScore with v3 calibration; surface tactical pullback"
```

---

## Task 8 — Live verification: today's CRI lands in 10-15 range

**No file changes** — runtime check only.

- [ ] **Step 8.1: Trigger a fresh CRI snapshot**

Run: `curl -X POST http://localhost:8400/jobs/cri_full_scan` (or trigger via /admin in the web UI).

- [ ] **Step 8.2: Query DB for today's snapshot**

`CriSnapshotRepository` requires `(conn, schema=...)` — there is no zero-arg constructor. Open a connection first:

```bash
uv run python -c "
import json, psycopg
from uw_scan.config import Settings
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
with psycopg.connect(Settings().db_dsn) as conn:
    repo = CriSnapshotRepository(conn, schema='uw_scan')
    snap = repo.fetch_latest()
    payload = snap['payload'] if 'payload' in snap else snap
    print('score:', payload['cri']['score'])
    print('level:', payload['cri']['level'])
    print('composite_version:', payload['cri'].get('composite_version'))
    print('components:', json.dumps(payload['cri']['components'], indent=2))
    print('pullback_20d_pct:', payload.get('pullback_20d_pct'))
    print('vix_delta_3d:', payload.get('vix_delta_3d'))
"
```

If `Settings().db_dsn` differs in this repo (it's `Settings.from_env()` or a named property), adapt — but always go through a real connection, never the zero-arg constructor.

**Expected ranges:**
- `score`: 10 ≤ score ≤ 15 (target ~13)
- `level`: "LOW"
- `composite_version`: 3
- `components.momentum`: ~4.9 (was 0.0)
- `components.vix`: ~2.8 (was 1.9)
- `components.vvix`: ~4.3 (was 3.1)
- `pullback_20d_pct`: ~-1.97 (negative)
- `vix_delta_3d`: ~+0.80 (positive)

- [ ] **Step 8.3: If actual score outside 10-15:**

- If too low (<10): user wants more sensitivity — narrow VIX RoC denom further (40 → 35) and re-run Task 4 gate.
- If too high (>15): user wanted ≤ 15 — widen pullback saturation (-4% → -5%) and re-run Task 4 gate.
- Document the actual landed score in the PR description.

- [ ] **Step 8.4: Sanity-check UI**

Navigate to `http://localhost:3001/regime` → CRI sub-tab. Verify in the browser:

1. Hero score matches DB (~13)
2. Components panel shows updated values
3. Trend Break subtext: "Pullback: -1.97% from 20d high"
4. Mean-reversion row shows 4 tiles (VRP, VIX Z, VIX/VIX3M, **VIX Δ (3d)**)
5. Guidance panel still renders (no regression)

---

## Task 9 — Run full test suite + push

- [ ] **Step 9.1: Python tests**

Run: `uv run pytest`
Expected: all passed (target: 740+ tests).

- [ ] **Step 9.2: Vitest**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run test`
Expected: all passed.

- [ ] **Step 9.3: Type check + lint (web)**

Run: `npm --prefix /Users/chenxi/projects/unusual-whales/web run typecheck && npm --prefix /Users/chenxi/projects/unusual-whales/web run lint`
Expected: no errors.

- [ ] **Step 9.4: Push branch and rewrite the PR description**

Run: `git push origin feat/cri-methodology-tune`

The push extends PR #58, which now carries: SPX-over-SPY preference, mean-reversion fields, guidance endpoint with AST whitelist, validation endpoint, v3 recalibration, tactical pullback sub-score, VIX velocity tile, methodology rewrite, and OOS gate test. This is a large PR — to keep it reviewable, rewrite the description with **three labelled sections and a per-commit reading order**:

```markdown
## v2 — SPX preference + mean-reversion fields (commits: <sha>...<sha>)
- ...

## v3 — Calibration (commits: <sha>...<sha>)
- VIX floor 15→13, RoC denom 60→40
- VVIX floor 85→80
- Module split: scorers extracted to `cri_scorers.py`

## v3 — Tactical pullback + VIX velocity tile (commits: <sha>...<sha>)
- Trend Break reshape (structural-15 + tactical-10)
- 4th mean-reversion tile (VIX Δ 3d)
- `priorComponentScore` aligned with v3 across all 4 slots
- OOS gate test: `tests/integration/regime/test_cri_oos_gate.py`

## Verification
- Today's CRI: <landed score>/100 LOW (was 6 pre-v3)
- OOS AUC vs v1: dd5 <measured>, dd10 <measured>
- See `docs/research/regime/oos-summary.json` for the authoritative table.

**Reviewing in <X> minutes**: read the three sections in order. Each commit on the branch maps to exactly one section.
```

Use `gh pr edit 58 --body-file <(cat ...)` or the GH web UI to apply.

- [ ] **Step 9.5: `/codex-review` final pass before merge**

Per cross-project convention, run `/codex-review` on the diff before merging.

---

## Done criteria

All checked when:
- [ ] All Python + Vitest tests pass
- [ ] OpenAPI snapshot reflects 3 new fields, no other changes
- [ ] OOS gate passed (v3 AUC ≥ v1 on dd5 AND dd10)
- [ ] Live snapshot in DB shows `composite_version=3`, score 10-15, momentum > 0
- [ ] Browser confirms 4 mean-reversion tiles + tactical pullback line
- [ ] PR #58 updated with v3 section
- [ ] `/codex-review` clean
- [ ] User explicitly asks to merge before merging
