# VCG v2 — Cascade and absolute-vol-stress recalibration

**Status:** Draft for review — 2026-05-27
**Author:** chenxi (with Claude Opus 4.7 as drafting assistant)
**Targets:** `src/uw_scan/cards/vcg_scoring.py` v1 → v2 (`COMPOSITE_VERSION = 1 → 2`)
**Evidence:** `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md` (forensic audit, on `feat/vcg-stress-window-forensics`)
**Methodology contract:** `docs/research/regime/vcg-methodology.md:308` requires this spec + `COMPOSITE_VERSION` bump + §3 / §7 doc updates in the same commit.

---

## 1. Goal

**Eliminate the highest-severity contradiction in the VCG payload**: rows where `regime="PANIC"` and `interpretation="SUPPRESSED"` co-occur. v2 is a **payload semantic consistency fix**, not a VCG predictive-performance optimization. If crisis-window recall improves as a side effect, that is welcome but not the success bar — and v2 must not make recall worse (see §5).

The forensic audit at `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md` documents 36 such contradiction days across 7 named-crisis windows. Root cause: the cascade at `src/uw_scan/cards/vcg_scoring.py:289-304` evaluates `not sign_ok → SUPPRESSED` (line 291) *before* `pi >= 1.0 → PANIC` (line 293), so failed regression sign-discipline structurally pre-empts the panic gate.

v2 fixes that one ordering bug and adds a second, percentile-based override (`vol_extreme → RISK_OFF`) that fires regardless of regression health. The cascade still allows `interpretation="SUPPRESSED"` to overwrite RISK_OFF / EDR / WATCH (flag-based) labels when `sign_ok=False` — that is **intentionally retained from v1**; deciding whether sign-failure should be allowed to suppress those lower-tier stress labels is the v2.1 sign-discipline question, not v2's scope.

## 2. Context — why v2

VCG v1 (port from xenon `d3cbc08`) treats failed regression sign-discipline as a label-rewriting gate: when `β₁_vvix > 0` or `β₂_vix > 0`, the interpretation is forced to `SUPPRESSED` regardless of every other signal in the payload. The audit shows this is mechanically counter-productive during stress windows:

- **β₁_vvix flips positive on 292 of 297 (98.3%) sign-failure mismatch days within crisis windows.** The 21-day OLS window absorbs early-stress days where VVIX leads credit, inverting the slope and triggering the SUPPRESSED label exactly when the underlying market state is most stressed.
- **36 days within crisis windows simultaneously produce `regime="PANIC"` and `interpretation="SUPPRESSED"`.** Two payload fields, one row, contradictory readings — externally indistinguishable from a bug.
- **Net effect on truth-set recall:** 52 of 528 truth-stress days (9.8%) flagged as VCG-stress; the rest are SUPPRESSED-overwritten (297 / 476 mismatch days, 62.4%) or fall-through NORMAL (179 / 476, 37.6%).

The candidate calibration items in `vcg-methodology.md:298-308` and `vcg-next-steps-2026-05-26.md:78-90` (window length, β-band, ensemble proxies, regime-aware floors) are **separate concerns** addressing the same indicator's *thresholds*. v2 targets the *cascade structure* — the audit's structural finding. Threshold work is deferred to v2.1.

## 3. In scope

1. **Cascade reorder.** Move `pi_panic ≥ 1.0 → PANIC` ahead of `not sign_ok → SUPPRESSED` in `_interpretation_for_index` (`vcg_scoring.py:289-304`).
2. **New absolute-vol-stress override gate.** Add `vix_percentile_rank ≥ 0.95 AND vvix_percentile_rank ≥ 0.95 → RISK_OFF` as the second cascade branch, immediately after the PANIC gate and before the SUPPRESSED gate. RISK_OFF (not EDR) because v2's gate is a tighter subset of truth-labeler RISK_OFF on the same inputs; see §6.1 for justification.
3. **Two new payload fields.** `vix_percentile_rank` and `vvix_percentile_rank`, both `float | None`, computed as 252-day rolling percentile ranks with `tie_rule="strict_lt"` (matches `docs/research/regime/ground-truth-labels/level1-thresholds.yaml`). They must be computed in both `compute_vcg` and the research-only `_compute_vcg_from_returns` path used by composite backtests.
4. **`COMPOSITE_VERSION = 1 → 2`** in `vcg_scoring.py`.
   - Also update the nearby research-channel comment that currently says production `COMPOSITE_VERSION` stays at `"1"` indefinitely; after v2, that comment must become version-neutral.
5. **Methodology-doc updates** (mandated by `vcg-methodology.md:308`):
   - `vcg-methodology.md` §2.5 — rewrite cascade order.
   - `vcg-methodology.md` §2.6 — new section: absolute-vol-stress override (semantics, thresholds, window).
   - `vcg-methodology.md` §3 — append v2 constants block (`VIX_PCT_PANIC`, `VVIX_PCT_PANIC`, `VOL_PERCENTILE_WINDOW`, `VOL_PERCENTILE_TIE_RULE`) with rationale.
   - `vcg-methodology.md` §7 — v2 entry (replacing the existing "v2 (TBD)" stub) recording the new cascade and constants.
   - `docs/research/regime/CLAUDE.md` "When to update" trigger list — add the new constants.
6. **Tests.**
   - Unit tests in `tests/unit/cards/test_vcg_scoring_v2_cascade.py` covering every cascade branch (one test per branch), percentile alignment, and the new vol-extreme NaN guard.
   - Unit tests in `tests/unit/test_backtest_vcg_daily_payloads.py` covering persisted daily payload fields used by the acceptance SQL.
   - Integration acceptance test `tests/integration/regime/test_vcg_v2_contradiction.py` that runs the v2 scorer end-to-end against a 7-crisis fixture and asserts `COUNT(*) WHERE regime='PANIC' AND interpretation='SUPPRESSED' = 0`.
   - OpenAPI snapshot regeneration (`tests/integration/api/openapi.snapshot.json`).
7. **v2 backfill script** `scripts/backfill_vcg_v2.py` (wrapper around the existing `scripts/backtest_vcg.py` entry, with the contract specified in §9.2).
8. **One UI string correction** in `web/components/regime/VcgSubTab.tsx:323-326` — 3-line update to remove a hardcoded "SUPPRESSED" narration that becomes misleading once v2 ships (see §11).

## 4. Out of scope (v2.1+ candidates)

These are real items already enumerated in `vcg-methodology.md:298-308` and `vcg-next-steps-2026-05-26.md:78-90`. The audit's success bar (`§5` below) does NOT require any of them. Each gets its own future spec and PR:

- `OLS_WINDOW` length sensitivity (21 / 42 / 63) and any change to the regression window.
- β-band relaxation (`β < +0.01` instead of `β ≤ 0`).
- Regime-aware `VIX_FLOOR`.
- Continuous panic-π function (replacing the binary clamp at lines 40-42).
- Ensemble proxy support (HYG + JNK consensus).
- Symmetric WATCH/EDR/BOUNCE thresholds across positive and negative VCG.
- UI redesign of `web/components/regime/VcgSubTab.tsx` beyond the additive-field surface and the in-scope 3-line string fix in §11.
- Tile rendering of the new `vix_percentile_rank` / `vvix_percentile_rank` fields (they ship in the payload + generated types; rendering is a v2.1 UI item).
- Whether to allow `sign_ok=False` to overwrite `RISK_OFF` / `EDR` / `WATCH` flag-based labels (v1 behavior retained in v2; the broader sign-discipline rethink is the v2.1 sign-discipline question).
- Archiving v=1 `regime_backtest_runs` rows via migration 060's `archived_at` column.

## 5. Acceptance criteria

Two gating bars. Both must hold on the same v=2 backtest row for v2 to ship.

### Gate 1 — Zero PANIC-SUPPRESSED contradictions

```sql
SELECT COUNT(*) FROM uw_scan.regime_backtest_daily
WHERE run_id = <v2_run_id>
  AND payload->>'regime' = 'PANIC'
  AND payload->>'interpretation' = 'SUPPRESSED';
```

Expected: **0**. Wrapped by `tests/integration/regime/test_vcg_v2_contradiction.py::test_vcg_v2_produces_zero_panic_suppressed_contradictions`.

Precondition: the v2 backtest must persist `payload.interpretation` on every `regime_backtest_daily` row. The test first asserts `COUNT(*) WHERE payload->>'interpretation' IS NULL = 0` for the v2 run; otherwise the contradiction query can return zero by querying missing JSON keys instead of real labels.

Other regime/interpretation pairings (e.g., `regime='DIVERGENCE' AND interpretation='RISK_OFF'`) are NOT contradictions — `regime` is a model-state descriptor (DIVERGENCE / TRANSITION / PANIC, keyed on `pi`), not a stress-level label. The only structural contradiction is PANIC-regime + SUPPRESSED-interpretation, because they reference the same panic-π evidence with opposite verdicts.

### Gate 2 — Crisis-window stress recall non-regression

```sql
-- v2 recall on the 7-crisis fixture
SELECT
  COUNT(*) FILTER (WHERE payload->>'interpretation' IN ('WATCH','EDR','RISK_OFF','PANIC','BOUNCE'))::float
    / COUNT(*) FILTER (WHERE truth_status IN ('EDR','RISK_OFF','PANIC')) AS v2_recall
FROM uw_scan.regime_backtest_daily v2_row
JOIN <truth_fixture_rows> truth
  ON truth.trade_date = v2_row.trade_date
WHERE v2_row.run_id = <v2_run_id>
  AND truth.crisis_window IS NOT NULL;
```

**v1 baseline (from forensic audit, fixed): `52 / 528 = 0.0985`.** v2 must produce recall ≥ this value. Wrapped by `tests/integration/regime/test_vcg_v2_recall_non_regression.py::test_v2_does_not_reduce_crisis_recall`.

A v2 implementation that "fixes" the contradiction by reclassifying everything to NORMAL would pass Gate 1 but fail Gate 2. Gate 2 forces v2 to preserve v1's existing stress-detection where it was correct, while removing the contradiction days.

### Where `<v2_run_id>` comes from

`scripts/backfill_vcg_v2.py` (§9.2) produces a `regime_backtest_runs` row with `composite_version=2`, `run_scope='production'`, `credit_proxy='HYG'`, `composite_method='single_proxy'` against the target DB's available `vol_index_daily` history. The integration tests produce their own v2 run from the committed warmup-bounded 7-crisis fixture; they use the truth-label parquet's `crisis_window` column for Gate 2 filtering.

### Secondary measurements (reported, not gated)

- Cohen's κ for VCG-vs-truth classification on the 7-crisis windows. v1 baseline per audit: 0.0124. v2 result: reported in PR description.
- Distribution of new `interpretation` values across crisis windows (count by class). Compared against the v1 distribution in the audit's Table 2.
- v=2 row count breakdown by interpretation, for the methodology-doc §3.1 empirical-distribution update.

## 6. Architecture

### 6.1 Cascade structure (the only logic change)

The new cascade replaces `_interpretation_for_index` lines 289-304 in `vcg_scoring.py`. Existing flag computation (`_signal_for_index`) and `regime` field (lines 281-286) are unchanged.

```python
# NEW: percentile-extreme check uses 252-day rolling rank of vix/vvix levels.
vix_percentile_rank = float(model["vix_percentile_rank"][idx])
vvix_percentile_rank = float(model["vvix_percentile_rank"][idx])
vol_extreme = (
    not math.isnan(vix_percentile_rank) and vix_percentile_rank >= VIX_PCT_PANIC
    and not math.isnan(vvix_percentile_rank) and vvix_percentile_rank >= VVIX_PCT_PANIC
)

# REWRITTEN cascade (lines 289-304 in v1):
if math.isnan(vcg_val):
    interpretation = "INSUFFICIENT_DATA"
elif pi_val >= 1.0:                                  # MOVED UP from v1 line 293
    interpretation = "PANIC"
elif vol_extreme:                                    # NEW branch
    interpretation = "RISK_OFF"
elif not flags["sign_ok"]:                           # demoted in priority (was line 291)
    interpretation = "SUPPRESSED"
elif flags["ro"]:
    interpretation = "RISK_OFF"
elif flags["edr"]:
    interpretation = "EDR"
elif flags["bounce"]:
    interpretation = "BOUNCE"
elif not math.isnan(vcg_adj_val) and vcg_adj_val > VCG_TRIGGER:
    interpretation = "WATCH"
else:
    interpretation = "NORMAL"
```

**Precedence rationale (top → bottom):**

1. `INSUFFICIENT_DATA` — data-quality guard, unchanged.
2. `PANIC` — strongest single-signal evidence (pi-clamped extreme vol).
3. `RISK_OFF` (vol-extreme override) — both VIX and VVIX in the historical top 5%; independent of regression health.
4. `SUPPRESSED` — data-quality flag for regression breakage; demoted below the two strongest stress signals.
5. `RISK_OFF` (flag-based) / `EDR` / `BOUNCE` / `WATCH` / `NORMAL` — multi-condition flag layer, unchanged.

When both `pi ≥ 1.0` and `vol_extreme` are true, PANIC wins by cascade order (intentional: panic-π is the stronger evidence — it incorporates the regression's prediction; vol-extreme is a raw historical-rank statement).

**Why `vol_extreme → RISK_OFF` (not EDR):** The truth labeler at `cards/regime_classification_labels.py:84` defines RISK_OFF as `credit_pct >= 0.80 OR (vix_pct >= 0.80 AND vvix_pct >= 0.80)`. v2's `vol_extreme` uses `vix_pct >= 0.95 AND vvix_pct >= 0.95` — a **tighter subset** of truth-RISK_OFF on the same inputs. By construction, every day v2 fires `vol_extreme → RISK_OFF` is also a day the truth labeler would call RISK_OFF (or PANIC if `vix+rv` both hit 0.95). The label is structurally aligned with the truth schema, not a semantic stretch. EDR was the wrong choice in earlier drafts because v1's existing `flags["edr"]` is drawdown-conditional; reusing the EDR label for a vol-percentile-only trigger would conflate two distinct criteria.

### 6.2 New constants

Added to `vcg_scoring.py` immediately after `VVIX_ELEVATED` (line 48):

```python
VIX_PCT_PANIC = 0.95            # Absolute-vol override: VIX percentile rank cutoff
VVIX_PCT_PANIC = 0.95           # Absolute-vol override: VVIX percentile rank cutoff
VOL_PERCENTILE_WINDOW = 252     # Rolling window for absolute-vol percentile rank
                                # (matches level1-thresholds.yaml `rolling_window_days`)
VOL_PERCENTILE_TIE_RULE = "strict_lt"  # Cohort comparison tie semantics
                                       # (matches level1-thresholds.yaml `percentile_tie_rule`)
```

**Why these specific values:**

- `0.95` matches `level1-thresholds.yaml` `P_PANIC` — the same cutoff the truth labeler uses for its PANIC class on the same `vix_pct` input. The override gate is structurally aligned with the highest-tier stress threshold in the ground-truth schema. The audit's deep-dive recommendations also converged on 0.95 (`forensics-2026-05-26.md` §7).
- `252` matches `level1-thresholds.yaml` `rolling_window_days` — one trading year, the same window every Level-1 percentile in the codebase already uses.
- `"strict_lt"` matches `level1-thresholds.yaml` `percentile_tie_rule` — explicit semantic alignment with `compute_rolling_percentile_rank` (defined at `cards/regime_classification_labels.py:29-60`).

### 6.3 New payload fields

`_interpretation_for_index` returns two additional fields:

```python
"vix_percentile_rank": _round_or_none(vix_percentile_rank, 4),
"vvix_percentile_rank": _round_or_none(vvix_percentile_rank, 4),
```

These are placed adjacent to the existing `vix` / `vvix` level fields (around line 314 in v1). They DO NOT replace or rename the existing `attribution.vix_pct` / `attribution.vvix_pct` fields, which retain their v1 meaning (% of the model's prediction attributable to each covariate).

Pydantic model `VcgSignal` in `src/uw_scan/api/schemas.py` gains:

```python
vix_percentile_rank: float | None = Field(
    default=None,
    description="VIX level's 252-day rolling percentile rank (strict_lt tie rule). "
                "Used by the v2 absolute-vol-stress override gate. NaN/None during "
                "the 252-bar warmup."
)
vvix_percentile_rank: float | None = Field(
    default=None,
    description="VVIX level's 252-day rolling percentile rank (strict_lt tie rule)."
)
```

### 6.4 Percentile computation

Inside `compute_vcg`, compute ranks on the raw N-length VIX/VVIX level inputs, then slice `[1:]` to align with the function's existing N-1 return/model arrays:

```python
from uw_scan.cards.regime_classification_labels import compute_rolling_percentile_rank

vix_rank_full = compute_rolling_percentile_rank(
    pd.Series(vix_prices),
    window=VOL_PERCENTILE_WINDOW,
    tie_rule=VOL_PERCENTILE_TIE_RULE,
)
vvix_rank_full = compute_rolling_percentile_rank(
    pd.Series(vvix_prices),
    window=VOL_PERCENTILE_WINDOW,
    tie_rule=VOL_PERCENTILE_TIE_RULE,
)
vix_percentile_rank = vix_rank_full.iloc[1:].to_numpy()
vvix_percentile_rank = vvix_rank_full.iloc[1:].to_numpy()
```

Inside `_compute_vcg_from_returns`, compute ranks on the already-aligned N-length `vix_levels` / `vvix_levels` inputs and do **not** slice:

```python
vix_percentile_rank = compute_rolling_percentile_rank(
    pd.Series(vix_levels),
    window=VOL_PERCENTILE_WINDOW,
    tie_rule=VOL_PERCENTILE_TIE_RULE,
).to_numpy()
vvix_percentile_rank = compute_rolling_percentile_rank(
    pd.Series(vvix_levels),
    window=VOL_PERCENTILE_WINDOW,
    tie_rule=VOL_PERCENTILE_TIE_RULE,
).to_numpy()
```

Computed once per model-build call and cached on the model dict alongside `residuals`, `beta1`, etc. — same pattern as v1's existing model-build phase.

**Cross-card import is intentional.** `cards/CLAUDE.md` does not prohibit cross-card imports (only DB access and float arithmetic on price-shaped data). `compute_rolling_percentile_rank` is already a stable, tested utility in `regime_classification_labels.py` with the exact strict_lt semantics required. Moving it to `cards/derive.py` is deferred until a third caller appears (rule of three).

## 7. Data flow & invariants

**Compute path:**

```
worker (scanners/vcg.py)  /  backtest (scripts/backtest_vcg.py)
                 │
                 ▼
        compute_vcg(vix_prices, vvix_prices, credit_prices)
        or _compute_vcg_from_returns(... already-aligned arrays ...)
                 │
                 ▼ build model dict (one pass):
                 │   residuals, beta1, beta2, alpha, vcg, vcg_adj, pi   ← v1
                 │   vix_percentile_rank, vvix_percentile_rank                        ← v2 NEW
                 ▼
        evaluate_signal → _interpretation_for_index(model, idx)
                 │
                 ▼ cascade fires per §6.1
                 ▼
        payload returned with all v1 fields + vix_percentile_rank + vvix_percentile_rank
                 │
                 ▼
        consumers (read-only):
          • backtest_vcg.py persists JSONB to regime_backtest_daily.payload
          • /api/regime/vcg returns the payload
          • web/components/regime/VcgSubTab.tsx renders payload.interpretation
          • backtest_vcg.py writes regime_backtest_daily rows
```

**Invariants:**

| Invariant | Why it holds | Enforcement |
|---|---|---|
| `regime = "PANIC" ⇒ interpretation = "PANIC"` | Cascade branch 2 fires before any sign_ok or vol-extreme check | Unit test `test_cascade_panic_fires_when_pi_high_even_if_sign_failed` |
| **Percentile-rank arrays are index-aligned to `model["vcg"]`, not to raw input levels** | Caller-side responsibility (see §7.1 "Array alignment" below); ranks computed against the same level series the rest of the model uses | Unit test `test_percentile_rank_arrays_align_with_vcg_array` |
| Until 252 valid bars accumulate, `vix_percentile_rank` and `vvix_percentile_rank` are NaN | `compute_rolling_percentile_rank` returns NaN for under-warmed bars; alignment preserves NaN positions | Existing helper behavior + alignment test |
| `vol_extreme` is False whenever either percentile rank is NaN | Explicit `not math.isnan(...)` guards in the `vol_extreme` boolean | Unit test `test_cascade_warmup_nan_percentile_does_not_fire_override` |
| `MIN_BARS` (94) is below the 252-bar percentile warmup | True by inspection (`OLS_WINDOW + Z_WINDOW + 10 = 21 + 63 + 10 = 94`) | Bars 95–251 produce non-NaN VCG but NaN percentile ranks; cascade behaves as "v1 + PANIC-reorder" in that interval. Production backtests start 2007-01-03 (per `level1-thresholds.yaml`); warmup is fully past by 2008. |
| The `regime` field is bit-for-bit identical to v1 on every bar | Lines 281-286 untouched | Unit test `test_regime_field_unchanged_from_v1`, golden v1/v2 fixture comparison |
| New payload fields serialize as JSON null when underlying value is NaN | FastAPI default for `float \| None` Pydantic fields | OpenAPI snapshot + Pydantic validation test `test_vcg_payload_accepts_v1_without_percentiles_and_v2_with` |

### 7.1 Array alignment (high implementation risk)

The single most error-prone aspect of v2 is **keeping the new percentile-rank arrays index-aligned with `model["vcg"]`**.

v1's `compute_vcg` mixes input arrays of different lengths:
- Raw input levels (`vix_levels`, `vvix_levels`, `credit_levels`) have length `N`.
- Return-based series (`vix_ret`, `vvix_ret`, `credit_ret`, `residuals`, `vcg`, `vcg_adj`, `pi`) have length `N-1` (or are NaN-leading at index 0).
- `_interpretation_for_index(model, idx)` accesses `model[key][idx]` uniformly — caller assumes all keys are co-indexed.

**Invariant the spec requires:** after building the percentile-rank arrays, the implementation MUST guarantee:

```python
assert len(model["vix_percentile_rank"]) == len(model["vcg"])
assert len(model["vvix_percentile_rank"]) == len(model["vcg"])
```

**How to satisfy it:**

```python
# compute_vcg: raw price inputs are length N, model arrays are length N-1.
vix_rank_full = compute_rolling_percentile_rank(
    pd.Series(vix_prices), window=VOL_PERCENTILE_WINDOW, tie_rule=VOL_PERCENTILE_TIE_RULE
)
model["vix_percentile_rank"] = vix_rank_full.iloc[1:].to_numpy()

# _compute_vcg_from_returns: all inputs are already aligned, so no slice.
model["vix_percentile_rank"] = compute_rolling_percentile_rank(
    pd.Series(vix_levels), window=VOL_PERCENTILE_WINDOW, tie_rule=VOL_PERCENTILE_TIE_RULE
).to_numpy()
```

Add separate alignment tests for both paths. A conditional "slice if lengths differ" helper is acceptable only if tests prove both the single-proxy N-1 path and the composite already-aligned path remain correct.

**Required tests for alignment:**

1. `test_percentile_rank_arrays_align_with_vcg_array` — synthetic 300-bar input series; assert `len(model["vix_percentile_rank"]) == len(model["vcg"]) == len(model["vvix_percentile_rank"])`.
2. `test_first_finite_percentile_rank_is_at_warmup_boundary` — assert the path-specific first finite index: `compute_vcg` first finite rank lands at model index 250 after the `[1:]` slice; `_compute_vcg_from_returns` first finite rank lands at model index 251 because no slice occurs. All earlier indices are NaN.
3. `test_percentile_rank_value_at_known_bar` — fixture with a hand-computed expected rank (e.g., monotonically-increasing series of length 300 → rank at bar 252 should be 1.0 with strict_lt). Catches misalignment that off-by-one tests would miss when arrays happen to be the right length but offset.
4. `test_percentile_rank_arrays_align_in_compute_vcg_from_returns` — aligned N-length level/return arrays through the composite helper; assert no `[1:]` trim occurs and lengths match `model["vcg"]`.

Without these tests, v2 can "look correct" (length checks pass, values are floats) while feeding the cascade ranks from the wrong calendar dates. Misalignment by even one bar invalidates the entire absolute-vol gate.

**No DB migration:** `regime_backtest_runs.composite_version` already keys on the constant; a new v=2 row appears automatically when the v=2 backtest persists. `regime_backtest_daily.payload` is JSONB — new keys flow in without DDL.

## 8. Testing strategy

### 8.1 Unit tests — `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

**Cascade-branch tests** (one per branch, synthetic model dicts, no market data):

| Test | Synthetic inputs | Expected `interpretation` |
|---|---|---|
| `test_cascade_panic_fires_when_pi_high_even_if_sign_failed` | `pi=1.5, sign_ok=False, vol_extreme=False, vcg=non-NaN` | `"PANIC"` |
| `test_cascade_vol_extreme_overrides_sign_failure` | `pi=0.5, sign_ok=False, vix_pct=0.97, vvix_pct=0.96` | `"RISK_OFF"` |
| `test_cascade_vol_extreme_only_one_side_does_not_override` | `pi=0.5, sign_ok=False, vix_pct=0.97, vvix_pct=0.85` | `"SUPPRESSED"` |
| `test_cascade_pi_panic_outranks_vol_extreme` | `pi=1.2, sign_ok=False, vix_pct=0.99, vvix_pct=0.99` | `"PANIC"` |
| `test_cascade_warmup_nan_percentile_does_not_fire_override` | `pi=0.5, sign_ok=False, vix_pct=NaN, vvix_pct=NaN` | `"SUPPRESSED"` |
| `test_cascade_insufficient_data` | `vcg=NaN` | `"INSUFFICIENT_DATA"` |
| `test_cascade_normal_path_unchanged_from_v1` | All-clear: `pi=0.3, sign_ok=True, vol_extreme=False, no flags, vcg_adj=1.0` | `"NORMAL"` |
| `test_composite_version_is_two` | (constant check) | `vcg_scoring.COMPOSITE_VERSION == 2` |

**Array-alignment tests** (high-priority, prevent off-by-one):

| Test | Setup | Assertion |
|---|---|---|
| `test_percentile_rank_arrays_align_with_vcg_array` | Synthetic 300-bar level + return inputs | `len(model["vix_percentile_rank"]) == len(model["vcg"]) == len(model["vvix_percentile_rank"])` |
| `test_first_finite_percentile_rank_is_at_warmup_boundary` | 300-bar monotonic VIX series | First non-NaN `vix_percentile_rank` index matches the implementation-pinned warmup boundary; all indices before that are NaN |
| `test_percentile_rank_value_at_known_bar` | Monotonically-increasing 300-bar VIX series; cohort known | At the first post-warmup bar, `vix_percentile_rank == 1.0` (today exceeds all 251 prior cohort members under strict_lt) |
| `test_percentile_rank_arrays_align_in_compute_vcg_from_returns` | Already-aligned N-length level/return arrays for the composite helper | Percentile arrays stay length N, are not sliced `[1:]`, and first finite rank lands at index 251 |

**Regime-field invariance test** (catch accidental regression):

| Test | Setup | Assertion |
|---|---|---|
| `test_regime_field_unchanged_from_v1` | Golden fixture: a 50-row CSV with hand-computed v1 `regime` values for `(pi, vcg)` combinations | For every row, `_interpretation_for_index(...)["regime"]` matches the golden v1 column |

**Pydantic model tests** (`tests/unit/api/test_models_regime.py`):

| Test | Setup | Assertion |
|---|---|---|
| `test_vcg_payload_accepts_v1_without_percentiles` | Sample v=1 payload dict (no `vix_percentile_rank`, no `vvix_percentile_rank`) | `VcgSignal.model_validate(payload)` succeeds; new fields default to `None` |
| `test_vcg_payload_accepts_v2_with_percentiles` | Sample v=2 payload dict with `vix_percentile_rank=0.97, vvix_percentile_rank=0.96` | `VcgSignal.model_validate(payload)` succeeds; fields round-trip |
| `test_vcg_payload_accepts_v2_with_nan_percentiles_as_null` | v=2 payload with `vix_percentile_rank=None` (NaN serializes as null) | Validates; `model.vix_percentile_rank is None` |

### 8.2 Integration acceptance tests — `tests/integration/regime/`

Three integration tests, one per acceptance gate plus one for API selection.

**Test 1 — `test_vcg_v2_contradiction.py::test_vcg_v2_produces_zero_panic_suppressed_contradictions`** (Gate 1):

```python
def test_vcg_v2_produces_zero_panic_suppressed_contradictions(seeded_db_empty_cards):
    # 1. Load contiguous warmup+crisis fixture into long-form vol_index_daily.
    # 2. Invoke backtest_vcg subprocess with UW_SCAN_DB_NAME/host env from repo.conn.
    # 3. Query: COUNT(*) WHERE payload->>'regime'='PANIC' AND payload->>'interpretation'='SUPPRESSED'
    # 4. Assert payload.interpretation is non-null for all v2 rows, then assert count == 0.
```

**Test 2 — `test_vcg_v2_recall_non_regression.py::test_v2_does_not_reduce_crisis_recall`** (Gate 2):

```python
def test_v2_does_not_reduce_crisis_recall(seeded_db_empty_cards):
    # 1. Same fixture as Test 1.
    # 2. Run backtest_vcg → produces v=2 row.
    # 3. v1 baseline is hardcoded constant V1_CRISIS_RECALL_BASELINE = 0.0985 (52/528),
    #    captured from the audit and recorded in the test file as the source of truth.
    # 4. Join committed truth-label parquet to persisted v2 daily rows in memory.
    # 5. Compute v2 recall on crisis truth-stress days: COUNT(stress interpretations) / COUNT(truth-stress days).
    # 6. Assert: v2_recall >= V1_CRISIS_RECALL_BASELINE.
```

The v1 baseline is a frozen constant rather than a re-derived value — it must NOT be re-computed at test time, because doing so would silently accommodate drift. If the audit's baseline number is wrong, that gets fixed in the audit (which has its own PR), not here.

**Test 3 — `test_vcg_v2_api_selection.py::test_default_validation_selects_v2_after_bump`** (covers MUST #5):

```python
def test_default_validation_selects_v2_after_bump(seeded_db_empty_cards):
    # 1. Seed two production rows in regime_backtest_runs:
    #    - composite_version=1, credit_proxy='HYG', composite_method='single_proxy', run_scope='production'
    #    - composite_version=2, credit_proxy='HYG', composite_method='single_proxy', run_scope='production'
    # 2. Confirm vcg_scoring.COMPOSITE_VERSION == 2 (post-bump).
    # 3. Call the production-default selector (the repository helper that backs /api/regime/vcg-validation).
    # 4. Assert: returned dict has composite_version == "2".
    # 5. Seed a research v=2 row (run_scope='research') and re-run.
    # 6. Assert: production selector still returns the production v=2 row, not the research v=2 row.
```

### Fixture

`tests/integration/regime/fixtures/seven_crisis_vol_complex.parquet`, derived once from production `vol_index_daily` long-form rows for `symbol IN ('VIX','VVIX','SPX','HYG')`. It stores the contiguous warmup-bounded range from earliest crisis start minus warmup through latest crisis end, plus a `crisis_window` marker. Do not slice only crisis-window rows; rolling 21/63/252-day state would become wrong across gaps. Generation script lives at `scripts/build_vcg_v2_test_fixture.py` and is documented in `tests/integration/regime/fixtures/README.md`.

Uses real `pytest-postgresql` per `src/uw_scan/CLAUDE.md` ("No fake cursors / mocked DB in integration tests").

### 8.3 OpenAPI snapshot — `tests/integration/api/openapi.snapshot.json`

The `VcgSignal` model surface gains two `float | None` optional fields. The current snapshot test has no update flag; regenerate `tests/integration/api/openapi.snapshot.json` by serializing `TestClient(app).get("/openapi.json").json()` from `uw_scan.api.server`. The snapshot diff should be additive-only (no removed or renamed fields). PR reviewer verifies the snapshot diff is purely additive before merge.

`web/lib/types.ts` regenerates via `cd web && npm run gen:types`, which reads `http://127.0.0.1:8400/openapi.json`; start only the API (`uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400`) or use an already-running API. The generated diff is committed in the same PR.

## 9. Rollout & operational handling

### 9.1 The 503 hazard

`/api/regime/vcg-validation` returns **503** when no completed `regime_backtest_runs` row exists at the current `composite_version` (per `closure-2026-05-24.md`). Bumping `COMPOSITE_VERSION = 2` at deploy time creates a gap: until a v=2 backtest persists, the endpoint 503s and `/regime` → Validation tab fails.

### 9.2 Policy: deploy-and-immediately-backfill

The PR that bumps `COMPOSITE_VERSION` MUST include in the same merge:

1. Code change (cascade rewrite + percentile compute + new constants + new payload fields).
2. Methodology-doc updates per §3 of this spec (mandated by `vcg-methodology.md:308`).
3. `scripts/backfill_vcg_v2.py` — wraps `scripts/backtest_vcg.py` and persists a v=2 row in `regime_backtest_runs`.
4. Runbook entry in the PR description: *"Merge → run `uv run scripts/backfill_vcg_v2.py` with target `UW_SCAN_DB_NAME`/host/user/password env → verify `/api/regime/vcg-validation` returns 200 with `composite_version=2` metadata."*

**Backfill script contract** (specced here, implementation pinned by impl plan):

```python
def main():
    # 1. Runtime-check the constant is at v2, refusing to run against a pre-bump build.
    from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION
    if COMPOSITE_VERSION != 2:
        raise RuntimeError(f"COMPOSITE_VERSION must be 2 to run v2 backfill; got {COMPOSITE_VERSION}")

    # 2. Idempotency: if a completed production v=2 row already exists, exit 0 (unless --force).
    existing = repo.find_latest_run(
        "vcg",
        composite_version="2",
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    if existing and not args.force:
        print(f"v=2 production row already exists (run_id={existing['id']}); use --force to re-run.")
        return 0

    # 3. Invoke the existing backtest entry with default production args, for
    #    example by subprocess: uv run scripts/backtest_vcg.py. Do NOT pass
    #    --composite-version on the CLI.
    # 4. Re-query the latest completed production HYG/single_proxy row and verify provenance:
    run = repo.find_latest_run("vcg", composite_version="2")
    assert run["composite_version"] == "2"
    assert run["run_scope"] == "production"
    assert run["credit_proxy"] == "HYG"
    assert run["composite_method"] == "single_proxy"
    return 0
```

Three contract points the impl plan must honor:

1. **Hard runtime check on `COMPOSITE_VERSION == 2`** before any DB write. Do not implement this with bare `assert`; production scripts must not lose the guard under `python -O`. Prevents the script from being run accidentally against a pre-bump build (which would write a v=1 row with v2-shaped payload — silent corruption).
2. **No CLI override of `composite_version`.** The value flows from the imported constant, matching `regime/CLAUDE.md:16` provenance rule.
3. **Idempotency**: existing production v=2 row → exit 0 unless `--force`. Lets the script be re-run during deployment without risking duplicate rows.

The 503 window is bounded by script runtime (minutes against a fully-populated `vol_index_daily`). Self-resolving and visible.

### 9.3 Two paths explicitly rejected

**Feature flag** (env-gate `VCG_COMPOSITE_VERSION=1|2` for atomic post-backfill flip). Rejected because `regime/CLAUDE.md:16` says: *"`composite_version` provenance is derived from code constants. Never override on the CLI"* — a flag would violate this contract. Also adds permanent code (`Settings.vcg_composite_version`), permanent env plumbing, and a permanent "which version is prod actually running?" question.

**Auto-backfill on worker startup** (scheduler detects "no v=N row exists" → kicks off backtest). Rejected because backtest is non-trivial compute (minutes) blocking first scan cycle; idempotency requires a "skip if exists" guard which is just the manual-script logic always-on; silent auto-backtest on worker boot is operationally surprising.

## 10. Backward compatibility

- **v=1 rows preserved.** `regime_backtest_runs` rows at `composite_version=1` remain queryable and untouched in the DB and reports. The production `/api/regime/vcg-validation` endpoint remains current-default rather than a historical-version selector.
- **Payload fields additive.** New `vix_percentile_rank` / `vvix_percentile_rank` are absent from v=1 rows. Downstream consumers must NULL-handle: `payload->>'vix_percentile_rank'` returns NULL on v=1 rows. Standard JSONB-evolution convention.
- **Generated types additive.** `web/lib/types.ts` gains the two new optional fields. Existing UI components reading `payload.interpretation` see the cascade rewrite immediately on v=2 rows; they continue rendering v=1 rows correctly because `interpretation` is required in both versions.
- **The `regime` field is unchanged** bit-for-bit on every bar. v=1 and v=2 disagree only on `interpretation` (and the two new fields).

## 11. UI impact

- **Cascade behavior change visible immediately, no React code change required.** The interpretation pill at `web/components/regime/VcgSubTab.tsx:372` reads `sig.interpretation` from the payload; the cascade rewrite changes which value the pill displays on contradiction days (red `PANIC` or red `RISK_OFF` instead of gray `SUPPRESSED`) without any frontend code change.
- **No new tiles for the percentile-rank fields in this PR.** They are present in the payload and in `types.ts` for future consumers (validation panel, debug overlay) but are not rendered as standalone tiles in v2. Adding tiles is deferred to v2.1 if useful.

### In-scope UI fix — `VcgSubTab.tsx:323-326` hardcoded string

The existing JSX is misleading once v2 ships:

```typescript
// v1 (current — misleading once v2 is live)
{sig.pi_panic > 0
  ? `π = ${sig.pi_panic.toFixed(2)} SUPPRESSED`
  : "NO SUPPRESSION"}
```

When v2 fires `interpretation="PANIC"` for a row with `pi_panic > 0`, this string still narrates "SUPPRESSED" — a UI-level contradiction layered on top of the very payload contradiction v2 is supposed to remove. The fix is mandatory and in-scope:

```typescript
// v2 (correct — describes π value without claiming a label)
{sig.pi_panic > 0
  ? `π = ${sig.pi_panic.toFixed(2)} (panic-adjustment active)`
  : "π = 0 (no panic adjustment)"}
```

Three lines changed. The text describes the `pi_panic` *quantity* without asserting an *interpretation label* — leaving the authoritative label to the pill at line 372. Vitest unit test in `web/tests/unit/VcgSubTab.test.tsx` covers the new string.

## 12. Documentation contract

Per `vcg-methodology.md:308`, the v2 PR MUST update the following docs in the same commit:

- `docs/research/regime/vcg-methodology.md`:
  - §2.5 — rewrite cascade order and rationale.
  - §2.6 (new) — absolute-vol-stress override semantics.
  - §3 — append v2 constants table (`VIX_PCT_PANIC`, `VVIX_PCT_PANIC`, `VOL_PERCENTILE_WINDOW`, `VOL_PERCENTILE_TIE_RULE`) with rationale.
  - §3.1 — extend empirical-distribution table with v=2 backfill results.
  - §7 — replace existing "v2 (TBD)" stub with the shipped v2 entry citing this spec and the audit doc.
- `docs/research/regime/CLAUDE.md`:
  - "When to update" trigger list — add the four new constants.

## 13. Audit-PR coordination

The forensic audit (`docs/research/regime/vcg-stress-window-forensics-2026-05-26.md`) lives on the separate branch `feat/vcg-stress-window-forensics`. The v2-spec PR cites the audit by file path. Merge ordering is unconstrained:

- v2-spec PR can land first; reviewers reading the spec can find the audit on its branch.
- Audit PR can land first; v2-spec's citations become resolvable on `main`.

The audit does not add any code path v2 depends on. The two PRs are independent.

## 14. Hard prerequisites this spec creates for downstream work

- **Phase B2 (VCG + CRI joint signal, item #3 in `vcg-next-steps-2026-05-26.md`) is unblocked** once v2 lands. The audit's §7 explicitly recommended deferring B2 until v2 ships, because B2 calibrated against v1 inherits the cascade defect.
- **Future calibration specs (v2.1 candidates in §4)** can layer on v2 without re-doing the cascade work.

## 15. Implementation-plan decisions now pinned

The implementation plan resolves the remaining execution details:

- `scripts/backfill_vcg_v2.py` is a fuller wrapper with logging, idempotency, provenance checks, and no DSN/composite-version override.
- The integration fixture is committed parquet generated from long-form `vol_index_daily` plus `macro_series_daily`, preserving contiguous warmup context and deriving truth labels with `derive_level1_frame`.
- v=1 `regime_backtest_runs` archival remains out of scope; v2 backfill does not depend on archiving.
- Integration tests load the committed fixture into `seeded_db_empty_cards` and run `scripts/backtest_vcg.py` against that migrated test DB.

---

## Self-review log

### Pass 1 — brainstorming skill Phase 7 (placeholder / consistency / scope / ambiguity), 2026-05-27

| Check | Finding | Resolution |
|---|---|---|
| Placeholder scan | Two "TBD" hits both quote the existing `vcg-methodology.md` §7 stub being replaced. Not residual placeholders. | Accepted as-is. |
| Placeholder scan | `<v2_run_id>` in the §5 acceptance SQL and `<env>` in the §9.2 runbook are template variables the impl plan / operator fills in. | Accepted (deliberately template-shaped). |
| Cross-reference | Initially cited `regime/CLAUDE.md:33` for the "composite_version provenance" quote; actual line is `:16`. | Fixed. |
| Naming consistency | Initial draft used `vix_pct_rank` (internal model dict keys) and `vix_percentile_rank` (payload fields) — same concept, two names. | Unified to `vix_percentile_rank` / `vvix_percentile_rank` throughout. |
| Scope check | Spec covers exactly the audit's §7 recommendation items #1 and #2. Item #3 (OLS_WINDOW sensitivity) is explicitly out of scope per Q5. | Aligned. |
| Internal contradiction | Acceptance SQL filters to PANIC ∧ SUPPRESSED; §11 says pill flips to PANIC or RISK_OFF (not SUPPRESSED). Consistent. | OK. |
| Ambiguity | "the same vol-complex dataset the audit used" in §5 left underspecified before. Tightened to: `vol_index_daily`, full crisis range covering all 7 named-crisis windows in `named-crises.yaml`. | Already explicit in current draft. |

### Pass 2 — user review patches (2026-05-27)

Applied 6 MUST and 4 SHOULD items from the review. Summarized:

| # | Severity | Issue | Patch |
|---|---|---|---|
| 1 | MUST | §1 goal said "stress days cannot disagree" (broad); §5 acceptance only tested PANIC ∧ SUPPRESSED (narrow). Mismatch. | §1 narrowed to "highest-severity contradiction" framing with explicit "payload semantic consistency fix, not VCG predictive-performance optimization"; §5 unchanged scope, language now matches. v1's behavior allowing sign_ok-failure to suppress RISK_OFF/EDR/WATCH is **explicitly retained** and called out as v2.1 work. |
| 2 | MUST | `vol_extreme → EDR` semantic mismatch (EDR is normally drawdown-conditional in v1's flag layer). | Changed to `vol_extreme → RISK_OFF`. Justification added in §6.1: truth-labeler RISK_OFF at `regime_classification_labels.py:84` uses `vix_pct >= 0.80 AND vvix_pct >= 0.80` with same input pair; v2's `vix_pct >= 0.95 AND vvix_pct >= 0.95` is a tighter subset of truth-RISK_OFF — structural alignment, no semantic stretch. |
| 3 | MUST | Percentile-rank arrays might be off-by-one vs `model["vcg"]` (highest implementation risk). | Added §7.1 "Array alignment" sub-section with: explicit length-equality invariant; implementation guidance (compute on N-length input, trim to match `model["vcg"]`); three required tests (length match, warmup boundary, known-value at known bar). The exact alignment expression is impl-plan business, the *test* is spec business. |
| 4 | MUST | `compute_rolling_percentile_rank` may not accept `tie_rule` arg. | Verified at `regime_classification_labels.py:29-31`: signature is `def compute_rolling_percentile_rank(series: pd.Series, *, window: int, tie_rule: str = "strict_lt") -> pd.Series` — parameter already exists. **No function extension required.** Spec calls match the existing signature. |
| 5 | MUST | No test ensuring default API selection picks `composite_version=2` after bump. | Added `test_vcg_v2_api_selection.py::test_default_validation_selects_v2_after_bump` (§8.2 Test 3) — seeds two production rows (v=1 and v=2), confirms production selector returns v=2, verifies research v=2 rows do not satisfy the production-default filter. |
| 6 | MUST | Acceptance only gates contradiction count; a "fix" that NORMAL-ifies everything would pass while degrading recall. | Promoted recall non-regression from "secondary measurement" to **Gate 2** (binding). v1 baseline frozen at 52/528=0.0985 (audit's published number). v2 recall must be ≥ baseline. Test 2 in §8.2 enforces it. |
| 7 | SHOULD | Spec asserts `regime` field is bit-for-bit unchanged but has no regression test. | Added `test_regime_field_unchanged_from_v1` (§8.1) — golden 50-row CSV fixture with hand-computed v1 regime values; cascade output must match column-by-column. |
| 8 | SHOULD | `scripts/backfill_vcg_v2.py` could inadvertently violate provenance rule by passing `--composite-version=2` on CLI. | §9.2 expanded with full backfill-script contract: hard runtime check that `COMPOSITE_VERSION == 2` before any DB write; no CLI override of composite_version; idempotency (existing v=2 production row → exit 0 unless `--force`); provenance assertions on the persisted run. |
| 9 | SHOULD | No tests that Pydantic `VcgSignal` validates both v=1 (no percentiles) and v=2 (with percentiles) payloads. | Added three model tests in §8.1: v=1 payload validates with field defaults `None`; v=2 payload round-trips; v=2 payload with `None` percentile fields validates. |
| 10 | SHOULD | UI hardcoded string at `VcgSubTab.tsx:323-326` becomes misleading post-v2; was marked out of scope. | Moved in-scope (§3 item #8). §11 now specifies the 3-line replacement — describes π value without asserting label, defers the authoritative label to the pill. Vitest unit test added. The out-of-scope list still excludes broader UI redesign and tile rendering. |
