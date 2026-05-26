# Research candidate: VCG risk-parity credit basket + drawdown validation

**Status:** Design — pending user review before plan-writing.
**Branch:** `feat/vcg-credit-etf-ab-research`
**Origin:** Phase 1 deferred work from `2026-05-24-regime-research-closure-design.md` §11.1.

---

## 1. Goal and hard guarantees

### Goal

Determine whether a **risk-parity composite credit basket** (HYG + JNK + LQD) produces an earlier and equally-reliable VCG RISK_OFF signal than the current single-proxy HYG default. Produce a reproducible validation report; promote only if pre-declared gates pass.

### Hard guarantees (must hold throughout this PR)

1. **No production scanner change.** `src/uw_scan/scanners/vcg.py` remains behaviorally identical: it runs the current single-proxy HYG VCG path and writes production v1 rows only. It must not import or reference `RESEARCH_COMPOSITE_VERSIONS`, `compute_vcg_composite`, `vcg_basket`, or any research-only method registry. (The exact symbols currently imported from `vcg_scoring` are an implementation detail; this guarantee is behavior-based.)
2. **No API default selection change.** `api/routers/regime_validation.py` default selection path filters **all four** of `run_scope='production'`, `composite_version='1'`, `credit_proxy='HYG'`, `composite_method='single_proxy'`. Filtering by version alone is insufficient — a JNK or LQD research baseline at v1 could otherwise win on `created_at DESC`.
3. **Research rows are structurally excluded from production selection by column filtering, not by `extras` JSONB convention.** Tests (`tests/unit/api/test_vcg_run_selection.py`) must prove that the production default cannot return any of: a newer research row, a newer single-proxy JNK row, a newer single-proxy LQD row, a newer composite row — under any `created_at` ordering.
4. **Single-proxy research baselines (HYG/JNK/LQD for the comparator) are written as `run_scope='research'`, not production.** Only the existing operational HYG cron path writes `run_scope='production'`. See §7 CLI redesign.
5. **No promotion until pre-declared validation gate passes** (spec §9). Promotion is a separate follow-up PR after the report is reviewed.

### Non-goals

- UI surface change adding `COMPOSITE` to the validation tab proxy selector. Deferred to a follow-up PR.
- Production runtime composite path. Strictly forbidden in this PR.
- Methodology debate about whether VCG itself is well-formulated. This PR studies *proxy construction*, not the OLS-on-residuals framework.

---

## 2. Architecture overview

```
┌────────────────────────────────────────────────────────────────────────┐
│ Production path (unchanged)                                            │
│   scanners/vcg.py → cards/vcg_scoring.compute_vcg(VIX, VVIX, HYG)       │
│        → storage/vcg_snapshot_repository                               │
└────────────────────────────────────────────────────────────────────────┘
                                  ↑ no edit
                                  │
┌────────────────────────────────────────────────────────────────────────┐
│ Research path (this PR)                                                │
│                                                                        │
│   scripts/backtest_vcg.py --composite-method {RP3|RP_HYJK|HY_MINUS_IG} │
│       │                                                                │
│       ├─→ cards/vcg_basket.build_basket(...)         [NEW MODULE]      │
│       │       │ no-lookahead risk-parity weights                       │
│       │       └─→ pd.Series basket_log_returns + pd.DataFrame weights  │
│       │                                                                │
│       ├─→ cards/vcg_scoring.compute_vcg_composite(...)  [NEW FUNCTION] │
│       │       │ canonical basket OLS + per-proxy OLS attribution       │
│       │       └─→ {signal, attribution.basket_construction,            │
│       │            attribution.signal_breakdown, disagreement_flag}    │
│       │                                                                │
│       └─→ storage/regime_backtest_repository.insert_run(               │
│              run_scope='research',                                     │
│              composite_method='risk_parity_basket',                    │
│              credit_proxy_col='COMPOSITE_RP3',                         │
│              composite_version=RESEARCH_COMPOSITE_VERSIONS[...],       │
│              extras={...weight artifact sha256, vol_window, ...})      │
│                                                                        │
│   scripts/compare_vcg_lead_time.py                       [NEW SCRIPT]  │
│       │                                                                │
│       ├─→ reads benchmark closes from index_ohlc_daily                 │
│       ├─→ reads research rows from regime_backtest_runs                │
│       │       (run_scope='research', composite_version IN (...))       │
│       ├─→ drawdown detector (3 definitions × N benchmarks)             │
│       ├─→ walk-forward splitter (4 pre-declared periods)               │
│       ├─→ metric battery (8 metrics × proxy variant × cell)            │
│       └─→ writes docs/research/regime/                                 │
│              vcg-composite-validation-2026-05-26.md                    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Schema migration (safe, two-phase)

`src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql`:

The migration **must be safe for existing rows**. A flat `ADD COLUMN ... NOT NULL DEFAULT 'production'` would semantically destroy any prior research/backtest history by labeling it as production. The migration adds columns nullable, backfills from `extras` heuristically, then sets constraints.

```sql
-- 059_regime_backtest_research_scope.sql
-- Promote run_scope, composite_method, credit_proxy out of extras JSONB
-- so the API can structurally exclude research rows from production queries.
-- Two-phase to preserve historical research labels.

-- Phase 1: add columns nullable
ALTER TABLE uw_scan.regime_backtest_runs
  ADD COLUMN IF NOT EXISTS run_scope TEXT,
  ADD COLUMN IF NOT EXISTS composite_method TEXT,
  ADD COLUMN IF NOT EXISTS credit_proxy TEXT;

-- Phase 2: backfill from extras (heuristics ordered most-specific first)
UPDATE uw_scan.regime_backtest_runs
SET credit_proxy = extras->>'credit_proxy'
WHERE credit_proxy IS NULL AND extras ? 'credit_proxy';

UPDATE uw_scan.regime_backtest_runs
SET composite_method = COALESCE(extras->>'composite_method', 'single_proxy')
WHERE composite_method IS NULL;

UPDATE uw_scan.regime_backtest_runs
SET run_scope = CASE
  WHEN extras->>'run_scope' IN ('production', 'research') THEN extras->>'run_scope'
  WHEN COALESCE(extras->>'credit_proxy', credit_proxy) LIKE 'COMPOSITE%' THEN 'research'
  WHEN composite_method IS NOT NULL AND composite_method <> 'single_proxy' THEN 'research'
  ELSE 'production'
END
WHERE run_scope IS NULL;

-- Phase 3: set defaults (post-backfill, so they don't overwrite history)
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET DEFAULT 'production',
  ALTER COLUMN composite_method SET DEFAULT 'single_proxy';

-- Phase 4: NOT NULL constraints (composite_method also NOT NULL — backfill
-- already populated 'single_proxy' for legacy rows; new writers always set it)
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET NOT NULL,
  ALTER COLUMN composite_method SET NOT NULL;

-- Phase 5: check constraints — wrapped in DO blocks because Postgres has no
-- ADD CONSTRAINT IF NOT EXISTS. Re-running the migration after partial success
-- must be a no-op.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_scope_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_scope_check
      CHECK (run_scope IN ('production', 'research'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_composite_method_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_composite_method_check
      CHECK (composite_method IN (
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3'
      ));
  END IF;
END $$;

-- VCG rows must populate credit_proxy. Other indicators may not, so the
-- constraint is conditional on indicator='vcg'.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_vcg_credit_proxy_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_vcg_credit_proxy_check
      CHECK (indicator <> 'vcg' OR credit_proxy IS NOT NULL);
  END IF;
END $$;

-- Phase 6: index. CREATE INDEX IF NOT EXISTS is transactional-safe; do not
-- use CONCURRENTLY unless the migration runner supports non-transactional
-- migrations (current runner wraps each file in a BEGIN/COMMIT so CONCURRENTLY
-- is not used here).
CREATE INDEX IF NOT EXISTS idx_regime_runs_scope_indicator_version_proxy
  ON uw_scan.regime_backtest_runs
     (run_scope, indicator, composite_version, credit_proxy, composite_method, created_at DESC);
```

Per the project policy "Migrations are idempotent": every step uses `IF NOT EXISTS` / `IF EXISTS`, a `pg_constraint` lookup in a `DO` block, or a `WHERE col IS NULL` guard. Re-running the migration after partial success is a no-op.

### Repository changes

`src/uw_scan/storage/regime_backtest_repository.py`:
- `insert_run(...)` adds required `run_scope` parameter (no default; callers state intent).
- `find_latest_run(...)` adds `run_scope='production'` default. Existing callers (validation API router) require no edit — default preserves behavior.
- New `list_research_runs(*, indicator, composite_version=None, composite_method=None, credit_proxy=None) -> list[dict]` — exclusively for the comparator script.

### Backward compatibility

- Existing `extras.credit_proxy` writes are continued by single-proxy paths during a deprecation window. Spec §6 marks `extras.credit_proxy` as **deprecated post-migration**; readers must use the column.
- Historical rows are backfilled into `credit_proxy`; `run_scope` is inferred from heuristics on `extras` (composite-named or non-single-proxy-method rows become `'research'`).
- API router default path is unchanged (still selects v1 production HYG row).

---

## 4. Math primitives — `cards/vcg_basket.py` (new module, ~250–300 lines)

### Input contract

All public functions accept **date-indexed `pd.Series`/`pd.DataFrame`**, never positional `np.ndarray`. This prevents the silent date-misalignment failure mode flagged in review.

```python
def realized_vol(
    log_returns: pd.Series,
    window: int = 63,
    vol_floor: float = 1e-6,
) -> pd.Series: ...
```

- First `window − 1` bars: `NaN`.
- Zero-variance windows clipped to `vol_floor` (prevents `1/0` weights).
- Output index identical to input index.

```python
def risk_parity_weights(
    prices_by_proxy: dict[str, pd.Series],
    *,
    window: int = 63,
    weight_lag: int = 1,
    vol_floor: float = 1e-6,
) -> pd.DataFrame: ...
```

**Strict no-lookahead invariant (index-position based, holiday-safe):**

For the basket return at aligned **index position** `i`, weights at position `i` must be a pure function of returns at positions `0 .. i − 1` (with default `weight_lag = 1`). Concretely:

```python
raw_returns = log_prices.diff()                # raw_returns[0] = NaN
returns_for_vol = raw_returns.shift(weight_lag) # shifts the vol input forward by lag
vol_i = rolling_std(returns_for_vol, window).iloc[i]
weights_i = normalize(1.0 / vol_i)
basket_return_i = (weights_i * raw_returns.iloc[i]).sum()
```

The shift is what guarantees `return_i` cannot affect `weight_i`. **Specification uses index-position lag, not "business day" lag** — holidays, missing dates, single-proxy halts, and data gaps all leave the index well-defined; "business day" semantics drift across markets and would create silent off-by-one risk.

Output: `pd.DataFrame` with index = intersection of input indices (no positional alignment), columns = proxy symbols, rows summing to 1.0 ± 1e-9 once warmed up.

### OLS causality contract (applies to scoring, not just basket)

The same no-lookahead rule applies to the OLS path that consumes `basket_log_returns`. The existing `cards/vcg_scoring.py` is verified causally clean (`rolling_ols` uses a trailing 21-bar window; `standardise_residuals` uses a trailing 63-bar z-window). This spec locks the contract in writing:

> **Causality contract** — Any rolling beta, residual, residual mean, residual std, or z-score threshold used at signal date `t` must be computable from data available no later than `close_t`. Signals computed using `close_t` are considered *actionable on `t+1`*, not intraday on `t`. The comparator's "actionable lead time" metric is the version that respects this contract; "close-to-trough lead time" is reported alongside as a less-conservative upper bound (spec §8).

The composite path's `compute_vcg_composite` must not introduce a full-sample OLS, a forward-looking residual mean, or a full-history z-window. Plan task includes a regression test fixing a value of `compute_vcg`'s output against the pre-PR implementation for a fixed input to ensure no accidental change.

```python
def build_basket(
    prices_by_proxy: dict[str, pd.Series],
    *,
    method: str,
    **kwargs,
) -> tuple[pd.Series, pd.DataFrame]: ...
```

`method ∈ {"risk_parity_3", "risk_parity_hyjk", "hy_minus_ig_spread", "equal_weight_3"}`:
- **`risk_parity_3`** — three-proxy 1/σ basket, the headline candidate. `method_type = "basket"`.
- **`risk_parity_hyjk`** — HYG + JNK only (drops LQD's duration exposure). `method_type = "basket"`.
- **`hy_minus_ig_spread`** — `0.5·HYG_ret + 0.5·JNK_ret − LQD_ret` per bar. Fixed weights, no realised-vol input. `method_type = "spread"`, `gross_exposure = 2.0`. **Flagged in metadata as a spread proxy, not a basket** — its scale, OLS residual, and z-score behaviour differ from the basket methods and the report must compare it on equal footing rather than treating it as another basket.
- **`equal_weight_3`** — comparator baseline; uniform 1/3 weights. `method_type = "basket"`.

Each method registers a `MethodMetadata` record (small dataclass in `vcg_basket.py`) carrying `method_type`, `gross_exposure`, and `requires_vol_estimation: bool`. `compute_vcg_composite` and the comparator surface this metadata in the row's `extras` so the report can group results by `method_type`.

Returns `(basket_log_returns, weight_history)`. The returned basket return at index position `i` is `(weights.iloc[i] * raw_returns.iloc[i]).sum()` — weights from prior data (via the shift), returns from the current bar.

### Unit tests (`tests/unit/cards/test_vcg_basket.py`)

Two load-bearing tests cover causality at different strengths:

**Test 1 — local perturbation (necessary but not sufficient):**
```python
def test_weights_at_t_unchanged_when_only_return_t_perturbed():
    """Helper _perturb_return_at_position multiplies prices[i:] by the factor.
    This shifts price level for i, i+1, ... so that ONLY return[i] changes;
    returns at positions > i are unaffected because they're ratios of consecutive
    bumped prices, and the factor cancels.

    Naive 'multiply price[i] only' is rejected because it would also change
    return[i+1] (the ratio price[i+1]/price[i]), making the test ambiguous.
    """
    base = _make_3proxy_fixture()
    w_base = risk_parity_weights(base)
    for i in range(1, len(base["HYG"])):  # i=0 has no return
        bumped = _perturb_return_at_position(base, proxy="HYG", index_pos=i, factor=10.0)
        w_bumped = risk_parity_weights(bumped)
        # weights at position i must be unchanged by perturbing return at i
        assert _almost_equal_row(w_base.iloc[i], w_bumped.iloc[i])
```

**Test 2 — full live-replay equivalence (sufficient, harder to fake):**
```python
def test_weights_match_strict_offset_reference_at_every_position():
    """The production function's output at position i must equal a strict
    reference computed from returns[0:i] only (with the same lag rule)."""
    base = _make_3proxy_fixture()
    actual = risk_parity_weights(base, window=63, weight_lag=1)
    for i in range(64, len(base["HYG"])):
        # Reference uses returns[0:i] only (strict prefix)
        prefix = {sym: s.iloc[:i] for sym, s in base.items()}
        expected = _reference_inverse_vol_weights(prefix, window=63, weight_lag=1)
        assert_close(actual.iloc[i], expected, rtol=1e-9)
```

The reference implementation is a separate small helper in the test file. If the production function ever uses information beyond `returns[0:i]`, test 2 fails at the offending position. Test 1 alone (perturb-last-bar) can be passed by a leaky implementation; test 2 cannot.

Additional tests:
- Constant prices → equal weights after warmup
- Zero-vol clipped to `vol_floor` (and contributes proportionally to weight cap)
- Missing dates in one proxy → that row excluded from output
- Weight rows sum to 1.0 ± 1e-9 (post-warmup)
- `basket_return[i]` is valid **only when every proxy has at least `window` valid historical returns strictly before position `i`** (precise invariant; replaces vague "first window bars produce NaN")
- `hy_minus_ig_spread` returns the closed-form `0.5·HYG + 0.5·JNK − LQD` exactly per bar
- Mid-series NaN: a missing day in HYG drops that day from the basket; no silent forward-fill
- Output `basket_log_returns.index ⊆ ∩ inputs.index`

---

## 5. Composite scoring extension — `cards/vcg_scoring.py`

Existing `COMPOSITE_VERSION` and `compute_vcg` stay unchanged.

New additions (~80 lines):

```python
# Research-only version channel — NOT imported by scanners/vcg.py or api/routers/.
RESEARCH_COMPOSITE_VERSIONS = {
    "risk_parity_3":      "2-candidate-rp3",
    "risk_parity_hyjk":   "2-candidate-rp-hyjk",
    "hy_minus_ig_spread": "2-candidate-hy-minus-ig",
    "equal_weight_3":     "2-candidate-eq3",  # baseline comparator
}

def compute_vcg_composite(
    vix_prices: pd.Series,
    vvix_prices: pd.Series,
    prices_by_proxy: dict[str, pd.Series],
    *,
    method: str,
) -> dict[str, Any]: ...
```

**Output shape (separates the two layers explicitly):**

```python
{
    "signal": {  # canonical (basket residual) — drives ro/edr/tier
        "vcg": ..., "vcg_adj": ..., "ro": ..., "edr": ..., "tier": ...,
        "interpretation": "RISK_OFF" | "EDR" | "BOUNCE" | ...,
    },
    "attribution": {
        "basket_construction": {
            "method": "risk_parity_3",
            "vol_window": 63,
            "weight_lag": 1,
            "weights_today": {"HYG": 0.34, "JNK": 0.31, "LQD": 0.35},
            "contributions": {"HYG": 0.0011, "JNK": -0.0008, "LQD": 0.0003},
            "weights_artifact_sha256": "abc123...",
        },
        "signal_breakdown": {  # per-proxy single-proxy OLS, diagnostic only
            "HYG": {"vcg": 1.8, "vcg_adj": 1.8, "ro": False, ...},
            "JNK": {"vcg": 2.1, "vcg_adj": 2.1, "ro": False, ...},
            "LQD": {"vcg": 0.4, "vcg_adj": 0.4, "ro": False, ...},
            "composite_single_proxy_disagreement": True,  # composite RO but ≤1 proxy RO
        },
    },
    "date": "2026-05-23",
    "credit_proxy": "COMPOSITE_RP3",  # written to credit_proxy_col
}
```

Spec §4.3: **composite residual is NOT a weighted average of single-proxy residuals.** The two `attribution.*` layers are deliberately separate so no reader treats `attribution.signal_breakdown.HYG.vcg` as a component of `signal.vcg`.

`composite_single_proxy_disagreement` is true when the composite signal class (RO / EDR / NORMAL / etc.) differs from the modal class across the three single-proxy signals.

---

## 6. Persistence

### `regime_backtest_runs` row shape per backtest invocation

| Column | Single-proxy run | Composite run |
|---|---|---|
| `indicator` | `'vcg'` | `'vcg'` |
| `composite_version` | `'1'` | `'2-candidate-rp3'` (or other variant) |
| `run_scope` | `'production'` (unchanged) | `'research'` (required by composite path) |
| `composite_method` | `'single_proxy'` (post-migration default) | `'risk_parity_3' \| 'risk_parity_hyjk' \| 'hy_minus_ig_spread' \| 'equal_weight_3'` |
| `credit_proxy` | `'HYG' \| 'JNK' \| 'LQD'` | `'COMPOSITE_RP3' \| 'COMPOSITE_RP_HYJK' \| 'COMPOSITE_HY_MINUS_IG' \| 'COMPOSITE_EQ3'` |
| `extras.composite_method` | absent | mirror of `composite_method` column |
| `extras.vol_window` | absent | `63` |
| `extras.weight_lag` | absent | `1` |
| `extras.price_field` | absent | `'adj_close'` |
| `extras.input_symbols` | absent | `["HYG", "JNK", "LQD"]` |
| `extras.input_data_sha256` | absent | sha256 of canonicalized input price series |
| `extras.weights_artifact_sha256` | absent | sha256 of weights parquet artifact |
| `extras.weights_artifact_path` | absent | `market-warehouse/research/vcg-weights/<sha>.parquet` |
| `daily` (JSONB) | per-day signal | per-day signal + `composite_single_proxy_disagreement` boolean |

### Weight artifact storage

Daily weight history is persisted as a parquet artifact under R2 at:
```
market-warehouse/research/vcg-weights/<sha256>.parquet
```
The R2 client is already in the codebase (PR #78 rails). The artifact contains a `pd.DataFrame` with index = trade_date, columns = proxy symbols (sorted alphabetically), values = weights (float64). `weights_artifact_sha256` in `extras` is the SHA256 of the canonical parquet bytes (allowing replay verification).

**Hash content is precisely defined to avoid future reproducibility drift:**

- `input_data_sha256` is the SHA256 of canonical **parquet bytes** containing columns `[trade_date (date32), symbol (string), price_field (string), price (float64)]` for all input symbols **after** alignment (intersection of dates) and **before** any return calculation, with rows sorted by `(trade_date, symbol)`. The parquet writer config is fixed in `vcg_basket.py` (no compression, no statistics page, deterministic dictionary encoding) so the byte stream is reproducible.
- `weights_artifact_sha256` is the SHA256 of the **parquet bytes** of the weight DataFrame, columns sorted alphabetically, rows by date, same parquet writer config.

Hashing Python objects, JSON dumps, or repr strings is rejected — float formatting and column-order drift would break replay.

**Hash reproducibility boundary:** Parquet byte-level determinism is guaranteed only within the pinned `uv.lock` dependency set (pyarrow + pandas versions are pinned). Cross-version byte identity across major pyarrow upgrades is not assumed; replay verification should run under the repository lockfile. If long-horizon cross-version reproducibility is later required, a secondary canonical-CSV hash (`date ISO, symbol, price_field, %.17g`-formatted price, sorted rows) is the documented fallback — *not* implemented in this PR but recorded here so a future maintainer doesn't need to re-derive the rationale.

Inlining the daily weight history into JSONB is also rejected (review point 11): grows linearly with history, hard to hash, hard to query.

---

## 7. Backtest harness — `scripts/backtest_vcg.py` extension

### CLI surface (three mutually-exclusive modes)

```
--proxy {HYG, JNK, LQD}
    PRODUCTION single-proxy run. Writes run_scope='production',
    composite_method='single_proxy'. This is the operational path used by the
    existing nightly cron (HYG only). JNK/LQD are technically accepted for
    historical/manual reasons but should not be invoked by automation — the
    comparator does NOT consume rows from this path.

--research-proxy {HYG, JNK, LQD}
    RESEARCH single-proxy baseline for the comparator. Writes
    run_scope='research', composite_method='single_proxy'. Distinct from
    --proxy: never enters the production default selection. The comparator
    consumes rows from this path for its single-proxy baselines.

--composite-method {risk_parity_3, risk_parity_hyjk, hy_minus_ig_spread, equal_weight_3}
    RESEARCH composite run. Writes run_scope='research',
    composite_method=<chosen>.

--vol-window INT
    Default 63. Used only with --composite-method.

--weight-lag INT
    Default 1. Used only with --composite-method.
```

Exclusivity is enforced by argparse: exactly one of `--proxy`, `--research-proxy`, `--composite-method` must be supplied. Any other combination exits 2.

`--run-scope` is **not exposed as a user-facing CLI flag**. The script sets `run_scope` internally based on which mode flag was used: `--proxy` → `production`; `--research-proxy` or `--composite-method` → `research`. There is no codepath that would emit a research-shape row tagged as production, and no way for the user to write a production row from a research baseline.

### Invocation matrix for the validation report

The comparator depends on **seven research rows** existing in `regime_backtest_runs` (the existing production HYG row is independent and untouched):

```bash
# Research single-proxy baselines (all three — the comparator needs all three)
uv run python scripts/backtest_vcg.py --research-proxy HYG  # run_scope='research'
uv run python scripts/backtest_vcg.py --research-proxy JNK  # run_scope='research'
uv run python scripts/backtest_vcg.py --research-proxy LQD  # run_scope='research'

# Research composite variants
uv run python scripts/backtest_vcg.py --composite-method risk_parity_3
uv run python scripts/backtest_vcg.py --composite-method risk_parity_hyjk
uv run python scripts/backtest_vcg.py --composite-method hy_minus_ig_spread
uv run python scripts/backtest_vcg.py --composite-method equal_weight_3   # comparator baseline
```

A helper Make-target (or shell script) `make backtest-vcg-research` runs all seven. The production HYG row is preserved independently by the existing cron — this matrix does not depend on or modify it.

---

## 8. Validation methodology — `scripts/compare_vcg_lead_time.py` (new, ~400–500 lines)

### Benchmark universe

Read benchmarks from `uw_scan.index_ohlc_daily`:
- **SPY** — broad market (verified present via existing massive scheduler job)
- **QQQ** — Nasdaq-100 (need to verify; if absent, spec §11 prerequisite)
- **IWM** — Russell 2000 (need to verify)
- **XLF** — Financial sector (need to verify)
- **RSP** — S&P 500 Equal-Weight (likely absent; spec §11 records the prerequisite or drops it)

Precheck: each enabled benchmark must have ≥ 4000 trading days; the script aborts with a clear error otherwise. RSP is included only if the precheck passes; spec §11 lists "RSP backfill" as a prerequisite if not present.

### Drawdown definitions

| Name | Threshold | Window |
|---|---|---|
| Fast | ≥ 5% peak→trough | 10 trading days |
| Medium | ≥ 7% peak→trough | 20 trading days |
| Major | ≥ 10% peak→trough | 60 trading days |

Each is run independently. Lead-time/precision/recall are reported per definition, not pooled.

### Drawdown event detection — non-overlapping invariant (within-definition only)

Events emitted by the detector must be **non-overlapping within a single definition**. Without this rule, a continuous selloff (e.g. 2020-Feb→Mar, 2022-Sep→Oct) generates dozens of near-duplicate events that contaminate the hit-rate and lead-time medians.

**Cross-definition independence:** Fast / Medium / Major are detected independently. A given trading day may be inside a Fast event AND a Medium event AND a Major event — that's expected; each definition's event series is what its metrics are computed against, and the report presents each definition separately, never pooled. Earlier draft of this spec suggested suppressing Fast events nested in Medium events; that's withdrawn because it would make Fast results depend on Medium parameters and break the "each definition runs independently" claim.

Detector rules (encoded in `cards/drawdown.py`):

1. Events are non-overlapping **within a single drawdown definition**.
2. After detecting event `E` (peak_date → trough_date) under definition `D`, the next event search **for that same definition** starts at `max(E.trough_date, E.recovery_date if known else E.trough_date)`. Recovery is reached when the price closes back at `E.peak_price` (or higher); if recovery doesn't happen before the period boundary, the next search starts at `E.trough_date + 1`.
3. Each event record is `(peak_date, trough_date, peak_price, trough_price, recovery_date | None, depth_pct, definition)`.
4. The detector runs three independent passes over the same price series, one per definition. Events from different definitions may overlap in time; that's by design.

### Regime-slice validation (pre-declared, no CLI override)

**Naming correction:** This PR does *not* perform walk-forward parameter recalibration. Thresholds are fixed (taken from `vcg_scoring.py` constants). What it does is **pre-declared regime-slice evaluation** — partitioning history into market-regime cells and reporting fixed-parameter metrics per cell. The honest term is "regime-slice validation".

| Name | Range |
|---|---|
| pre-2020 | 2008-01-01 → 2019-12-31 |
| 2020-COVID | 2020-01-01 → 2020-12-31 |
| 2021-2022-rates | 2021-01-01 → 2022-12-31 |
| 2023-2026-AI | 2023-01-01 → 2026-05-26 |

Why these splits: pre-COVID baseline, the single most volatile period (deserves its own cell), the rate-shock regime (where LQD/duration matters most), and the recent AI/liquidity regime.

> This PR does not recalibrate thresholds walk-forward. It performs fixed-parameter evaluation across pre-declared market-regime slices. A future PR may add a true walk-forward harness.

### Lead-time definitions (two reported alongside)

| Metric | Formula | Interpretation |
|---|---|---|
| `close_to_trough_lead` | `trough_date − ro_date_close` (trading days) | Upper bound — assumes signal usable on day-of-close |
| `actionable_lead` | `trough_date − next_trading_day(ro_date_close)` | Per causality contract §4 — signal at close `t` is actionable at session `t+1` |

**Actionable-hit rule:** For all actionable metrics (hit rate, recall, utility score, promotion gate), an RO signal counts as an event hit **only if `actionable_lead ≥ 0`**, i.e. `next_trading_day(ro_date_close) ≤ trough_date`. Signals first observed on `trough_date`'s close get reported under `close_to_trough_lead` for transparency but **do not** count as actionable hits — promoting an "after-the-fact confirmation" to a "predictive warning" is the kind of error that invalidates the report.

The promotion gate (§9) uses `actionable_lead` exclusively. `close_to_trough_lead` is reported for transparency but is *not* a gate metric.

### Metric battery (per cell `benchmark × drawdown_def × period × proxy`)

| Metric | Formula |
|---|---|
| Median actionable lead time to trough | Median over events of `actionable_lead` for events where RO fired in `[peak − 30d, trough]`; NaN if RO never fires |
| Hit rate | `events_with_RO_in_window / total_events` |
| **FP day rate** (sensitive to multi-day RO regimes) | `RO_days_with_no_forward_drawdown / total_RO_days`, forward window = drawdown_def window |
| **FP episode rate** (event-level, gate metric) | `RO_episodes_with_no_qualifying_drawdown_within_H_def / total_RO_episodes`, where `H_def` is per-definition (Fast→30d, Medium→30d, Major→60d). Pre-declared; matches the drawdown definition's own horizon so a Major RO that pays off in week 7 isn't punished as a false positive. |
| **FP short-horizon** | RO days with no `≥2%` forward drawdown in 10 trading days |
| **FP event-window** | RO days with no qualifying event in `H_def` trading days (definition-dependent) |
| Alarm day ratio | `RO_days / total_trading_days` |
| RO episode count | Count of contiguous RO runs in period |
| Median RO episode length | Median over RO episodes of `(episode_end − episode_start) + 1` |
| Precision (day) | `TP_days / (TP_days + FP_days)` |
| Recall (event) | `events_caught_by_any_episode / total_events` |
| Utility score | `median_actionable_lead × hit_rate − k_fp × FP_episode_rate` with `k_fp = 5.0` (pre-declared) |
| Disagreement rate | `days_composite_signal ≠ HYG_signal / total_days` |

**RO episode definition:** A maximal contiguous run of trading days where the proxy's signal is in tier 1 or tier 2 RO. Episode end is the last RO day before a non-RO day. Episode-based FP avoids punishing the same warning held for additional days.

### Report output

`docs/research/regime/vcg-composite-validation-2026-05-26.md`:
1. Methodology recap (one section, with pointers to this spec)
2. Data coverage table (per benchmark, date range, # bars)
3. Per-period results matrix (one table per period × drawdown_def, rows = proxy variants, cols = metric battery)
4. Disagreement diagnostic (days/events where composite and HYG-baseline disagree)
5. **Promotion gate verdict** — pass/fail per criterion in §9, with quoted numbers
6. Raw data appendix (artifact SHAs, query templates)

---

## 9. Promotion gate (frozen before backtests run)

### Aggregation contract (closes the "wins a slice" ambiguity)

Each regime slice contains 9 cells: `3 benchmarks × 3 drawdown definitions` (benchmark universe is the three cash indices SPX/NDX/RUT — broad market / mega-cap-tech / small-cap-credit-sensitive). A gate criterion must be evaluated at the **slice** level, which requires a defined aggregation from cells → slice value. The gate uses a **primary + robustness** split:

- **Primary cell** per slice: `(SPX, Fast)`. SPX is the broad-market cash index whose drawdowns motivate this PR's thesis; Fast (≥5%/10d) is the original drawdown definition. This is the focused single-cell test.
- **Robustness cells** per slice: median of the metric across all non-empty cells in the slice (all enabled `benchmark × drawdown_def` combinations with at least one drawdown event). This tests whether the result generalises.

A composite variant must pass **both the primary gate and the robustness gate** to be promotion-eligible. Mixing-and-matching is not allowed.

### Per-slice winner definition

For each slice `p`:
- `primary_p(v) = metric on (SPY, Fast)` for variant `v`.
- `robustness_p(v) = median over non-empty (benchmark, drawdown_def) cells in p` for variant `v`.
- `best_single_primary_p = max over {HYG, JNK, LQD} of primary_p`.
- `best_single_robustness_p = max over {HYG, JNK, LQD} of robustness_p`.

### Promotion criteria (all must hold; no author discretion)

**Primary gate** (each criterion evaluated using `primary_p` only):

1. **Primary utility:** `primary_p(utility_score, composite) > best_single_primary_p(utility_score)` in **at least 3 of 4** regime slices.
2. **Primary lead:** `primary_p(median_actionable_lead, composite)` is no worse than `best_single_primary_p(median_actionable_lead)` by more than 0.5 trading day in **any** slice, AND improves by ≥ 1.0 trading day in **at least 2 of 4** slices.

**Robustness gate** (each criterion evaluated using `robustness_p`):

3. **Robustness FP episode rate:** Relative increase ≤ **10%** vs `best_single_robustness_p(FP_episode_rate)` in **at least 3 of 4** slices.
4. **Robustness alarm day ratio:** Relative increase ≤ **20%** in **at least 3 of 4** slices.
5. **Robustness hit rate:** Within **5% absolute** in **at least 3 of 4** slices.

**Single-regime dominance** (uses primary lead, period-level math):

6. Define `improvement_p = max(0, primary_p(median_actionable_lead, composite) − best_single_primary_p(median_actionable_lead))`. Let `total_improvement = Σ_p improvement_p`. **No single `improvement_p` may exceed `0.50 × total_improvement`.** If `total_improvement < 1.0 trading day` across all slices, this gate fails by default (defends against false-positive "win" from a single regime).

**FP gate metric is `FP_episode_rate`**, not `FP_day_rate`. The day-rate metric is reported alongside as diagnostic but the gate uses the episode-level version so a longer RO regime isn't double-counted as additional false-positives within the same warning.

Promotion (i.e. flipping the production scanner) is a separate PR. This PR's deliverable is the report and a per-criterion pass/fail verdict, with the numeric value quoted for every gate, for every variant, in every slice.

---

## 10. Adjusted vs raw close policy

Loaded once into a `PriceFieldPolicy` dataclass and passed explicitly to every reader:

| Series | Field | Reason |
|---|---|---|
| HYG, JNK, LQD | `adj_close` | Monthly distributions otherwise create false negative-residual spikes |
| VIX, VVIX | `close` | Index (no adjustment exists) |
| SPY, QQQ, IWM, XLF, RSP | `adj_close` | Drawdown is total-return concept; raw close double-counts dividends as drawdown |

No defaults. Each call site states the field. CI check (grep gate) ensures no `_load_series(...)` in research code paths runs without an explicit `prefer_adj_close=` argument.

---

## 11. Prerequisites and open items

Before the comparator script can run, these must be checked or resolved:

1. **`composite_version` column type** — verified TEXT (migration `057_regime_backtest_results.sql:5`). No prerequisite work.
2. **`vcg_scoring.COMPOSITE_VERSION` import sites** — verified to be `api/routers/regime_validation.py` (read-only import); `scanners/vcg.py` does not import it directly (it imports `vcg_scoring.MIN_BARS`). No prerequisite work.
3. **SPY in `index_ohlc_daily`** — verified via existing `seed_spy_ohlc.py` and scheduler job. No prerequisite work.
4. **QQQ / IWM / XLF / RSP in `index_ohlc_daily`** — **must verify in plan task 1**. If any are absent (≥ 4000 trading days), either:
   - Drop from the benchmark universe (acceptable for RSP; loss for QQQ / IWM / XLF)
   - Add a seed script run as a plan prerequisite task
5. **R2 write credentials for the research path** — the existing R2 client (PR #78) is read-only in production code. Writing weight artifacts under `market-warehouse/research/` requires write credentials. Confirm `R2_*` env vars include write access; if not, the artifact lands locally and gets uploaded via a separate operator step.
6. **Import-boundary test for production constant pollution** — `tests/unit/test_research_isolation.py` includes:
   ```python
   def test_runtime_scanner_does_not_reference_research_versions():
       import uw_scan.scanners.vcg as vcg_scanner
       assert "RESEARCH_COMPOSITE_VERSIONS" not in vcg_scanner.__dict__
       assert "RESEARCH_COMPOSITE_VERSIONS" not in dir(vcg_scanner)

   def test_api_routers_do_not_reference_research_versions():
       import uw_scan.api.routers.regime_validation as router
       assert "RESEARCH_COMPOSITE_VERSIONS" not in router.__dict__
   ```
   An import-boundary test catches accidental pollution that a grep gate could miss (e.g. via `from cards.vcg_scoring import *`). Grep additionally complements the test but is not the primary defence.

7. **API run-selection isolation test** — `tests/unit/api/test_vcg_run_selection.py` covers:
   - Production v1 row older than a research row in the DB
   - Research row has `created_at DESC` newest of all rows
   - Default API still returns the production row (not the research one)
   - Explicit research endpoint returns the research row only with explicit params
   - UI-facing endpoint cannot return research rows under any default-path call
   This is the *structural* proof of Hard Guarantee #3 from §1.

---

## 12. Module size budget

Pre-split the comparator script into focused modules upfront, rather than allowing it to grow into a 500-line orchestration black box. The comparator is the *centerpiece of research credibility* and must remain readable.

| File | Role | Estimated lines |
|---|---|---|
| `cards/vcg_basket.py` | NEW — basket primitives, no-lookahead weights, method registry | ~290 |
| `cards/vcg_scoring.py` | EXTEND — add `compute_vcg_composite`, `RESEARCH_COMPOSITE_VERSIONS` | 432 + 80 = ~512 ⚠ |
| `cards/drawdown.py` | NEW — non-overlapping drawdown event detector, recovery logic | ~150 |
| `cards/vcg_validation_metrics.py` | NEW — lead-time computers, FP day/episode metrics, episode counters, utility score | ~250 |
| `scripts/backtest_vcg.py` | EXTEND — `--composite-method`, artifact upload, internal `run_scope` setter | 314 + 90 = ~404 |
| `scripts/compare_vcg_lead_time.py` | NEW — orchestration only: load runs, dispatch detectors/metrics, write report | ~250 |
| `storage/regime_backtest_repository.py` | EXTEND — `run_scope` defaults, `list_research_runs(...)` | varies (verify) |

If `vcg_scoring.py` final size exceeds 500, the `_history_row`/`_signal_for_index` helpers move to `cards/vcg_signal.py`. Decision made during plan-writing, not at runtime.

Each of the three new `cards/` modules has unit tests; the comparator script then has a single end-to-end test against a small synthetic fixture.

---

## 13. Milestones (commit boundaries)

Per CLAUDE.md big-project rule, commit each milestone after its verification:

1. **Migration + repository columns + isolation tests** — `043` two-phase migration runs; existing rows backfilled with heuristic `run_scope`; `find_latest_run` default unchanged; `list_research_runs` added; `tests/unit/api/test_vcg_run_selection.py` proves a newer research row cannot leak into the default selection path; `tests/unit/test_research_isolation.py` proves import boundaries. Verification: full existing API test suite passes (production-default unchanged).
2. **`vcg_basket.py` math primitives** — `realized_vol`, `risk_parity_weights`, `build_basket`, `MethodMetadata`. Verification: full unit test suite, including local-perturbation AND full-replay-equivalence tests for no-lookahead.
3. **`cards/drawdown.py`** — non-overlapping drawdown event detector with recovery logic. Verification: unit tests against synthetic series including a continuous-selloff fixture that proves no duplicate events.
4. **`cards/vcg_validation_metrics.py`** — lead-time (close-to-trough AND actionable), FP day rate, FP episode rate, episode counters, utility score. Verification: each metric unit-tested against hand-computed reference values.
5. **`compute_vcg_composite` in `vcg_scoring.py`** — adds the composite scoring path + `RESEARCH_COMPOSITE_VERSIONS`. Verification: composite output schema test; production `compute_vcg` regression test (must produce bit-identical output to pre-PR for fixed inputs); OLS-causality assertion via reference re-implementation.
6. **`backtest_vcg.py` --composite-method flag** — new flag, internal `run_scope='research'` setter (no `--run-scope` exposed), artifact upload. Verification: one composite invocation against a small fixture produces a `regime_backtest_runs` row with `run_scope='research'`, a valid `weights_artifact_sha256`, and an artifact discoverable at the persisted path.
7. **`compare_vcg_lead_time.py` orchestration + report assembly** — markdown output. Verification: a smoke run on a small fixture produces a non-empty report with all matrix sections, all gate criteria evaluated, and quoted numbers per criterion.
8. **Run all 7 backtests + comparator** — produces the actual research report at `docs/research/regime/vcg-composite-validation-2026-05-26.md`. Verification: report committed; promotion gate verdict computed for every variant.
9. **Methodology doc update** — `docs/research/regime/vcg-methodology.md` §3 documents the composite formulation, OLS causality contract, and links the report. The statement "composite residual ≠ weighted average of single-proxy residuals" is preserved verbatim.

---

## 14. Out of scope (explicit)

- UI surface: adding `COMPOSITE_RP3` etc. to the validation tab proxy selector. Follow-up PR pending report verdict.
- Production scanner cutover.
- Web frontend changes of any kind.
- New OpenAPI components.
- Per-issuer (single-CDS-name) credit decomposition.
- Cross-asset composite (e.g. adding EM debt or convertibles).
- Tactical-long (`BOUNCE`) signal reformulation.

---

## 15. Self-review notes

Conducted per the brainstorming skill checklist (placeholders / consistency / scope / ambiguity):

- **Placeholders:** None. All numeric thresholds, periods, weights, FP horizons, episode definitions, and gate criteria are concrete.
- **Internal consistency (post-v3 review):**
  - §1 Hard Guarantee #1 is behavior-based, not import-detail-based — resolves the §1↔§11 contradiction from the v2 review.
  - §1 Hard Guarantee #2 lists all four production-default filter columns explicitly (`run_scope='production'` AND `composite_version='1'` AND `credit_proxy='HYG'` AND `composite_method='single_proxy'`); §11.7 run-selection test enforces it.
  - §1 Hard Guarantee #4 (research single-proxy ≠ production) is operationally enforced by §7 CLI redesign (`--research-proxy` separate from `--proxy`).
  - §3 migration constraint DDL uses `DO $$ pg_constraint $$` blocks for true idempotency (no `ADD CONSTRAINT IF NOT EXISTS` which doesn't exist in Postgres).
  - §3 `composite_method` is `NOT NULL` post-backfill; CHECK constraint no longer admits NULL; new `regime_backtest_runs_vcg_credit_proxy_check` enforces `credit_proxy` presence for `indicator='vcg'`.
  - §4 no-lookahead invariant is index-position based; unit test helper renamed `_perturb_return_at_position` to remove the v2 naming ambiguity.
  - §4 OLS causality contract applies the same rule to scoring as to basket construction.
  - §5 attribution layers (basket construction vs signal breakdown) are separated so reader cannot confuse `attribution.signal_breakdown.HYG.vcg` with a component of `signal.vcg`.
  - §6 hash boundary is documented (uv.lock-bound; canonical-CSV fallback recorded).
  - §7 CLI surface has three mutually-exclusive modes (`--proxy` / `--research-proxy` / `--composite-method`); `--run-scope` is not user-controllable.
  - §7 invocation matrix says "seven research rows" (corrected from v2's "six rows" mismatch).
  - §8 drawdown definitions are independent; non-overlap is within-definition only (removes v2's cross-definition suppression contradiction).
  - §8 actionable-hit rule: only signals with `actionable_lead ≥ 0` count as hits for gate metrics — eliminates "after-the-fact confirmation" leak.
  - §8 FP_episode_horizon is per-definition (`Fast→30d, Medium→30d, Major→60d`), matching each definition's own window so a Major RO paying off in week 7 isn't counted as FP.
  - §9 aggregation contract: primary (SPY, Fast) cell AND robustness median across cells; both must pass; closes the "what does winning a slice mean" ambiguity.
  - §9 gate item 6 defines `improvement_p = max(0, ...)` and adds the `total_improvement < 1.0` automatic-fail floor.
  - §11.6 import-boundary test is the structural defense for §1 Hard Guarantee #1; §11.7 run-selection test is the API-layer enforcement of #2 and #3.
  - §15 comparator concurrency: sequential, batch-load-once, zero-DB-queries-in-loop invariant.
- **Scope check:** One PR, ~1500 LOC + report. Milestone commits per CLAUDE.md big-project rule. TDD per milestone; subagent-driven execution recommended.
- **Ambiguity scrub:** All v2 review ambiguities resolved. The v3 review's 10 final-list items are addressed in their respective sections; no open ambiguities remain that block plan-writing.

### Comparator concurrency decision (closed)

**Comparator v1 is sequential.** It must batch-load all benchmark close series and all VCG `regime_backtest_runs.daily` series **once at startup** before metric computation begins; the per-cell loop then runs in-memory with zero further Postgres queries. Parallel execution is explicitly deferred unless wall-clock runtime exceeds **5 minutes** in steady state.

Rationale (per review):
- Cell count is modest (`3 × 3 × 4 × 7 = 252` cells, after benchmark-universe correction to SPX/NDX/RUT) — Python metric computation is not the bottleneck.
- The real risk is repeated DB queries from inside the metric loop. Batch-loading upfront eliminates that class of problem regardless of execution model.
- Sequential code is easier to debug when a metric value disagrees with hand-computed reference. Parallel-from-day-one would mix metric correctness debugging with concurrency debugging.
- If wall-clock later exceeds threshold, a follow-up PR can add `asyncio` orchestration without changing the metric layer.

Spec lock-in (encoded as a unit-test assertion in milestone 7): the comparator must issue zero database queries between the start of the per-cell loop and report assembly.
