# SPX Density Cone (v13 GJR-GARCH port) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port signal-lab's v13-validated SPX 1–5 day conditional density model into argon, numerically bit-identical, as a display-only fan chart + prospective shadow log on the `/regime` Market Tide tab.

**Architecture:** ~300 lines of numeric code vendored VERBATIM from signal-lab into `src/uw_scan/density/`, guarded by a zero-tolerance golden parity test in CI. A nightly two-pass worker job (settle yesterday's outcomes, then issue today's cone) writes `uw_scan.spx_density_forecast`; two read-only routes on the regime router feed two hand-rolled SVG components inside the existing Market Tide sub-tab.

**Tech Stack:** Python 3.13 / uv, `arch==8.0.0` (new dep), psycopg 3, FastAPI + Pydantic v2, APScheduler, Next.js 16 + React 19, hand-rolled SVG (no chart library).

**Spec:** `docs/superpowers/specs/2026-08-01-spx-density-cone-design.md` (approved 2026-08-01).

**Source of truth for all vendored code:**
`/Users/chenxi/projects/signal-lab/plugins/signal-lab/skills/signal-lab` at commit `0f893513171e2157ba997e28dcdf81a650420749` (working tree clean — verified 2026-08-01). Referred to below as `$LAB`. All `[COPY VERBATIM]` line ranges refer to files under `$LAB`.

**Recommended executor models** (orchestrator dispatches per task): Tasks 2, 3, 4, 6 are fidelity-critical → **opus**. All other tasks are mechanical pattern-following → **sonnet**. The orchestrator (Fable) reviews every task's diff before the next task starts, with special scrutiny on any diff touching `src/uw_scan/density/`.

## Amendments during execution (2026-08-01)

The plan below is kept as written; these five points are where reality overrode it. Read
them before following any instruction they touch.

1. **Constraint 2 / Task 4 — `== 0.0` throughout is not achievable.** It holds on the
   platform the golden was produced on (macOS/arm64: worst delta still exactly 0.0) but not
   on CI's Linux/x86-64, where a different BLAS lands the iterative GJR maximum-likelihood
   fit on a marginally different stationary point (`omega` 1.1e-7 relative; the analytic
   EWMA path 1 ULP). The gate now asserts **exactly** on everything discrete (panel index,
   derived seed, `n_returns`, dates, labels, quantile row shape — where silent drift is
   actually dangerous) and **bounds the float chain at 1e-6 relative**, printing the worst
   observed delta each run. Spec §3.4 amended to match.
2. **Task 6 — the `as_of` rail was too strict.** It refused any `as_of` inside the frozen
   panel window, making the reconstructed backfill impossible (only the 4 sessions after
   the panel's end qualified, so `--sessions 60` could never work). `seed_for(i)` is
   panel-index arithmetic, so a rewind still yields that date's correct index — exactly what
   v13's own backtest did. The rail now validates over the overlap; the shorter-than-panel
   refusal is scoped to live runs, where it still catches a stale mirror.
3. **Task 7 — cron is `tue-sat`, not daily** (chanlun's precedent), so Friday's close is
   issued Saturday morning rather than waiting until Monday.
4. **Task 9 — `web/lib/types.ts` full regen is correct**, contrary to the plan's surgical
   procedure. The committed file was already in openapi-typescript 7.13.0 declaration order;
   regen produced 206 additions and one deletion (an orphaned doc comment left by an earlier
   hand-splice — evidence that surgical editing of generated files rots them).
5. **Packaging + lint** — `[tool.setuptools.package-data]` needed a `uw_scan.density`
   entry for the runtime panel (Docker copies `src/` so the deploy path was unaffected, but
   a wheel install would have omitted it), `ruff format` needs `force-exclude = true` to
   stay off the vendored modules, and the three vendored files are exempted by name in
   `scripts/_lint_except.py` (Guardrail 2) because their bare `except Exception:` handlers
   are frozen v13 behaviour.

## Global Constraints

Every task's requirements implicitly include all of these.

1. **Fidelity edit policy (the prime rule):** vendored function bodies, class bodies, and constant literals are **byte-identical** to their `$LAB` origin lines. The ONLY permitted differences: module docstrings/headers, import statements (rewritten to argon paths), and deletion of function-local imports that became module-level imports. Never reformat, rename, "fix", or let a linter touch a vendored body. If ruff complains about a vendored line, add a targeted `# noqa` rather than editing the line.
2. **The golden parity test is a hard CI gate** — all assertions `== 0.0`, never a tolerance, never skipped. It failing means the cone on screen is not the validated model.
3. **Pin `arch==8.0.0` exactly** (`==`, not `>=`) in `pyproject.toml`.
4. **uv only:** `uv run pytest`, `uv sync`, never bare `python`/`pip`. Web tests: `cd web && npm run test`.
5. **Env gate:** `UW_SCAN_SPX_DENSITY_ENABLED`, default **false** (`UW_SCAN_` prefix per config.py's stated convention; this supersedes the spec's literal `SPX_DENSITY_FORECAST_ENABLED` — Task 1 patches the spec).
6. **Display-only copy rules (UI text):** permanent `DISPLAY ONLY · NOT A TRADING SIGNAL` chip; the p50 is dotted and annotated as not a direction call; copy never claims the band is tighter than EWMA; `fallback_used` renders `EWMA FALLBACK — GJR fit unavailable` in `var(--warning)`, never silently substituted; H=4 marked unscored.
7. **Persistence:** every analytical output lands in Postgres; research scripts write their full trace to a committed artifact with the reproduce command recorded.
8. **Migrations idempotent**, fully schema-qualified (`uw_scan.`), no GRANT lines, no tracking table.
9. **Module size budget** <500 lines per file.
10. **One branch, one PR:** `feat/spx-density-cone`. CHANGELOG `[Unreleased]` entry rides this PR. Never push to main; never merge before CI green.
11. **Tests:** integration tests need `UW_SCAN_TEST_DB_NAME` set (see `tests/integration/conftest.py`); on the MacBook also force-local DB env per `tests/CLAUDE.md`.

## File Structure

```
src/uw_scan/density/__init__.py            (empty marker)
src/uw_scan/density/constants.py           every frozen constant, one place (~80 lines)
src/uw_scan/density/cone.py                Cone + GJR bootstrap + EWMA baseline, vendored (~170 lines)
src/uw_scan/density/fit.py                 v8 estimator + ARMS registry, vendored (~180 lines)
src/uw_scan/density/forecast.py            orchestration: series build, agreement rail, rows (~200 lines)
src/uw_scan/density/data/panel.parquet     the frozen research panel (217,060 bytes) — runtime + tests
src/uw_scan/storage/migrations/111_spx_density_forecast.sql
src/uw_scan/storage/spx_density_repository.py
src/uw_scan/worker/jobs/spx_density_forecast.py
src/uw_scan/worker/scheduler.py            (modify: wrapper + registration)
src/uw_scan/config.py                      (modify: spx_density_enabled)
src/uw_scan/models/spx_density.py          API contract models
src/uw_scan/models/__init__.py             (modify: exports)
src/uw_scan/api/routers/regime.py          (modify: two GET routes + helper)
src/uw_scan/reports/data_freshness.py      (modify: MONITORED_TABLES entry)
src/uw_scan/reports/data_gap_healer.py     (modify: REGISTRY entry)
docs/runbooks/data-gap-dataset-policy.md   (regenerated)
tests/unit/density/test_constants.py
tests/unit/density/test_fit.py
tests/unit/density/test_forecast.py
tests/unit/density/test_parity_golden.py   THE GATE
tests/fixtures/density/forward_forecast_golden.json   (copy of $LAB committed forecast.json)
tests/fixtures/density/ewma_fallback_golden.json      (generated from $LAB originals)
tests/integration/storage/test_spx_density_repository.py
tests/integration/worker/test_spx_density_job.py
tests/integration/api/openapi.snapshot.json            (regenerated)
scripts/research/spx_density_ewma_golden_gen.py
scripts/research/spx_density_refit_staleness.py
scripts/backfill/spx_density_backfill.py
web/lib/svgChart.ts                        (modify: pathFromBand)
web/lib/regime/api.ts                      (modify: two endpoints)
web/lib/regime/useSpxDensity.ts            two hooks + types
web/components/regime/DensityConePanel.tsx
web/components/regime/DensityConeStrip.tsx
web/components/regime/MarketTideSubTab.tsx (modify: mount both)
web/lib/types.ts                           (regenerated via gen:types)
web/tests/unit/svgChart.test.ts            (modify: pathFromBand cases)
web/tests/unit/density-cone.test.tsx
web/tests/e2e/regime-density.spec.ts
CHANGELOG.md                               (modify: [Unreleased])
docs/superpowers/specs/2026-08-01-spx-density-cone-design.md (modify: 4 small patches)
docs/research/spx-density-cone/refit_staleness.json    (script output, committed)
```

---

### Task 1: Groundwork — branch, dependency, fixtures, spec patches

**Files:**
- Modify: `pyproject.toml` (add arch dep), `uv.lock` (via uv sync)
- Create: `src/uw_scan/density/__init__.py`, `src/uw_scan/density/data/panel.parquet`, `tests/fixtures/density/forward_forecast_golden.json`, `tests/unit/density/__init__.py` (not needed if tests dir has no `__init__` convention — check `tests/unit/reports/`; mirror it)
- Modify: `docs/superpowers/specs/2026-08-01-spx-density-cone-design.md`

**Interfaces:**
- Produces: `arch` importable at exactly 8.0.0; panel fixture at `src/uw_scan/density/data/panel.parquet` with sha256 `bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81`; golden JSON at `tests/fixtures/density/forward_forecast_golden.json`.

- [ ] **Step 1: Create the worktree/branch**

```bash
git -C /Users/chenxi/projects/argon worktree add .worktrees/spx-density-cone -b feat/spx-density-cone
cd /Users/chenxi/projects/argon/.worktrees/spx-density-cone
```
(All later tasks run in this worktree. Web tasks: run a real `npm ci` in `web/` — symlinked `node_modules` panics Turbopack.)

- [ ] **Step 2: Add the arch pin**

In `pyproject.toml` `[project].dependencies`, after the `"scipy>=1.17.1",` line add:

```toml
  "arch==8.0.0",
```

Run: `uv sync --extra postgres`
Expected: resolves cleanly; `uv run python -c "import arch; print(arch.__version__)"` prints `8.0.0`.

- [ ] **Step 3: Copy the frozen artifacts**

```bash
LAB=/Users/chenxi/projects/signal-lab/plugins/signal-lab/skills/signal-lab
mkdir -p src/uw_scan/density/data tests/fixtures/density tests/unit/density
touch src/uw_scan/density/__init__.py
cp "$LAB/research/runs/2026-07-27-spx-short-horizon-density/data/panel.parquet" src/uw_scan/density/data/panel.parquet
cp "$LAB/research/runs/2026-08-01-spx-fan-forward/forecast.json" tests/fixtures/density/forward_forecast_golden.json
shasum -a 256 src/uw_scan/density/data/panel.parquet
```
Expected: digest `bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81`; forecast.json is 10521 bytes.

- [ ] **Step 4: Patch the spec (4 edits)**

In `docs/superpowers/specs/2026-08-01-spx-density-cone-design.md`:
1. §7: `SPX_DENSITY_FORECAST_ENABLED` → `UW_SCAN_SPX_DENSITY_ENABLED` (config.py's stated `UW_SCAN_` prefix convention for new gates).
2. §3.4: panel fixture location `tests/fixtures/density/` → `src/uw_scan/density/data/panel.parquet` — the runtime agreement rail needs it too, so it ships as package data; tests read the same file.
3. §3.1 vendor table: add row `research/runs/_shd_v8.py | LOGLIK_TOL=1e-6, MAX_FAILURE_CARRY_DAYS=10` (a seventh source module); note in the `_v8_estimator.py` row that "channel constants" = the 9 `CHANNEL_*` strings; note `fit_gjr` is vendored but dead on arm G (kept only so `_fit` stays verbatim).
4. §5 `target_date` row: append "— weekday-advance estimate at issue; the settle pass corrects it to the actual H-th trading day (the model's horizon is trading days: bootstrap steps, matching v13's own panel-index scoring)."

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/uw_scan/density tests/fixtures/density tests/unit/density docs/superpowers/specs/2026-08-01-spx-density-cone-design.md
git commit -m "feat(density): groundwork — arch==8.0.0, frozen panel + golden fixtures, spec patches"
```

---

### Task 2: Vendored constants + cone module

**Recommended executor: opus.** Fidelity-critical.

**Files:**
- Create: `src/uw_scan/density/constants.py`, `src/uw_scan/density/cone.py`
- Test: `tests/unit/density/test_constants.py`

**Interfaces:**
- Produces (`constants.py`): `QUANTILES: tuple[float,...]`, `GJR_MIN_OBS=756`, `HORIZONS=(1,2,3,5)`, `H_MAX=5`, `M_PATHS=10000`, `LAM=0.94`, `V5_ANCHOR=755`, `SEED_BASE=20260728`, `seed_for(i:int)->int`, `MULTI_STARTS`, `T_START_NU=8.0`, the 9 `CHANNEL_*` strings, `MAX_FAILURE_CARRY_DAYS=10`, `LOGLIK_TOL=1e-6`, `OVERLAY_BURN_IN=252`, `OVERLAY_MIN_POOL=756`, `EWMA_LAMBDA`, `BAND_80=(1,5)`, `PANEL_SHA256: str`, `PANEL_FIRST_DATE: date`.
- Produces (`cone.py`): `Cone` (dataclass with `.at(h)`), `cone_from_paths`, `_to_pct_log`, `gjr_var_path`, `_gjr_simulate`, `gjr_std_residuals`, `gjr_std_boot_cone(returns_hist, price0, asof, H, params, *, M, seed, burn_in, min_pool) -> Cone | None`, `ewma_cone(returns_hist, price0, asof, H, *, lam, quantiles, M, seed) -> Cone`, `_gbm_samples`, `_ewma_sigma_series(r, lam=LAM) -> np.ndarray`, `arm_a_quantiles(sigma1, H) -> np.ndarray` of shape `(H, len(QUANTILES))`.

- [ ] **Step 1: Write the failing test**

`tests/unit/density/test_constants.py`:

```python
"""Pin every frozen v13 constant. A drift here is a different model wearing the same name."""

from uw_scan.density.constants import (
    BAND_80,
    EWMA_LAMBDA,
    GJR_MIN_OBS,
    H_MAX,
    HORIZONS,
    LAM,
    LOGLIK_TOL,
    M_PATHS,
    MAX_FAILURE_CARRY_DAYS,
    MULTI_STARTS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    SEED_BASE,
    T_START_NU,
    V5_ANCHOR,
    seed_for,
)


def test_frozen_constants() -> None:
    assert QUANTILES == (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
    assert BAND_80 == (1, 5)
    assert (GJR_MIN_OBS, OVERLAY_BURN_IN, OVERLAY_MIN_POOL) == (756, 252, 756)
    assert (M_PATHS, H_MAX, HORIZONS) == (10000, 5, (1, 2, 3, 5))
    assert LAM == 0.94 and EWMA_LAMBDA == 0.94
    assert (V5_ANCHOR, SEED_BASE) == (755, 20260728)
    assert MULTI_STARTS == (
        (0.05, 0.05, 0.05, 0.85),
        (0.02, 0.02, 0.02, 0.90),
        (0.10, 0.10, 0.10, 0.70),
        (0.20, 0.01, 0.15, 0.60),
    )
    assert T_START_NU == 8.0
    assert (MAX_FAILURE_CARRY_DAYS, LOGLIK_TOL) == (10, 1e-6)
    assert PANEL_SHA256 == (
        "bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81"
    )


def test_seed_matches_committed_run() -> None:
    # the 2026-08-01 forward run: series_index 4239 -> cone_seed 20264212
    assert seed_for(4239) == 20264212
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/density/test_constants.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.density.constants'`

- [ ] **Step 3: Write `src/uw_scan/density/constants.py`**

Full content (constants transcribed verbatim from `$LAB` — origin lines cited inline; the `#:` doc comments are the source's own and stay):

```python
"""Frozen constants of the v13 SPX density model — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513 ($LAB = plugins/signal-lab/skills/signal-lab), validated by
run 2026-08-01-spx-density-v13 (verdict PASS). DO NOT EDIT VALUES — the golden parity test
(tests/unit/density/test_parity_golden.py) pins behaviour; any change here is a different
model wearing the same name.

Origins:
  scripts/forward_paths.py:13,623        QUANTILES, GJR_MIN_OBS
  research/runs/_shd_v5.py:27-32         HORIZONS, H_MAX, M_PATHS, LAM
  research/runs/_shd_v6.py:29-31,459-461 V5_ANCHOR, SEED_BASE, seed_for
  research/runs/_v8_estimator.py:18-38   MULTI_STARTS, T_START_NU, CHANNEL_*
  research/runs/_shd_v8.py:63,65         MAX_FAILURE_CARRY_DAYS, LOGLIK_TOL
  research/runs/_v8_arms.py:59-70        OVERLAY_BURN_IN, OVERLAY_MIN_POOL, EWMA_LAMBDA
  research/runs/_v6_certification.py:62  BAND_80
Argon-added (anchors, not model parameters): PANEL_SHA256, PANEL_FIRST_DATE.
"""

from __future__ import annotations

from datetime import date

QUANTILES: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

GJR_MIN_OBS = 756  # v5 §3: below this, the caller falls back to arm A and labels `degraded`

HORIZONS = (1, 2, 3, 5)
H_MAX = max(HORIZONS)
M_PATHS = 10000
LAM = 0.94

# --- §3.3 parity anchor — FROZEN ----------------------------------------------------------
V5_ANCHOR = 755  # the index the v6 driver ITERATES from
SEED_BASE = 20260728


def seed_for(i: int) -> int:
    """v5's exact per-date seed. A function of the PANEL INDEX, never of loop position."""
    return SEED_BASE + (i - V5_ANCHOR)


#: §3.2. Index 0 is the arch package's own default; §5.3's no-harm invariant depends on that,
#: because it makes `B`'s attempt set a superset of `A_default_v8`'s. Constants, NEVER sampled —
#: a randomised multi-start would make availability itself seed-dependent.
MULTI_STARTS: tuple[tuple[float, float, float, float], ...] = (
    (0.05, 0.05, 0.05, 0.85),
    (0.02, 0.02, 0.02, 0.90),
    (0.10, 0.10, 0.10, 0.70),
    (0.20, 0.01, 0.15, 0.60),
)
#: §3.2. Student-t carries a trailing `nu` the Normal model does not.
T_START_NU = 8.0

CHANNEL_OK = "ok"
CHANNEL_TOO_SHORT = "too_short"
CHANNEL_EXCEPTION = "exception"
CHANNEL_NOT_CONVERGED = "not_converged"
CHANNEL_NON_FINITE = "non_finite"
CHANNEL_INVALID_PARAMS = "invalid_params"
CHANNEL_NON_STATIONARY = "non_stationary"
CHANNEL_BAD_NU = "bad_nu"
CHANNEL_NON_FINITE_LL = "non_finite_loglik"

MAX_FAILURE_CARRY_DAYS = 10
LOGLIK_TOL = 1e-6

#: §3.5. PASSED EXPLICITLY at the call site, never taken from `gjr_std_boot_cone`'s signature
#: defaults (see _v8_arms.py:59-64 for the full rationale).
OVERLAY_BURN_IN = 252
OVERLAY_MIN_POOL = 756

#: §5's EWMA baseline decay, likewise passed explicitly.
EWMA_LAMBDA = LAM

BAND_80 = (QUANTILES.index(0.10), QUANTILES.index(0.90))  # v5 §4(3)

# --- argon-added anchors (not model parameters) -------------------------------------------
PANEL_SHA256 = "bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81"
PANEL_FIRST_DATE = date(2009, 9, 18)  # panel row 0 — the origin of the seed's index frame
```

- [ ] **Step 4: Write `src/uw_scan/density/cone.py`**

Module skeleton — header + imports written here; every function/class body is a **verbatim copy** from `$LAB/scripts/forward_paths.py` and `$LAB/research/runs/_shd_v5.py` at the cited line ranges. Copy from the source file, do not retype from memory:

```python
"""GJR-GARCH bootstrap cone + EWMA baseline — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513, scripts/forward_paths.py + research/runs/_shd_v5.py.
Only this header and the import block differ from the source; every class and function
body below is byte-identical to its origin lines. DO NOT reformat, rename, or "fix" —
the load-bearing quirks (simple-return EWMA variance consumed as log vol; isfinite
filtering BEFORE log1p; v[t] lag in gjr_std_residuals; percent→log at exactly one point
in _gjr_simulate; np.quantile default method="linear") are frozen contract, and the
golden parity test fails on any behavioural change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from uw_scan.density.constants import GJR_MIN_OBS, LAM, QUANTILES  # noqa: F401 (GJR_MIN_OBS re-exported for fit.py)
```

Then, in this order:

1. `[COPY VERBATIM]` `scripts/forward_paths.py:16-35` → `class Cone` (keep the `@dataclass` decorator line; keep the unused `price_q` method — it is part of the verbatim body).
2. `[COPY VERBATIM]` `scripts/forward_paths.py:38-58` → `def cone_from_paths`.
3. `[COPY VERBATIM]` `scripts/forward_paths.py:245-281` → `def ewma_cone` (keep its function-local `from scipy.stats import norm` at source line 263).
4. `[COPY VERBATIM]` `scripts/forward_paths.py:284-290` → `def _gbm_samples`.
5. `[COPY VERBATIM]` `scripts/forward_paths.py:610-621` → the GJR units/first-step frozen-contract comment block (it is the unit spec — vendor the comment). Do NOT copy line 623 (`GJR_MIN_OBS = ...`) — it lives in `constants.py` and is imported above.
6. `[COPY VERBATIM]` `scripts/forward_paths.py:626-630` → `def _to_pct_log`.
7. `[COPY VERBATIM]` `scripts/forward_paths.py:671-687` → `def gjr_var_path`.
8. `[COPY VERBATIM]` `scripts/forward_paths.py:690-704` → `def _gjr_simulate`.
9. `[COPY VERBATIM]` `scripts/forward_paths.py:726-742` → `def gjr_std_residuals`.
10. `[COPY VERBATIM]` `scripts/forward_paths.py:745-774` → `def gjr_std_boot_cone`.
11. `[COPY VERBATIM]` `research/runs/_shd_v5.py:93-102` → `def _ewma_sigma_series`.
12. `[COPY VERBATIM]` `research/runs/_shd_v5.py:105-111` → `def arm_a_quantiles` (keep its function-local `from scipy.stats import norm`).

NOT copied (dead on the forward path): `_ewma_sigma_path`, `hmm_cone`, `bootstrap_cone`, `std_bootstrap_cone`, `rw_cone`, `hmm_kalman_cone`, `iv_cone`, kalman helpers, `ConformalQuantileForecaster`, `gjr_cone`, `fit_gjr` (→ Task 3), `pinball`.

- [ ] **Step 5: Verify the copies against source**

```bash
LAB=/Users/chenxi/projects/signal-lab/plugins/signal-lab/skills/signal-lab
# spot-check two bodies byte-for-byte (repeat for any block you are unsure about):
sed -n '745,774p' "$LAB/scripts/forward_paths.py"
sed -n '93,102p'  "$LAB/research/runs/_shd_v5.py"
```
Compare visually against the vendored file. The definitive check is Task 4's parity gate.

- [ ] **Step 6: Run the test**

Run: `uv run pytest tests/unit/density/test_constants.py -v && uv run python -c "from uw_scan.density.cone import gjr_std_boot_cone, ewma_cone, arm_a_quantiles; print('imports ok')"`
Expected: PASS + `imports ok`

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/density/constants.py src/uw_scan/density/cone.py tests/unit/density/test_constants.py
git commit -m "feat(density): vendor v13 constants + GJR/EWMA cone numerics verbatim"
```

---

### Task 3: Vendored estimator module

**Recommended executor: opus.** Fidelity-critical.

**Files:**
- Create: `src/uw_scan/density/fit.py`
- Test: `tests/unit/density/test_fit.py`

**Interfaces:**
- Consumes: `constants.py` (MULTI_STARTS, T_START_NU, CHANNEL_*, LOGLIK_TOL, MAX_FAILURE_CARRY_DAYS), `cone.py` (`_to_pct_log`, `GJR_MIN_OBS` re-export).
- Produces: `Attempt` (frozen dataclass — fields exactly as in `_v8_estimator.py:41-52`), `_guard`, `_attempt`, `select_attempt(attempts, loglik_tol=LOGLIK_TOL)`, `fit_v8(r, *, family, multi_start, loglik_tol=LOGLIK_TOL) -> tuple[dict | None, list[Attempt]]` (verify exact signature against source when copying), `fit_gjr` (dead code on arm G, kept for `_fit` verbatim-ness), `ArmSpec` (frozen dataclass: `family, multi_start, retry, max_carry, legacy=False`), `ARMS: dict[str, ArmSpec]` with `ARMS["G"] == ArmSpec("normal", True, True, MAX_FAILURE_CARRY_DAYS)`, `_fit(spec, hist) -> tuple[dict | None, list[Attempt]]`.

- [ ] **Step 1: Write `src/uw_scan/density/fit.py`**

Header + imports:

```python
"""v8 estimator + arm registry — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513, research/runs/_v8_estimator.py + research/runs/_v8_arms.py
(+ fit_gjr from scripts/forward_paths.py — dead code on arm G, kept so _fit stays verbatim).
Only this header and imports differ from source; every body below is byte-identical.
Frozen behaviours the parity test pins: all 5 starts evaluated unconditionally (no early
exit); select_attempt argmax over admissible loglik, ties within LOGLIK_TOL -> lowest grid
index via min over the eligible set; _attempt catches bare Exception around model.fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from uw_scan.density.cone import GJR_MIN_OBS, _to_pct_log
from uw_scan.density.constants import (
    CHANNEL_BAD_NU,
    CHANNEL_EXCEPTION,
    CHANNEL_INVALID_PARAMS,
    CHANNEL_NON_FINITE,
    CHANNEL_NON_FINITE_LL,
    CHANNEL_NON_STATIONARY,
    CHANNEL_NOT_CONVERGED,
    CHANNEL_OK,
    CHANNEL_TOO_SHORT,
    LOGLIK_TOL,
    MAX_FAILURE_CARRY_DAYS,
    MULTI_STARTS,
    T_START_NU,
)
```

Then, in this order:

1. `[COPY VERBATIM]` `research/runs/_v8_estimator.py:41-52` → `class Attempt` (frozen dataclass).
2. `[COPY VERBATIM]` `research/runs/_v8_estimator.py:55-73` → `def _guard`.
3. `[COPY VERBATIM]` `research/runs/_v8_estimator.py:76-117` → `def _attempt`. **One permitted edit:** the two function-local import lines at source 77-78 — keep `from arch.univariate import GARCH, Normal, StudentsT, ZeroMean` exactly; delete `from scripts.forward_paths import GJR_MIN_OBS, _to_pct_log` (both are module-level imports above). Everything else in the body byte-identical.
4. `[COPY VERBATIM]` `research/runs/_v8_estimator.py:120-135` → `def select_attempt`.
5. `[COPY VERBATIM]` `research/runs/_v8_estimator.py:138-162` → `def fit_v8`.
6. `[COPY VERBATIM]` `scripts/forward_paths.py:633-668` → `def fit_gjr`. If its body contains function-local `arch` imports, keep them exactly; if it references `_to_pct_log`/`GJR_MIN_OBS`, they resolve via the module-level imports.
7. `[COPY VERBATIM]` `research/runs/_v8_arms.py:103-126` → `class ArmSpec` + the full `ARMS` dict (all 7 arms, with the source's `#:` doc comments).
8. `[COPY VERBATIM]` `research/runs/_v8_arms.py:135-142` → `def _fit`. **One permitted edit:** delete the function-local `from scripts.forward_paths import fit_gjr` at source line 139 (`fit_gjr` is defined above).

- [ ] **Step 2: Write the failing test**

`tests/unit/density/test_fit.py`. NOTE: construct `Attempt` with the exact field names from the vendored dataclass (read it after copying — the fields come from `_v8_estimator.py:41-52`; adjust the constructor kwargs below to match, keeping the assertions unchanged):

```python
"""Estimator selection semantics — pin the tie-break and the arm registry."""

import numpy as np

from uw_scan.density.constants import CHANNEL_NOT_CONVERGED, CHANNEL_OK, MAX_FAILURE_CARRY_DAYS
from uw_scan.density.fit import ARMS, Attempt, ArmSpec, select_attempt


def _ok(grid_index: int, loglik: float) -> Attempt:
    # Adjust kwargs to the vendored Attempt fields (from _v8_estimator.py:41-52).
    return Attempt(
        grid_index=grid_index,
        start_values=None,
        channel=CHANNEL_OK,
        params={"omega": 0.04, "alpha": 0.01, "gamma": 0.24, "beta": 0.83},
        loglik=loglik,
    )


def test_arm_g_is_the_v13_candidate() -> None:
    assert ARMS["G"] == ArmSpec("normal", True, True, MAX_FAILURE_CARRY_DAYS)
    assert ARMS["G"].legacy is False


def test_select_attempt_ties_break_to_lowest_grid_index() -> None:
    # equal loglik within LOGLIK_TOL -> the LOWER grid index wins
    picked = select_attempt([_ok(3, -100.0), _ok(1, -100.0), _ok(2, -100.0 - 1e-9)])
    assert picked.grid_index == 1


def test_select_attempt_prefers_higher_loglik_outside_tol() -> None:
    picked = select_attempt([_ok(0, -105.0), _ok(4, -100.0)])
    assert picked.grid_index == 4


def test_select_attempt_none_when_nothing_admissible() -> None:
    bad = Attempt(
        grid_index=0,
        start_values=None,
        channel=CHANNEL_NOT_CONVERGED,
        params=None,
        loglik=float("nan"),
    )
    assert select_attempt([bad]) is None
```

If `select_attempt` returns the params dict rather than the Attempt, adapt the assertions to whatever the vendored signature actually returns (read `_v8_estimator.py:120-135` first) — the semantic claims (lowest-grid-index tie-break, higher-loglik wins, None when inadmissible) are what must hold.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/unit/density/test_fit.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/density/fit.py tests/unit/density/test_fit.py
git commit -m "feat(density): vendor v8 estimator + ARMS registry verbatim"
```

---

### Task 4: The golden parity gate

**Recommended executor: opus.** This is the fidelity mechanism itself.

**Files:**
- Create: `scripts/research/spx_density_ewma_golden_gen.py`, `tests/fixtures/density/ewma_fallback_golden.json`, `tests/unit/density/test_parity_golden.py`

**Interfaces:**
- Consumes: `cone.py` (`ewma_cone`, `gjr_std_boot_cone`, `Cone`), `fit.py` (`ARMS`, `_fit`), `constants.py`, the two fixtures from Task 1.
- Produces: the CI gate. Also `_bars_from_golden()` (test helper reused by Task 6's tests — defined in `test_parity_golden.py` and imported from there or duplicated).

**Note on Task ordering:** the function-level parity test here does NOT need `forecast.py` (Task 6) — it drives the vendored functions directly, exactly as `_forward_cone.py` does. Task 6 adds a second, orchestration-level golden.

- [ ] **Step 1: Generate the EWMA fallback golden from signal-lab ORIGINALS**

`scripts/research/spx_density_ewma_golden_gen.py` (committed; one-off authoring tool — the fixture must come from the ORIGINAL code so the vendored copy is tested against it, not against itself):

```python
"""One-off: freeze the EWMA-fallback golden from signal-lab's ORIGINAL ewma_cone.

The GJR golden (forward_forecast_golden.json) exercises _fit + gjr_std_boot_cone; it never
touches ewma_cone/_gbm_samples. This fixture covers the fallback branch, generated from the
UNVENDORED source so vendoring errors cannot self-certify.

Reproduce:
  uv run python scripts/research/spx_density_ewma_golden_gen.py \
      --signal-lab /Users/chenxi/projects/signal-lab/plugins/signal-lab/skills/signal-lab
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
PANEL = REPO / "src" / "uw_scan" / "density" / "data" / "panel.parquet"
OUT = REPO / "tests" / "fixtures" / "density" / "ewma_fallback_golden.json"

N_LAST = 400  # short slice: long enough to be a realistic series, short enough to be fast


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal-lab", required=True)
    lab = Path(ap.parse_args().signal_lab).expanduser()
    sys.path.insert(0, str(lab))
    from scripts.forward_paths import QUANTILES, ewma_cone  # the ORIGINALS

    golden = json.loads(GOLDEN.read_text())
    panel = pd.read_parquet(PANEL).sort_values("trade_date").reset_index(drop=True)
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    closes = np.asarray(closes, dtype=float)
    r = closes[1:] / closes[:-1] - 1.0

    hist = r[-N_LAST:]
    anchor_close = float(golden["anchor"]["close"])
    anchor_date = golden["anchor"]["date"]
    seed = int(golden["model"]["cone_seed"])

    cone = ewma_cone(
        hist, anchor_close, pd.Timestamp(anchor_date), 5,
        lam=0.94, quantiles=QUANTILES, M=10000, seed=seed,
    )
    OUT.write_text(json.dumps({
        "generated_from": "signal-lab ORIGINAL scripts/forward_paths.ewma_cone @ 0f893513",
        "reproduce": "uv run python scripts/research/spx_density_ewma_golden_gen.py --signal-lab <lab>",
        "n_last_returns": N_LAST,
        "anchor_date": anchor_date,
        "anchor_close": anchor_close,
        "seed": seed,
        "lam": 0.94,
        "cum_return_q": {str(h): [float(v) for v in cone.at(h)] for h in range(1, 6)},
    }, indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `uv run python scripts/research/spx_density_ewma_golden_gen.py --signal-lab /Users/chenxi/projects/signal-lab/plugins/signal-lab/skills/signal-lab`
Expected: writes `tests/fixtures/density/ewma_fallback_golden.json` with 5 rows of 7 finite floats.

- [ ] **Step 2: Write the parity test**

`tests/unit/density/test_parity_golden.py`:

```python
"""THE GATE: zero-tolerance golden parity vs signal-lab's committed 2026-08-01 forward run.

Offline by construction: forecast.json records its 4 post-panel bars verbatim under
provenance.fresh_bars_appended, so panel.parquet + those rows reconstruct the exact
4,240-return input with no lake and no network.

Every assertion is `== 0.0`. NEVER add a tolerance. NEVER skip. This test failing means
the cone argon draws is not the model v13 validated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from uw_scan.density.cone import ewma_cone, gjr_std_boot_cone
from uw_scan.density.constants import (
    H_MAX,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
EWMA_GOLDEN = REPO / "tests" / "fixtures" / "density" / "ewma_fallback_golden.json"
PANEL = REPO / "src" / "uw_scan" / "density" / "data" / "panel.parquet"


def _joined_returns() -> tuple[np.ndarray, dict]:
    """panel + fresh_bars_appended -> the exact committed input series."""
    golden = json.loads(GOLDEN.read_text())
    assert hashlib.sha256(PANEL.read_bytes()).hexdigest() == PANEL_SHA256
    assert golden["provenance"]["panel_sha256"] == PANEL_SHA256
    panel = pd.read_parquet(PANEL).sort_values("trade_date").reset_index(drop=True)
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    arr = np.asarray(closes, dtype=float)
    return arr[1:] / arr[:-1] - 1.0, golden


def test_gjr_cone_bit_identical_to_committed_run() -> None:
    r, golden = _joined_returns()
    i = len(r) - 1
    assert i == golden["anchor"]["series_index"]
    hist = r[: i + 1]
    seed = int(seed_for(i))
    assert seed == golden["model"]["cone_seed"]

    params, _attempts = _fit(ARMS["G"], hist)
    assert params is not None
    for k, v in golden["model"]["params"].items():
        assert float(params[k]) - v == 0.0, f"param {k} drifted: {float(params[k])!r} vs {v!r}"

    cone = gjr_std_boot_cone(
        hist,
        float(golden["anchor"]["close"]),
        pd.Timestamp(golden["anchor"]["date"]),
        H_MAX,
        params,
        M=M_PATHS,
        seed=seed,
        burn_in=OVERLAY_BURN_IN,
        min_pool=OVERLAY_MIN_POOL,
    )
    assert cone is not None
    for row in golden["forecast"]:
        got = cone.at(row["h"])
        for qi, q in enumerate(QUANTILES):
            want = row["cum_return_q"][str(q)]
            assert float(got[qi]) - want == 0.0, f"h={row['h']} q={q} drifted"


def test_ewma_fallback_bit_identical_to_signal_lab_original() -> None:
    fx = json.loads(EWMA_GOLDEN.read_text())
    r, _ = _joined_returns()
    hist = r[-int(fx["n_last_returns"]) :]
    cone = ewma_cone(
        hist,
        float(fx["anchor_close"]),
        pd.Timestamp(fx["anchor_date"]),
        5,
        lam=float(fx["lam"]),
        quantiles=QUANTILES,
        M=10000,
        seed=int(fx["seed"]),
    )
    for h in range(1, 6):
        got = cone.at(h)
        for qi, want in enumerate(fx["cum_return_q"][str(h)]):
            assert float(got[qi]) - want == 0.0, f"ewma h={h} qi={qi} drifted"


def test_short_pool_returns_none() -> None:
    """Degraded branch: residual pool < min_pool + H -> gjr_std_boot_cone refuses (None)."""
    r, golden = _joined_returns()
    # 1000 returns -> pool 1000-252=748 < 756+5=761
    assert (
        gjr_std_boot_cone(
            r[:1000],
            100.0,
            pd.Timestamp("2026-07-30"),
            H_MAX,
            golden["model"]["params"],
            M=M_PATHS,
            seed=1,
            burn_in=OVERLAY_BURN_IN,
            min_pool=OVERLAY_MIN_POOL,
        )
        is None
    )
```

- [ ] **Step 3: Run the gate**

Run: `uv run pytest tests/unit/density/test_parity_golden.py -v`
Expected: 3 PASSED (the GJR test takes ~3–6 s: five MLE fits on 4,240 returns + a 10,000-path simulation). If ANY delta assertion fails, the vendored code differs from source — diff the vendored bodies against `$LAB` line ranges from Tasks 2–3; do NOT add a tolerance.

- [ ] **Step 4: Commit**

```bash
git add scripts/research/spx_density_ewma_golden_gen.py tests/fixtures/density/ewma_fallback_golden.json tests/unit/density/test_parity_golden.py
git commit -m "test(density): zero-tolerance golden parity gate vs committed v13 forward run"
```

---

### Task 5: Migration 111 + repository

**Recommended executor: sonnet.**

**Files:**
- Create: `src/uw_scan/storage/migrations/111_spx_density_forecast.sql`, `src/uw_scan/storage/spx_density_repository.py`
- Test: `tests/integration/storage/test_spx_density_repository.py`

**Interfaces:**
- Produces: `SpxDensityRepository(conn: psycopg.Connection, schema: str = "uw_scan")` with methods `upsert_rows(rows: Sequence[dict]) -> int`, `latest_as_of() -> date | None`, `fetch_recent_as_ofs(limit: int) -> list[date]`, `fetch_forecast(as_of: date) -> list[dict]` (dict_row, ordered by h), `fetch_unsettled() -> list[dict]`, `settle(as_of, h, target_date, realised_return, inside_band80) -> None`, `hit_rate_tally() -> list[dict]`, `fetch_spx_series(first_date: date) -> list[tuple[date, float]]`, `fetch_spx_closes_after(after: date, limit: int) -> list[tuple[date, float]]`, `fetch_spx_recent(n: int) -> list[dict]`.
- Upsert row dict keys (later tasks produce these): `as_of, h, target_date, scored_horizon, q05, q10, q25, q50, q75, q90, q95, baseline_q05, baseline_q10, baseline_q25, baseline_q50, baseline_q75, baseline_q90, baseline_q95, band80_width, baseline_band80_width, width_ratio, anchor_close, params_jsonb (dict | None), fallback_used, origin, provenance_jsonb (dict)`.

- [ ] **Step 1: Write the migration**

`src/uw_scan/storage/migrations/111_spx_density_forecast.sql` (full content):

```sql
-- 111_spx_density_forecast.sql — SPX 1–5 trading-day conditional density cone (signal-lab
-- v13 GJR-GARCH port, verdict PASS) + its prospective shadow log.
-- Idempotent. DISPLAY-ONLY research surface: v13's authorisation ceiling is a fan chart
-- plus forward-in-time logging — rows here must never feed sizing, orders, or alerts.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.spx_density_forecast (
    as_of                  DATE NOT NULL,      -- anchor trade date (close the cone is drawn from)
    h                      SMALLINT NOT NULL,  -- horizon in TRADING days, 1..5
    target_date            DATE NOT NULL,      -- weekday-advance estimate at issue; settled to the actual H-th trading day
    scored_horizon         BOOLEAN NOT NULL,   -- h IN (1,2,3,5): v13 scored only these
    -- cumulative simple-return quantiles, the model's native units
    q05                    NUMERIC NOT NULL,
    q10                    NUMERIC NOT NULL,
    q25                    NUMERIC NOT NULL,
    q50                    NUMERIC NOT NULL,
    q75                    NUMERIC NOT NULL,
    q90                    NUMERIC NOT NULL,
    q95                    NUMERIC NOT NULL,
    -- RiskMetrics EWMA lambda=0.94 arm-A analytic band (the non-inferiority baseline)
    baseline_q05           NUMERIC NOT NULL,
    baseline_q10           NUMERIC NOT NULL,
    baseline_q25           NUMERIC NOT NULL,
    baseline_q50           NUMERIC NOT NULL,
    baseline_q75           NUMERIC NOT NULL,
    baseline_q90           NUMERIC NOT NULL,
    baseline_q95           NUMERIC NOT NULL,
    band80_width           NUMERIC NOT NULL,   -- q90 - q10
    baseline_band80_width  NUMERIC NOT NULL,
    width_ratio            NUMERIC NOT NULL,   -- often > 1: the cone is NOT claimed tighter than EWMA
    anchor_close           NUMERIC NOT NULL,   -- price rendering is anchor_close * (1 + q)
    params_jsonb           JSONB,              -- omega/alpha/gamma/beta + persistence; NULL when fallback_used
    fallback_used          BOOLEAN NOT NULL DEFAULT FALSE,
    origin                 TEXT NOT NULL DEFAULT 'prospective'
                           CHECK (origin IN ('prospective', 'reconstructed')),
    provenance_jsonb       JSONB NOT NULL,     -- panel sha256, series index, seed, agreement-check stats
    realised_return        NUMERIC,            -- filled by the settle pass once the target trading day closes
    inside_band80          BOOLEAN,            -- q10 <= realised <= q90, set with realised_return
    inserted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, h)
);

CREATE INDEX IF NOT EXISTS ix_spx_density_forecast_asof
  ON uw_scan.spx_density_forecast (as_of DESC);

COMMENT ON TABLE uw_scan.spx_density_forecast IS
  'DISPLAY-ONLY research surface (signal-lab v13 PASS): 1-5 trading-day SPX conditional '
  'density cone + prospective shadow log. origin=reconstructed rows are in-sample backfill '
  'and are tallied separately. Never a trading input.';
```

- [ ] **Step 2: Apply it**

Run: `bash scripts/migrate.sh`
Expected: applies cleanly; re-run is a no-op.

- [ ] **Step 3: Write the failing integration test**

`tests/integration/storage/test_spx_density_repository.py`:

```python
"""Round-trip + settle semantics for spx_density_forecast."""

from datetime import date

from uw_scan.storage.spx_density_repository import SpxDensityRepository


def _row(h: int, as_of: date = date(2026, 7, 30)) -> dict:
    # values from the committed 2026-08-01 forward run, h=1 (repeated per h for simplicity)
    return {
        "as_of": as_of,
        "h": h,
        "target_date": date(2026, 7, 30 + h) if 30 + h <= 31 else date(2026, 8, h - 1),
        "scored_horizon": h in (1, 2, 3, 5),
        "q05": -0.01633321359465356,
        "q10": -0.011705426306386713,
        "q25": -0.004442375363439999,
        "q50": 0.0010092081497704575,
        "q75": 0.0069347905721822145,
        "q90": 0.01231707317456232,
        "q95": 0.015371712986999712,
        "baseline_q05": -0.014103,
        "baseline_q10": -0.011005,
        "baseline_q25": -0.005807,
        "baseline_q50": 0.0,
        "baseline_q75": 0.005841,
        "baseline_q90": 0.011127,
        "baseline_q95": 0.014304,
        "band80_width": 0.024022499480949033,
        "baseline_band80_width": 0.022131559863228463,
        "width_ratio": 1.085440864964171,
        "anchor_close": 7437.63,
        "params_jsonb": {"omega": 0.0394, "alpha": 0.0141, "gamma": 0.2364, "beta": 0.8339},
        "fallback_used": False,
        "origin": "prospective",
        "provenance_jsonb": {"panel_sha256": "bd95c2ab", "series_index": 4239},
    }


def test_upsert_settle_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)

    assert sdr.upsert_rows([_row(h) for h in range(1, 6)]) == 5
    assert sdr.upsert_rows([_row(h) for h in range(1, 6)]) == 5  # idempotent re-run
    assert sdr.latest_as_of() == date(2026, 7, 30)
    assert sdr.fetch_recent_as_ofs(10) == [date(2026, 7, 30)]

    got = sdr.fetch_forecast(date(2026, 7, 30))
    assert [r["h"] for r in got] == [1, 2, 3, 4, 5]
    assert got[0]["realised_return"] is None
    assert len(sdr.fetch_unsettled()) == 5

    sdr.settle(date(2026, 7, 30), 1, date(2026, 7, 31), 0.0123, True)
    got = sdr.fetch_forecast(date(2026, 7, 30))
    assert got[0]["inside_band80"] is True
    assert float(got[0]["realised_return"]) == 0.0123
    assert len(sdr.fetch_unsettled()) == 4


def test_hit_rate_tally_splits_origin_and_scored(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    rows = [_row(h) for h in range(1, 6)]
    recon = [{**_row(h, as_of=date(2026, 7, 29)), "origin": "reconstructed"} for h in range(1, 6)]
    sdr.upsert_rows(rows + recon)
    for h in range(1, 6):
        sdr.settle(date(2026, 7, 30), h, date(2026, 8, 6), 0.001, True)
        sdr.settle(date(2026, 7, 29), h, date(2026, 8, 5), 0.05, False)
    tally = {t["origin"]: t for t in sdr.hit_rate_tally()}
    # h=4 is unscored -> only 4 of 5 rows count per origin
    assert tally["prospective"] == {"origin": "prospective", "inside": 4, "total": 4}
    assert tally["reconstructed"] == {"origin": "reconstructed", "inside": 0, "total": 4}
```

Run: `uv run pytest tests/integration/storage/test_spx_density_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.storage.spx_density_repository`

- [ ] **Step 4: Write the repository**

`src/uw_scan/storage/spx_density_repository.py` (full content):

```python
"""Standalone repository for spx_density_forecast (v13 density cone shadow log).

Never extends storage/repository.py (standing rule). Also owns the two vol_index_daily
SPX reads the job needs (series build + settle), keeping the job free of raw SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_COLUMNS = (
    "as_of",
    "h",
    "target_date",
    "scored_horizon",
    "q05",
    "q10",
    "q25",
    "q50",
    "q75",
    "q90",
    "q95",
    "baseline_q05",
    "baseline_q10",
    "baseline_q25",
    "baseline_q50",
    "baseline_q75",
    "baseline_q90",
    "baseline_q95",
    "band80_width",
    "baseline_band80_width",
    "width_ratio",
    "anchor_close",
    "params_jsonb",
    "fallback_used",
    "origin",
    "provenance_jsonb",
)


class SpxDensityRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in _COLUMNS if c not in ("as_of", "h")
        )
        sql = f"""
            INSERT INTO {self._schema}.spx_density_forecast ({cols})
            VALUES ({placeholders})
            ON CONFLICT (as_of, h) DO UPDATE SET {updates}
        """
        params = []
        for r in rows:
            p = {c: r.get(c) for c in _COLUMNS}
            p["params_jsonb"] = (
                Jsonb(r["params_jsonb"]) if r.get("params_jsonb") is not None else None
            )
            p["provenance_jsonb"] = Jsonb(r.get("provenance_jsonb") or {})
            params.append(p)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(rows)

    def latest_as_of(self) -> date | None:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT MAX(as_of) FROM {self._schema}.spx_density_forecast")
            row = cur.fetchone()
        return row[0] if row else None

    def fetch_recent_as_ofs(self, limit: int) -> list[date]:
        sql = f"""
            SELECT DISTINCT as_of FROM {self._schema}.spx_density_forecast
            ORDER BY as_of DESC LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [r[0] for r in cur.fetchall()]

    def fetch_forecast(self, as_of: date) -> list[dict[str, Any]]:
        sql = f"""
            SELECT * FROM {self._schema}.spx_density_forecast
            WHERE as_of = %s ORDER BY h
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (as_of,)).fetchall()

    def fetch_unsettled(self) -> list[dict[str, Any]]:
        sql = f"""
            SELECT as_of, h, anchor_close, q10, q90
            FROM {self._schema}.spx_density_forecast
            WHERE realised_return IS NULL
            ORDER BY as_of, h
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql).fetchall()

    def settle(
        self,
        as_of: date,
        h: int,
        target_date: date,
        realised_return: float,
        inside_band80: bool,
    ) -> None:
        sql = f"""
            UPDATE {self._schema}.spx_density_forecast
            SET target_date = %s, realised_return = %s, inside_band80 = %s
            WHERE as_of = %s AND h = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (target_date, realised_return, inside_band80, as_of, h))
        self._conn.commit()

    def hit_rate_tally(self) -> list[dict[str, Any]]:
        # only v13-scored horizons count, split by origin (reconstructed is in-sample)
        sql = f"""
            SELECT origin,
                   COUNT(*) FILTER (WHERE inside_band80)::int AS inside,
                   COUNT(*)::int AS total
            FROM {self._schema}.spx_density_forecast
            WHERE inside_band80 IS NOT NULL AND scored_horizon
            GROUP BY origin
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql).fetchall()

    # --- vol_index_daily SPX reads (series build + settle pass) --------------------------

    def fetch_spx_series(self, first_date: date) -> list[tuple[date, float]]:
        sql = f"""
            SELECT trade_date, close::float8 FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' AND trade_date >= %s ORDER BY trade_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (first_date,))
            return [(r[0], r[1]) for r in cur.fetchall()]

    def fetch_spx_closes_after(self, after: date, limit: int) -> list[tuple[date, float]]:
        sql = f"""
            SELECT trade_date, close::float8 FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' AND trade_date > %s ORDER BY trade_date LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (after, limit))
            return [(r[0], r[1]) for r in cur.fetchall()]

    def fetch_spx_recent(self, n: int) -> list[dict[str, Any]]:
        sql = f"""
            SELECT trade_date, close::float8 AS close
            FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' ORDER BY trade_date DESC LIMIT %s
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(sql, (n,)).fetchall()
        rows.reverse()
        return rows
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/integration/storage/test_spx_density_repository.py -v`
(MacBook: export the forced-local DB env per `tests/CLAUDE.md` first, incl. `UW_SCAN_TEST_DB_NAME`.)
Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/111_spx_density_forecast.sql src/uw_scan/storage/spx_density_repository.py tests/integration/storage/test_spx_density_repository.py
git commit -m "feat(density): migration 111 + SpxDensityRepository"
```

---

### Task 6: Forecast orchestration (`density/forecast.py`)

**Recommended executor: opus.** Contains the panel-index alignment rail — the silent-drift trap.

**Files:**
- Create: `src/uw_scan/density/forecast.py`
- Test: `tests/unit/density/test_forecast.py`

**Interfaces:**
- Consumes: everything from `constants.py` / `cone.py` / `fit.py`.
- Produces:
  - `class PanelMismatchError(RuntimeError)`, `class SeriesTooShortError(RuntimeError)`
  - `load_frozen_panel() -> pd.DataFrame` (columns `trade_date`, `close`; sha256-verified)
  - `compute_forecast(bars: Sequence[tuple[date, float]], *, as_of: date | None = None) -> ForecastResult` — `bars` is the full ascending SPX `(trade_date, close)` series starting at `PANEL_FIRST_DATE`; `as_of` truncates for backfill.
  - `@dataclass(frozen=True) ForecastResult`: `as_of: date`, `anchor_close: float`, `fallback_used: bool`, `params: dict[str, float] | None`, `seed: int`, `provenance: dict`, `rows: list[dict]` (row keys = the Task 5 upsert keys minus `as_of/anchor_close/params_jsonb/fallback_used/origin/provenance_jsonb`).
  - `result_to_db_rows(result: ForecastResult, *, origin: str) -> list[dict]` — exactly the Task 5 upsert dicts.

- [ ] **Step 1: Write the failing tests**

`tests/unit/density/test_forecast.py`:

```python
"""Orchestration-level golden + the panel-index alignment rail."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import uw_scan.density.forecast as fc
from uw_scan.density.forecast import (
    PanelMismatchError,
    compute_forecast,
    load_frozen_panel,
    result_to_db_rows,
)

REPO = Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json").read_text()
)
QKEY = {"0.05": "q05", "0.1": "q10", "0.25": "q25", "0.5": "q50",
        "0.75": "q75", "0.9": "q90", "0.95": "q95"}


def _bars() -> list[tuple[date, float]]:
    panel = load_frozen_panel()
    bars = [
        (d.date(), float(c))
        for d, c in zip(pd.to_datetime(panel["trade_date"]), panel["close"], strict=True)
    ]
    bars += [
        (date.fromisoformat(b["date"]), float(b["close"]))
        for b in GOLDEN["provenance"]["fresh_bars_appended"]
    ]
    return bars


def test_orchestrator_reproduces_committed_run_bit_identically() -> None:
    result = compute_forecast(_bars())
    assert result.as_of == date.fromisoformat(GOLDEN["anchor"]["date"])
    assert result.anchor_close == GOLDEN["anchor"]["close"]
    assert result.provenance["series_index"] == GOLDEN["anchor"]["series_index"]
    assert result.seed == GOLDEN["model"]["cone_seed"]
    assert result.fallback_used is False
    for k, v in GOLDEN["model"]["params"].items():
        assert result.params[k] - v == 0.0
    assert result.params["persistence"] - (
        GOLDEN["model"]["params"]["alpha"]
        + GOLDEN["model"]["params"]["gamma"] / 2.0
        + GOLDEN["model"]["params"]["beta"]
    ) == 0.0
    for row, grow in zip(result.rows, GOLDEN["forecast"], strict=True):
        assert row["h"] == grow["h"]
        assert row["scored_horizon"] == grow["scored_horizon"]
        assert row["target_date"] == date.fromisoformat(grow["date"])
        for qs, col in QKEY.items():
            assert row[col] - grow["cum_return_q"][qs] == 0.0
        assert row["band80_width"] - grow["band80_width_return"] == 0.0
        assert row["width_ratio"] - grow["width_ratio_vs_baseline"] == 0.0


def test_close_disagreement_refuses() -> None:
    bars = _bars()
    d0, c0 = bars[100]
    bars[100] = (d0, c0 + 0.01)  # one tick, one row, 17 years ago
    with pytest.raises(PanelMismatchError, match="close disagreement"):
        compute_forecast(bars)


def test_date_misalignment_refuses() -> None:
    bars = _bars()
    del bars[50]  # a missing session shifts every later index -> different seed
    with pytest.raises(PanelMismatchError, match="misalignment|shorter|rows"):
        compute_forecast(bars)


def test_series_shorter_than_panel_refuses() -> None:
    with pytest.raises(PanelMismatchError):
        compute_forecast(_bars()[:1000])


def test_as_of_truncation_moves_anchor_and_seed() -> None:
    bars = _bars()
    result = compute_forecast(bars, as_of=date(2026, 7, 29))
    assert result.as_of == date(2026, 7, 29)
    # one fewer return than the committed run -> seed one lower
    assert result.seed == GOLDEN["model"]["cone_seed"] - 1


def test_fit_failure_is_labelled_fallback(monkeypatch) -> None:
    monkeypatch.setattr(fc, "_fit", lambda spec, hist: (None, []))
    result = compute_forecast(_bars())
    assert result.fallback_used is True
    assert result.params is None
    assert all(np.isfinite(row["q50"]) for row in result.rows)


def test_result_to_db_rows_shape() -> None:
    result = compute_forecast(_bars(), as_of=date(2026, 7, 29))
    rows = result_to_db_rows(result, origin="reconstructed")
    assert len(rows) == 5
    assert rows[0]["origin"] == "reconstructed"
    assert rows[0]["as_of"] == date(2026, 7, 29)
    assert rows[0]["provenance_jsonb"]["cone_seed"] == result.seed
```

Run: `uv run pytest tests/unit/density/test_forecast.py -v`
Expected: FAIL — module not found.

- [ ] **Step 2: Write `src/uw_scan/density/forecast.py`**

Full content:

```python
"""Orchestration for the SPX density cone — argon's port of _forward_cone.py.

The numeric core is vendored verbatim in density/{constants,cone,fit}.py; this module
reimplements only the runner glue, mirroring signal-lab's
research/runs/2026-08-01-spx-fan-forward/_forward_cone.py (@ 0f893513):
series build, the zero-tolerance agreement rail, fit -> cone -> labelled fallback,
the EWMA arm-A baseline, and row emission.

THE TRAP THIS FILE EXISTS TO PREVENT: seed_for(i) is a function of the PANEL index. The
frozen panel starts 2009-09-18; argon's vol_index_daily SPX starts 1975. Feeding the full
argon series would silently change every seed and every bootstrap draw — same model,
different numbers, no error. So the series is anchored at PANEL_FIRST_DATE and the entire
panel window must match the frozen panel positionally (dates) and exactly (closes), or we
refuse to publish.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from uw_scan.density.cone import (
    _ewma_sigma_series,
    arm_a_quantiles,
    ewma_cone,
    gjr_std_boot_cone,
)
from uw_scan.density.constants import (
    BAND_80,
    EWMA_LAMBDA,
    GJR_MIN_OBS,
    H_MAX,
    HORIZONS,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit

ARM = "G"  # the v13-validated arm; frozen


class PanelMismatchError(RuntimeError):
    """DB series disagrees with the frozen panel — publishing would silently change the model."""


class SeriesTooShortError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForecastResult:
    as_of: date
    anchor_close: float
    fallback_used: bool
    params: dict[str, float] | None
    seed: int
    provenance: dict[str, Any]
    rows: list[dict[str, Any]]


def _panel_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "panel.parquet"


def load_frozen_panel() -> pd.DataFrame:
    """Hash raw bytes then parse — same order as _forward_cone.authenticated_panel."""
    raw = _panel_path().read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PANEL_SHA256:
        raise PanelMismatchError(f"frozen panel digest {digest[:16]} != {PANEL_SHA256[:16]}")
    return pd.read_parquet(_panel_path()).sort_values("trade_date").reset_index(drop=True)


def _forward_weekdays(anchor: date, n: int) -> list[date]:
    """_forward_cone.forward_trading_days, ported: pure weekday advance, no holiday
    calendar. An estimate for display — the settle pass corrects target_date to the
    actual H-th trading day (the model's horizon is trading days: bootstrap steps)."""
    out: list[date] = []
    d = anchor
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def compute_forecast(
    bars: Sequence[tuple[date, float]], *, as_of: date | None = None
) -> ForecastResult:
    """bars: full SPX (trade_date, close) ascending, starting at PANEL_FIRST_DATE.

    Agreement rail over the ENTIRE panel window: positional date equality pins the index
    frame (seed_for is panel-index arithmetic), close equality pins the values. Either
    failing -> PanelMismatchError, never a cone.
    """
    panel = load_frozen_panel()
    p_dates = [d.date() for d in pd.to_datetime(panel["trade_date"])]
    p_closes = panel["close"].to_numpy(dtype=float)
    n = len(panel)

    if len(bars) < n:
        raise PanelMismatchError(f"db series has {len(bars)} rows, frozen panel has {n}")
    b_dates = [b[0] for b in bars]
    if b_dates[:n] != p_dates:
        k = next(j for j in range(n) if b_dates[j] != p_dates[j])
        raise PanelMismatchError(
            f"date misalignment at panel index {k}: db {b_dates[k]} != panel {p_dates[k]}"
        )
    closes_all = np.array([b[1] for b in bars], dtype=float)
    delta = float(np.abs(closes_all[:n] - p_closes).max())
    if delta > 0:
        raise PanelMismatchError(
            f"close disagreement over the panel window: max abs {delta}"
        )

    if as_of is not None:
        keep = sum(1 for d in b_dates if d <= as_of)
        if keep < n:
            raise PanelMismatchError(
                f"as_of {as_of} predates the frozen panel end {p_dates[-1]}"
            )
        b_dates, closes_all = b_dates[:keep], closes_all[:keep]

    # v13 §4.2 frame: ret = close.pct_change(); r = ret[1:] (drop the NaN row 0).
    # pct_change is a/b - 1, NOT diff/b — the two differ in float and parity pins this.
    r = closes_all[1:] / closes_all[:-1] - 1.0
    dates_r = b_dates[1:]
    closes_r = closes_all[1:]
    if r.size < GJR_MIN_OBS:
        raise SeriesTooShortError(f"{r.size} returns < GJR_MIN_OBS {GJR_MIN_OBS}")

    i = len(r) - 1  # the anchor: the freshest close that exists
    anchor_date = dates_r[i]
    anchor_close = float(closes_r[i])
    hist = r[: i + 1]
    cone_seed = int(seed_for(i))

    spec = ARMS[ARM]
    params, _attempts = _fit(spec, hist)
    fallback_used = False
    cone = None
    if params is not None:
        cone = gjr_std_boot_cone(
            hist,
            anchor_close,
            pd.Timestamp(anchor_date),
            H_MAX,
            params,
            M=M_PATHS,
            seed=cone_seed,
            burn_in=OVERLAY_BURN_IN,
            min_pool=OVERLAY_MIN_POOL,
        )
    if cone is None:
        # §4.2's fallback, labelled — never silently substituted. Same seed, by design.
        fallback_used = True
        cone = ewma_cone(
            hist,
            anchor_close,
            pd.Timestamp(anchor_date),
            H_MAX,
            lam=EWMA_LAMBDA,
            quantiles=QUANTILES,
            M=M_PATHS,
            seed=cone_seed,
        )

    # the baseline the candidate was scored against (arm A: analytic, seed-independent)
    sig = _ewma_sigma_series(r, lam=EWMA_LAMBDA)
    qa = arm_a_quantiles(sig[i], H_MAX)
    lo, hi = BAND_80
    fwd = _forward_weekdays(anchor_date, H_MAX)

    rows: list[dict[str, Any]] = []
    for h in range(1, H_MAX + 1):
        cq = cone.at(h)
        bq = qa[h - 1]
        row: dict[str, Any] = {
            "h": h,
            "target_date": fwd[h - 1],
            "scored_horizon": h in HORIZONS,
        }
        for q, v in zip(QUANTILES, cq, strict=True):
            row[f"q{round(q * 100):02d}"] = float(v)
        for q, v in zip(QUANTILES, bq, strict=True):
            row[f"baseline_q{round(q * 100):02d}"] = float(v)
        row["band80_width"] = float(cq[hi] - cq[lo])
        row["baseline_band80_width"] = float(bq[hi] - bq[lo])
        row["width_ratio"] = float((cq[hi] - cq[lo]) / (bq[hi] - bq[lo]))
        rows.append(row)

    params_j: dict[str, float] | None = None
    if params is not None:
        params_j = {k: float(v) for k, v in params.items()}
        params_j["persistence"] = (
            params_j["alpha"] + params_j["gamma"] / 2.0 + params_j["beta"]
        )

    provenance = {
        "arm": ARM,
        "panel_sha256": PANEL_SHA256,
        "series_index": i,
        "n_returns": int(hist.size),
        "cone_seed": cone_seed,
        "overlap_days_checked": n,
        "max_abs_close_disagreement": delta,
        "fresh_bars_beyond_panel": len(b_dates) - n,
        "anchor_date": str(anchor_date),
    }
    return ForecastResult(
        as_of=anchor_date,
        anchor_close=anchor_close,
        fallback_used=fallback_used,
        params=params_j,
        seed=cone_seed,
        provenance=provenance,
        rows=rows,
    )


def result_to_db_rows(result: ForecastResult, *, origin: str) -> list[dict[str, Any]]:
    return [
        {
            "as_of": result.as_of,
            "anchor_close": result.anchor_close,
            "params_jsonb": result.params,
            "fallback_used": result.fallback_used,
            "origin": origin,
            "provenance_jsonb": result.provenance,
            **row,
        }
        for row in result.rows
    ]
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/unit/density/test_forecast.py -v`
Expected: 7 PASSED. The two fit-running tests take ~3–6 s each. If the orchestration golden fails while Task 4's function-level golden passes, the bug is in THIS file's glue (series build, quantile keying, `round(q*100)`), not in the vendored numerics.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/density/forecast.py tests/unit/density/test_forecast.py
git commit -m "feat(density): forecast orchestration with zero-tolerance panel agreement rail"
```

---

### Task 7: Config flag + worker job + scheduler

**Recommended executor: sonnet.**

**Files:**
- Create: `src/uw_scan/worker/jobs/spx_density_forecast.py`
- Modify: `src/uw_scan/config.py`, `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_spx_density_job.py`

**Interfaces:**
- Consumes: `compute_forecast`, `result_to_db_rows`, `PanelMismatchError`, `SeriesTooShortError`, `PANEL_FIRST_DATE`, `SpxDensityRepository` (all signatures per Tasks 5–6).
- Produces: `spx_density_forecast_job(repo: Repository, settings: Settings) -> dict[str, Any]`; `Settings.spx_density_enabled: bool` (default False, env `UW_SCAN_SPX_DENSITY_ENABLED`).

- [ ] **Step 1: Add the config flag**

In `src/uw_scan/config.py`, next to the other job gates (near `chanlun_lifecycle_enabled`, ~line 408):

```python
    # SPX 1-5d density cone (nightly 03:30 ET, massive-0). Display-only v13 port —
    # zero UW/IB spend; reads vol_index_daily only.
    spx_density_enabled: bool = False
```

And in `from_env` (next to the other `_env_bool` gates, ~line 923):

```python
            spx_density_enabled=_env_bool("UW_SCAN_SPX_DENSITY_ENABLED", False),
```

- [ ] **Step 2: Write the failing integration test**

`tests/integration/worker/test_spx_density_job.py`:

```python
"""Full job loop: seed vol_index_daily -> issue -> re-run skips -> next close settles."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from uw_scan.density.forecast import load_frozen_panel
from uw_scan.storage.spx_density_repository import SpxDensityRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.spx_density_forecast import spx_density_forecast_job

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "density" / "forward_forecast_golden.json").read_text()
)


def _seed_spx(repo) -> None:
    panel = load_frozen_panel()
    rows = []
    for d, c in zip(pd.to_datetime(panel["trade_date"]), panel["close"], strict=True):
        rows.append(_bar(d.date(), float(c)))
    for b in GOLDEN["provenance"]["fresh_bars_appended"]:
        rows.append(_bar(date.fromisoformat(b["date"]), float(b["close"])))
    VolIndexRepository(repo.conn, schema=repo._schema).upsert_rows(rows)


def _bar(d: date, close: float) -> dict:
    return {
        "symbol": "SPX",
        "trade_date": d,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adj_close": close,
        "volume": 0,
    }


def test_issue_then_skip_then_settle(seeded_db_empty_cards, settings_for_test=None):
    repo = seeded_db_empty_cards
    from uw_scan.config import Settings  # test settings come from the fixture's env

    settings = Settings.from_env()
    _seed_spx(repo)

    out1 = spx_density_forecast_job(repo, settings)
    assert out1["issued"] == 5 and out1["as_of"] == "2026-07-30"
    assert out1["fallback_used"] is False

    out2 = spx_density_forecast_job(repo, settings)
    assert out2["issued"] == 0 and out2["skipped"] == "already_issued"

    # next session closes 1% above the anchor -> h=1 settles inside the 80% band
    anchor_close = float(GOLDEN["anchor"]["close"])
    VolIndexRepository(repo.conn, schema=repo._schema).upsert_rows(
        [_bar(date(2026, 7, 31), anchor_close * 1.01)]
    )
    out3 = spx_density_forecast_job(repo, settings)
    assert out3["settled"] == 1
    assert out3["issued"] == 5 and out3["as_of"] == "2026-07-31"

    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    row_h1 = sdr.fetch_forecast(date(2026, 7, 30))[0]
    assert row_h1["target_date"] == date(2026, 7, 31)
    assert abs(float(row_h1["realised_return"]) - 0.01) < 1e-12
    # the committed run's h=1 band80 is [-1.17%, +1.23%]; +1% realised lands inside
    assert row_h1["inside_band80"] is True


def test_panel_mismatch_refuses_but_settles(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()
    _seed_spx(repo)
    # corrupt one panel-window close in the DB
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.vol_index_daily SET close = close + 0.01 "
            "WHERE symbol = 'SPX' AND trade_date = '2010-06-01'"
        )
    repo.conn.commit()
    out = spx_density_forecast_job(repo, settings)
    assert out["issued"] == 0 and out["error"] == "panel_mismatch"
```

NOTE for the executor: if `Settings.from_env()` inside the fixture env misbehaves, use the `_migrated_settings`-derived settings object the conftest exposes instead (read `tests/integration/conftest.py` — the fixtures build a `Settings` for the test DB; reuse that instead of calling `from_env` directly). The job only reads `settings.db_schema` from Settings, so any correctly-scoped Settings works.

Run: `uv run pytest tests/integration/worker/test_spx_density_job.py -v`
Expected: FAIL — job module not found.

- [ ] **Step 3: Write the job**

`src/uw_scan/worker/jobs/spx_density_forecast.py` (full content):

```python
"""Nightly SPX density cone job — settle pass then issue pass (v13 display-only port).

Pass 1 (settle) fills realised_return / inside_band80 for any row whose H-th subsequent
trading day now has a close — pure SQL + arithmetic, so a pass-2 failure never blocks
yesterday's outcomes. Pass 2 (issue) draws today's cone and writes 5 new (as_of, h) rows.
Every degradation is labelled and returned in the summary; nothing is silent.
"""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.config import Settings
from uw_scan.density.constants import PANEL_FIRST_DATE
from uw_scan.density.forecast import (
    PanelMismatchError,
    SeriesTooShortError,
    compute_forecast,
    result_to_db_rows,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.spx_density_repository import SpxDensityRepository

log = logging.getLogger(__name__)


def _settle_pass(sdr: SpxDensityRepository) -> int:
    settled = 0
    for row in sdr.fetch_unsettled():
        closes = sdr.fetch_spx_closes_after(row["as_of"], row["h"])
        if len(closes) < row["h"]:
            continue  # the H-th trading day hasn't closed yet
        target_date, close = closes[row["h"] - 1]
        realised = close / float(row["anchor_close"]) - 1.0
        inside = float(row["q10"]) <= realised <= float(row["q90"])
        sdr.settle(row["as_of"], row["h"], target_date, realised, inside)
        settled += 1
    return settled


def spx_density_forecast_job(repo: Repository, settings: Settings) -> dict[str, Any]:
    sdr = SpxDensityRepository(repo.conn, schema=settings.db_schema)
    settled = _settle_pass(sdr)

    bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
    if not bars:
        log.error("spx_density_forecast: no SPX rows in vol_index_daily")
        return {"settled": settled, "issued": 0, "skipped": "no_data"}
    anchor = bars[-1][0]
    if sdr.latest_as_of() == anchor:
        # vol_index_lake_sync produced no new bar — never re-anchor on a stale close
        return {"settled": settled, "issued": 0, "skipped": "already_issued"}

    try:
        result = compute_forecast(bars)
    except PanelMismatchError as exc:
        log.error("spx_density_forecast: REFUSING to publish — %s", exc)
        return {"settled": settled, "issued": 0, "error": "panel_mismatch"}
    except SeriesTooShortError as exc:
        log.warning("spx_density_forecast: %s", exc)
        return {"settled": settled, "issued": 0, "skipped": "too_short"}

    issued = sdr.upsert_rows(result_to_db_rows(result, origin="prospective"))
    if result.fallback_used:
        log.warning("spx_density_forecast: GJR fit unavailable — EWMA FALLBACK issued")
    return {
        "settled": settled,
        "issued": issued,
        "as_of": str(result.as_of),
        "fallback_used": result.fallback_used,
    }
```

- [ ] **Step 4: Register in the scheduler**

In `src/uw_scan/worker/scheduler.py`:

Wrapper (next to the other job wrappers, e.g. near `_vrp_markout_refresh` at ~line 763):

```python
    def _spx_density_forecast() -> None:
        from uw_scan.worker.jobs.spx_density_forecast import spx_density_forecast_job

        with _repo(settings) as repo:
            summary = spx_density_forecast_job(repo, settings)
        logger.info("spx_density_forecast_tick %s", summary)
```

Registration — inside the existing `if "massive" in groups:` → `if _is_primary_worker(settings):` nested block (~line 1397ff, near the `vrp_markout_refresh` registration):

```python
            if settings.spx_density_enabled:
                # SPX 1-5d density cone at 03:30 ET — AFTER vol_index_lake_sync (03:15)
                # so the anchor is the freshest lake close. Zero UW/IB spend; the job
                # self-gates (skips issue when no new SPX bar landed).
                sched.add_job(
                    _spx_density_forecast,
                    CronTrigger(hour=3, minute=30, timezone=settings.rth_tz),
                    id="spx_density_forecast",
                    name="SPX 1-5d density cone (v13 GJR-GARCH, display-only)",
                    max_instances=1,
                    coalesce=True,
                )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/integration/worker/test_spx_density_job.py tests/unit/density -v`
Expected: all PASS (the loop test runs two real fits, ~10 s total).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/worker/jobs/spx_density_forecast.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_spx_density_job.py
git commit -m "feat(density): nightly two-pass job, UW_SCAN_SPX_DENSITY_ENABLED gate (default off)"
```

---

### Task 8: Monitoring-registry enrolments

**Recommended executor: sonnet.**

**Files:**
- Modify: `src/uw_scan/reports/data_freshness.py`, `src/uw_scan/reports/data_gap_healer.py`
- Regenerate: `docs/runbooks/data-gap-dataset-policy.md`

**Interfaces:**
- Consumes: table `spx_density_forecast` (Task 5).
- Produces: both CI gates green (`tests/unit/reports/test_data_gap_dataset_policy.py` and the freshness tests).

- [ ] **Step 1: Freshness monitor entry**

In `src/uw_scan/reports/data_freshness.py`, append to `MONITORED_TABLES` (the list at lines 84-254). `as_of` is NOT in `_DATE_COL_PREFERENCE`, so the override is mandatory — follow the `rates_treasury_auctions` ticker-less precedent:

```python
    # SPX density cone (migration 111): nightly 03:30 ET issue, gated
    # UW_SCAN_SPX_DENSITY_ENABLED. Ticker-less (SPX only, keyed as_of+h).
    MonitoredTable(
        "spx_density_forecast",
        "watchlist",  # ticker-less
        None,
        date_col_override="as_of",
    ),
```

- [ ] **Step 2: Gap-healer registry entry**

In `src/uw_scan/reports/data_gap_healer.py`, add to `REGISTRY` (near the other derived regime tables, e.g. after `market_tide_sentiment_daily` at ~line 314):

```python
        DatasetRegistryEntry(
            "spx_density_forecast",
            "regime_marketwide",
            # research_artifact, not strict_session: a prospective forecast for a past
            # date cannot be healed retroactively BY DEFINITION — a healed row would be
            # origin='reconstructed', which the backfill script owns explicitly.
            "research_artifact",
            date_col="as_of",
            ticker_col=None,
            expected_frequency="equity_session",
            provider="db",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            reason=(
                "Display-only v13 density cone shadow log. Prospective rows are "
                "forward-in-time only; historical fill is origin='reconstructed' via "
                "scripts/backfill/spx_density_backfill.py."
            ),
        ),
```

- [ ] **Step 3: Regenerate the policy doc**

Run (the exact command the CI gate's error message quotes):

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```

- [ ] **Step 4: Run the gates**

Run: `uv run pytest tests/unit/reports/test_data_gap_dataset_policy.py tests/unit/reports -v`
Expected: PASS (if a registry-shape test fails — e.g. an audit_mode/granularity combination check — read the failing test's message; the `theta_harvester_candidates` entry at data_gap_healer.py:507-536 is the proven-legal template for adapterless derived tables).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/data_freshness.py src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md
git commit -m "feat(density): enrol spx_density_forecast in freshness + gap-healer registries"
```

---

### Task 9: API models + routes + contract regeneration

**Recommended executor: sonnet.**

**Files:**
- Create: `src/uw_scan/models/spx_density.py`
- Modify: `src/uw_scan/models/__init__.py`, `src/uw_scan/api/routers/regime.py`
- Regenerate: `tests/integration/api/openapi.snapshot.json`, `web/lib/types.ts`
- Test: `tests/integration/api/test_spx_density_routes.py`

**Interfaces:**
- Consumes: `SpxDensityRepository` (Task 5).
- Produces routes: `GET /api/regime/spx-density` → `SpxDensityLatestResponse`; `GET /api/regime/spx-density/issued?limit=5` → `SpxDensityIssuedResponse`.
- Produces models (exported from `uw_scan.models`): `SpxDensityHorizon`, `SpxDensityForecast`, `SpxDensityPathPoint`, `SpxDensityHitRate`, `SpxDensityLatestResponse`, `SpxDensityIssuedResponse`.

- [ ] **Step 1: Write the models**

`src/uw_scan/models/spx_density.py` (full content — follows the `models/vrp.py` skeleton: `_UwBase` + `_preserve_public_module`):

```python
"""API contract models for the SPX density cone (signal-lab v13 display-only port)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from uw_scan.models._base import _preserve_public_module, _UwBase

_DISCLAIMER = (
    "Display-only fan chart (v13 PASS). Not a trading signal; the median is not a "
    "direction call; the band is not claimed tighter than EWMA."
)


class SpxDensityHorizon(_UwBase):
    h: int
    target_date: date
    scored_horizon: bool
    q05: float
    q10: float
    q25: float
    q50: float
    q75: float
    q90: float
    q95: float
    baseline_q05: float
    baseline_q10: float
    baseline_q25: float
    baseline_q50: float
    baseline_q75: float
    baseline_q90: float
    baseline_q95: float
    band80_width: float
    baseline_band80_width: float
    width_ratio: float
    realised_return: float | None = None
    inside_band80: bool | None = None


class SpxDensityForecast(_UwBase):
    as_of: date
    anchor_close: float
    origin: str
    fallback_used: bool
    params: dict[str, float] | None = None
    rows: list[SpxDensityHorizon]


class SpxDensityPathPoint(_UwBase):
    date: date
    close: float


class SpxDensityHitRate(_UwBase):
    origin: str
    inside: int
    total: int


class SpxDensityLatestResponse(_UwBase):
    forecast: SpxDensityForecast | None = None
    recent_path: list[SpxDensityPathPoint] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class SpxDensityIssuedResponse(_UwBase):
    forecasts: list[SpxDensityForecast] = Field(default_factory=list)
    hit_rates: list[SpxDensityHitRate] = Field(default_factory=list)


_preserve_public_module(
    SpxDensityHorizon,
    SpxDensityForecast,
    SpxDensityPathPoint,
    SpxDensityHitRate,
    SpxDensityLatestResponse,
    SpxDensityIssuedResponse,
)
```

- [ ] **Step 2: Export from the package**

In `src/uw_scan/models/__init__.py`, add an alphabetically-placed block:

```python
from .spx_density import (
    SpxDensityForecast,
    SpxDensityHitRate,
    SpxDensityHorizon,
    SpxDensityIssuedResponse,
    SpxDensityLatestResponse,
    SpxDensityPathPoint,
)
```

and add all six names to `__all__` (alphabetical position within the list).

- [ ] **Step 3: Add the routes**

In `src/uw_scan/api/routers/regime.py` — imports at the top:

```python
from uw_scan.models.spx_density import (
    SpxDensityForecast,
    SpxDensityHitRate,
    SpxDensityHorizon,
    SpxDensityIssuedResponse,
    SpxDensityLatestResponse,
    SpxDensityPathPoint,
)
from uw_scan.storage.spx_density_repository import SpxDensityRepository
```

Routes + helper (place near the `/vrp-macro-signal` routes; `Query` is already imported in this router — verify, else add):

```python
_SPX_DENSITY_QCOLS = (
    "q05", "q10", "q25", "q50", "q75", "q90", "q95",
    "baseline_q05", "baseline_q10", "baseline_q25", "baseline_q50",
    "baseline_q75", "baseline_q90", "baseline_q95",
)


def _spx_density_forecast_model(as_of, rows) -> SpxDensityForecast:
    head = rows[0]
    return SpxDensityForecast(
        as_of=as_of,
        anchor_close=float(head["anchor_close"]),
        origin=head["origin"],
        fallback_used=head["fallback_used"],
        params=head["params_jsonb"],
        rows=[
            SpxDensityHorizon(
                h=r["h"],
                target_date=r["target_date"],
                scored_horizon=r["scored_horizon"],
                band80_width=float(r["band80_width"]),
                baseline_band80_width=float(r["baseline_band80_width"]),
                width_ratio=float(r["width_ratio"]),
                realised_return=(
                    None if r["realised_return"] is None else float(r["realised_return"])
                ),
                inside_band80=r["inside_band80"],
                **{c: float(r[c]) for c in _SPX_DENSITY_QCOLS},
            )
            for r in rows
        ],
    )


@router.get("/spx-density", response_model=SpxDensityLatestResponse)
def get_spx_density(
    repo: Annotated[Repository, Depends(get_repo)],
) -> SpxDensityLatestResponse:
    """Latest issued SPX density cone (display-only, v13 PASS). Renders the most recent
    row with its as_of — never interpolates a missing day."""
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    as_of = sdr.latest_as_of()
    if as_of is None:
        return SpxDensityLatestResponse()
    rows = sdr.fetch_forecast(as_of)
    recent = sdr.fetch_spx_recent(45)
    return SpxDensityLatestResponse(
        forecast=_spx_density_forecast_model(as_of, rows),
        recent_path=[
            SpxDensityPathPoint(date=r["trade_date"], close=float(r["close"]))
            for r in recent
        ],
    )


@router.get("/spx-density/issued", response_model=SpxDensityIssuedResponse)
def get_spx_density_issued(
    repo: Annotated[Repository, Depends(get_repo)],
    limit: int = Query(5, ge=1, le=20),
) -> SpxDensityIssuedResponse:
    """The previously-issued cones (strip) + the cumulative 80%-band hit-rate tally,
    split prospective vs reconstructed (the latter is in-sample by construction)."""
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    as_ofs = sdr.fetch_recent_as_ofs(limit + 1)[1:]  # skip the latest — headline panel
    return SpxDensityIssuedResponse(
        forecasts=[_spx_density_forecast_model(a, sdr.fetch_forecast(a)) for a in as_ofs],
        hit_rates=[SpxDensityHitRate(**t) for t in sdr.hit_rate_tally()],
    )
```

- [ ] **Step 4: Write the route integration test**

`tests/integration/api/test_spx_density_routes.py` (follow the fixture idioms of the neighbouring files in `tests/integration/api/` — reuse their `client` + DB fixtures exactly; the assertions below are the contract):

```python
"""Route contract: empty DB -> null forecast; seeded rows -> full shape."""

from datetime import date


def test_empty_db_returns_null_forecast(client):
    body = client.get("/api/regime/spx-density").json()
    assert body["forecast"] is None
    assert body["recent_path"] == []
    assert "not a trading signal" in body["disclaimer"].lower()


def test_seeded_rows_round_trip(client, seeded_db_empty_cards):
    from uw_scan.storage.spx_density_repository import SpxDensityRepository

    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    base = {
        "as_of": date(2026, 7, 30),
        "target_date": date(2026, 7, 31),
        "q05": -0.016333, "q10": -0.011705, "q25": -0.004442, "q50": 0.001009,
        "q75": 0.006935, "q90": 0.012317, "q95": 0.015372,
        "baseline_q05": -0.014103, "baseline_q10": -0.011005, "baseline_q25": -0.005807,
        "baseline_q50": 0.0, "baseline_q75": 0.005841, "baseline_q90": 0.011127,
        "baseline_q95": 0.014304,
        "band80_width": 0.024022, "baseline_band80_width": 0.022132,
        "width_ratio": 1.085441, "anchor_close": 7437.63,
        "params_jsonb": {"omega": 0.0394, "alpha": 0.0141, "gamma": 0.2364, "beta": 0.8339},
        "fallback_used": False, "origin": "prospective",
        "provenance_jsonb": {"series_index": 4239},
    }
    sdr.upsert_rows(
        [{**base, "h": h, "scored_horizon": h in (1, 2, 3, 5)} for h in range(1, 6)]
    )

    body = client.get("/api/regime/spx-density").json()
    f = body["forecast"]
    assert f["as_of"] == "2026-07-30"
    assert [r["h"] for r in f["rows"]] == [1, 2, 3, 4, 5]
    assert f["rows"][3]["scored_horizon"] is False  # h=4 unscored
    issued = client.get("/api/regime/spx-density/issued").json()
    assert issued["forecasts"] == []  # only one as_of exists; latest is skipped
```

(Executor: if `client` and the seeded-DB fixture can't coexist in one test in this suite's conftest, split into two tests matching how neighbouring API tests seed data — the assertions stay.)

Run: `uv run pytest tests/integration/api/test_spx_density_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Update the OpenAPI snapshot + web types — SURGICALLY, never full-regen**

⚠️ Both generated artifacts are frozen in an **older format the current pinned tooling no longer reproduces**: `web/lib/types.ts` is committed in 4-space, alphabetical order (openapi-typescript 7.13.0 now emits declaration order — `npm run gen:types` would reorder ~9.6k lines and bury the real change), and `openapi.snapshot.json` was dumped with `json.dumps(indent=2, ensure_ascii=True, sort_keys=True)`. `web/CLAUDE.md`'s "run gen:types and commit the diff" is stale on this. Add surgically:

**Snapshot** — with the local API running (`bash scripts/dev.sh`):

```bash
uv run python - <<'EOF'
import json, urllib.request
from pathlib import Path

sp = Path("tests/integration/api/openapi.snapshot.json")
snap = json.loads(sp.read_text())
cur = json.load(urllib.request.urlopen("http://127.0.0.1:8400/openapi.json"))
for p in ("/api/regime/spx-density", "/api/regime/spx-density/issued"):
    snap["paths"][p] = cur["paths"][p]
for s in ("SpxDensityForecast", "SpxDensityHitRate", "SpxDensityHorizon",
          "SpxDensityIssuedResponse", "SpxDensityLatestResponse", "SpxDensityPathPoint"):
    snap["components"]["schemas"][s] = cur["components"]["schemas"][s]
sp.write_text(json.dumps(snap, indent=2, ensure_ascii=True, sort_keys=True) + "\n")
print("snapshot patched")
EOF
```

**types.ts** — generate the new blocks to a THROWAWAY file, then splice them into the committed file at their **alphabetical slots**, matching its 4-space style, via a **bash/script write, not the Edit tool** (the Edit PostToolUse prettier hook reflows the generated file):

```bash
cd web
npx openapi-typescript http://127.0.0.1:8400/openapi.json -o /tmp/types.gen.ts
# From /tmp/types.gen.ts copy: (a) the two `"/api/regime/spx-density"...` path entries into
# the paths interface alphabetically; (b) the six SpxDensity* schema blocks into
# components["schemas"] alphabetically. Re-indent to 4 spaces to match the committed file.
# Write with a python/sed script or `cat` heredoc — NOT the Edit tool.
cd ..
```
Note: a field with a Pydantic default is NOT in the schema's `required` list, but openapi-typescript still renders it non-optional (`defaultNonNullable`) — copy the generated blocks verbatim rather than hand-writing them.

Then verify the diff is additions-only:

```bash
git diff --stat tests/integration/api/openapi.snapshot.json web/lib/types.ts
git diff tests/integration/api/openapi.snapshot.json | grep -c '^-[^-]' # expect 0 (or near-0 context shifts)
```
Any deletion/reorder beyond the added blocks means an accidental contract change or a format churn — stop and redo surgically.

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models/spx_density.py src/uw_scan/models/__init__.py src/uw_scan/api/routers/regime.py tests/integration/api/test_spx_density_routes.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(density): /api/regime/spx-density routes + contract models"
```

---

### Task 10: Web plumbing — band helper + hooks

**Recommended executor: sonnet.**

**Files:**
- Modify: `web/lib/svgChart.ts`, `web/lib/regime/api.ts`, `web/tests/unit/svgChart.test.ts`
- Create: `web/lib/regime/useSpxDensity.ts`

**Interfaces:**
- Produces: `pathFromBand(upper: Point[], lower: Point[]): string` in `web/lib/svgChart.ts`; `regimeApi.spx_density()` / `regimeApi.spx_density_issued(limit)`; hooks `useSpxDensity(): UseSyncReturn<SpxDensityLatest>` and `useSpxDensityIssued(): UseSyncReturn<SpxDensityIssued>` plus exported types `SpxDensityHorizon`, `SpxDensityForecast`, `SpxDensityLatest`, `SpxDensityIssued`, `SpxDensityHitRate`.

- [ ] **Step 1: Write the failing vitest**

Append to `web/tests/unit/svgChart.test.ts`:

```typescript
describe("pathFromBand", () => {
  it("closes upper-forward + lower-reversed into one polygon", () => {
    const d = pathFromBand(
      [[0, 10], [10, 5], [20, 0]],
      [[0, 10], [10, 15], [20, 20]],
    );
    expect(d).toBe("M0,10 L10,5 L20,0 L20,20 L10,15 L0,10 Z");
  });

  it("returns empty string when either edge is degenerate", () => {
    expect(pathFromBand([[0, 0]], [[0, 0], [1, 1]])).toBe("");
    expect(pathFromBand([], [])).toBe("");
  });
});
```
(and add `pathFromBand` to the existing import line from `@/lib/svgChart`.)

Run: `cd web && npx vitest run tests/unit/svgChart.test.ts`
Expected: FAIL — `pathFromBand` is not exported.

- [ ] **Step 2: Implement `pathFromBand`**

Append to `web/lib/svgChart.ts`:

```typescript
/** Filled band between two edges sharing x positions: upper drawn forward, lower
 * reversed, closed into one polygon. No existing chart draws a two-edge band —
 * added for the SPX density cone's nested quantile bands. */
export function pathFromBand(upper: Point[], lower: Point[]): string {
  if (upper.length < 2 || lower.length < 2) return "";
  const fwd = upper
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`)
    .join(" ");
  const back = [...lower]
    .reverse()
    .map(([x, y]) => `L${x},${y}`)
    .join(" ");
  return `${fwd} ${back} Z`;
}
```

Run: `cd web && npx vitest run tests/unit/svgChart.test.ts` — Expected: PASS.

- [ ] **Step 3: Endpoint builders**

In `web/lib/regime/api.ts`, add to the `regimeApi` object (near `vrp_macro_signal`):

```typescript
  spx_density: () => `${API}/api/regime/spx-density`,
  spx_density_issued: (limit: number = 5) =>
    `${API}/api/regime/spx-density/issued?limit=${limit}`,
```

- [ ] **Step 4: The hooks**

`web/lib/regime/useSpxDensity.ts` (full content — follows `useMarketTide.ts`: module-level stable refs, `useSyncHook`):

```typescript
"use client";

import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type SpxDensityHorizon = {
  h: number;
  target_date: string;
  scored_horizon: boolean;
  q05: number; q10: number; q25: number; q50: number;
  q75: number; q90: number; q95: number;
  baseline_q05: number; baseline_q10: number; baseline_q25: number;
  baseline_q50: number; baseline_q75: number; baseline_q90: number;
  baseline_q95: number;
  band80_width: number;
  baseline_band80_width: number;
  width_ratio: number;
  realised_return: number | null;
  inside_band80: boolean | null;
};

export type SpxDensityForecast = {
  as_of: string;
  anchor_close: number;
  origin: string;
  fallback_used: boolean;
  params: Record<string, number> | null;
  rows: SpxDensityHorizon[];
};

export type SpxDensityHitRate = { origin: string; inside: number; total: number };

export type SpxDensityLatest = {
  forecast: SpxDensityForecast | null;
  recent_path: { date: string; close: number }[];
  disclaimer: string;
};

export type SpxDensityIssued = {
  forecasts: SpxDensityForecast[];
  hit_rates: SpxDensityHitRate[];
};

// Stable refs so useSyncHook's executeRequest useCallback never invalidates.
const _latestTs = (d: SpxDensityLatest) => d.forecast?.as_of ?? null;
const _issuedTs = (d: SpxDensityIssued) => d.forecasts[0]?.as_of ?? null;
const _noRetry = () => false;

// Data changes once per night — 5-min polling is plenty.
const _INTERVAL = 300_000;

export function useSpxDensity(): UseSyncReturn<SpxDensityLatest> {
  return useSyncHook<SpxDensityLatest>(
    {
      endpoint: regimeApi.spx_density(),
      interval: _INTERVAL,
      hasPost: false,
      extractTimestamp: _latestTs,
      shouldRetry: _noRetry,
      retryIntervalMs: 5000,
      retryMethod: "GET" as const,
    },
    true,
  );
}

export function useSpxDensityIssued(): UseSyncReturn<SpxDensityIssued> {
  return useSyncHook<SpxDensityIssued>(
    {
      endpoint: regimeApi.spx_density_issued(5),
      interval: _INTERVAL,
      hasPost: false,
      extractTimestamp: _issuedTs,
      shouldRetry: _noRetry,
      retryIntervalMs: 5000,
      retryMethod: "GET" as const,
    },
    true,
  );
}
```
(Executor: verify the `useSyncHook` config type in `web/lib/regime/useSyncHook.ts` — if `extractTimestamp` must return `string | undefined` rather than `| null`, adapt the two `_Ts` helpers to `?? undefined`.)

- [ ] **Step 5: Typecheck + commit**

Run: `cd web && npx tsc --noEmit && npm run test`
Expected: clean.

```bash
git add web/lib/svgChart.ts web/lib/regime/api.ts web/lib/regime/useSpxDensity.ts web/tests/unit/svgChart.test.ts
git commit -m "feat(density-web): pathFromBand helper + spx-density hooks"
```

---

### Task 11: The two components + Market Tide wiring

**Recommended executor: sonnet.** Orchestrator reviews UI copy against Global Constraint 6.

**Files:**
- Create: `web/components/regime/DensityConePanel.tsx`, `web/components/regime/DensityConeStrip.tsx`
- Modify: `web/components/regime/MarketTideSubTab.tsx`
- Test: `web/tests/unit/density-cone.test.tsx`

**Interfaces:**
- Consumes: `useSpxDensity`, `useSpxDensityIssued`, `pathFromBand`, `linearScale`, `finiteDomain`, `pathFromPoints`, `niceTicks` from `@/lib/svgChart`.
- Produces: `<DensityConePanel />` (`data-testid="spx-density-panel"`), `<DensityConeStrip />` (`data-testid="spx-density-strip"`), both default exports, no props.

- [ ] **Step 1: Write `DensityConePanel.tsx`**

Full content (Argon idiom: CSS-var colors with hex fallbacks, `viewBox` + `preserveAspectRatio="none"`, mono font vars):

```tsx
"use client";

import { useSpxDensity, type SpxDensityHorizon } from "@/lib/regime/useSpxDensity";
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromBand,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

const WIDTH = 880;
const HEIGHT = 330;
const PAD = { top: 18, right: 66, bottom: 30, left: 52 };
const RECENT_N = 20;

const COLORS = {
  band: "var(--accent-vol, #7c6cf0)",
  median: "var(--text-muted)",
  realised: "var(--accent-warm, #F5A623)",
  baseline: "var(--text-secondary, #94a3b8)",
  grid: "rgba(148,163,184,0.08)",
  muted: "var(--text-muted)",
  warning: "var(--warning, #f59e0b)",
};

// (loKey, hiKey, fillOpacity) — outermost first so inner bands paint on top
const BANDS: Array<[keyof SpxDensityHorizon, keyof SpxDensityHorizon, number]> = [
  ["q05", "q95", 0.1],
  ["q10", "q90", 0.18],
  ["q25", "q75", 0.3],
];

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export default function DensityConePanel() {
  const { data, loading, error } = useSpxDensity();
  const f = data?.forecast ?? null;

  if (loading && !data) {
    return (
      <div data-testid="spx-density-panel" style={{ color: "var(--text-muted)", fontSize: 12 }}>
        Loading density cone…
      </div>
    );
  }
  if (error || !f) {
    return (
      <div data-testid="spx-density-panel" style={{ color: "var(--text-muted)", fontSize: 12 }}>
        {error ? `Density cone unavailable: ${error}` : "No density forecast issued yet."}
      </div>
    );
  }

  const anchor = f.anchor_close;
  const rows = f.rows;
  const recent = (data?.recent_path ?? []).slice(-RECENT_N);
  const nRec = Math.max(recent.length, 2);

  // x in session units: realised path at -(n-1)..0 (0 = anchor), horizons at 1..5
  const xScale = linearScale([-(nRec - 1), 5.4], [PAD.left, WIDTH - PAD.right]);
  const values: number[] = [0];
  for (const r of rows) {
    values.push(r.q05, r.q95, r.baseline_q05, r.baseline_q95);
    if (r.realised_return != null) values.push(r.realised_return);
  }
  for (const p of recent) values.push(p.close / anchor - 1);
  const dom = finiteDomain(values);
  const lo = dom ? dom.lo * 1.08 : -0.05;
  const hi = dom ? dom.hi * 1.08 : 0.05;
  const yScale = linearScale([lo, hi], [HEIGHT - PAD.bottom, PAD.top]);

  const conePts = (key: keyof SpxDensityHorizon): Point[] => [
    [xScale(0), yScale(0)],
    ...rows.map((r, i) => [xScale(i + 1), yScale(r[key] as number)] as Point),
  ];
  const realisedPts: Point[] = recent.map((p, i) => [
    xScale(i - (recent.length - 1)),
    yScale(p.close / anchor - 1),
  ]);
  const yTicks = niceTicks(lo, hi, 5);

  return (
    <div className="section" data-testid="spx-density-panel">
      <div className="section-header">
        <div className="section-title">
          SPX 1–5D Density Cone
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: COLORS.muted, marginLeft: 8 }}>
            anchor {f.as_of} · {anchor.toFixed(2)} · GJR arm G/normal
            {f.origin === "reconstructed" ? " · RECONSTRUCTED" : ""}
          </span>
          {f.fallback_used && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: COLORS.warning, marginLeft: 8 }}>
              EWMA FALLBACK — GJR fit unavailable
            </span>
          )}
        </div>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: COLORS.muted }}>
          DISPLAY ONLY · NOT A TRADING SIGNAL
        </span>
      </div>
      <svg
        role="img"
        aria-label="SPX 1-5 trading-day conditional density cone, cumulative return"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        style={{ width: "100%", display: "block" }}
      >
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke={COLORS.grid} />
            <text x={PAD.left - 6} y={yScale(t) + 3} textAnchor="end" fontSize={10} fontFamily="var(--font-mono)" fill={COLORS.muted}>
              {pct(t)}
            </text>
          </g>
        ))}
        {[1, 2, 3, 4, 5].map((h) => (
          <text key={`x${h}`} x={xScale(h)} y={HEIGHT - PAD.bottom + 14} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fill={COLORS.muted}>
            H{h}
            {h === 4 ? "*" : ""}
          </text>
        ))}
        {BANDS.map(([blo, bhi, op]) => (
          <path key={`${blo}`} d={pathFromBand(conePts(bhi), conePts(blo))} fill={COLORS.band} fillOpacity={op} />
        ))}
        {/* EWMA baseline: thin outline only, never filled — a reference, not a forecast */}
        <path d={pathFromPoints(conePts("baseline_q10"))} fill="none" stroke={COLORS.baseline} strokeDasharray="6 4" opacity={0.6} />
        <path d={pathFromPoints(conePts("baseline_q90"))} fill="none" stroke={COLORS.baseline} strokeDasharray="6 4" opacity={0.6} />
        {/* p50: dotted, deliberately faint — NOT a direction call */}
        <path d={pathFromPoints(conePts("q50"))} fill="none" stroke={COLORS.median} strokeDasharray="2 4" />
        {realisedPts.length >= 2 && (
          <path d={pathFromPoints(realisedPts)} fill="none" stroke={COLORS.realised} strokeWidth={1.5} />
        )}
        <circle cx={xScale(0)} cy={yScale(0)} r={3} fill={COLORS.realised} />
      </svg>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: COLORS.muted, display: "flex", gap: 14, flexWrap: "wrap" }}>
        <span>
          80% band: {rows.map((r) => pct(r.band80_width)).join(" ")}
        </span>
        <span>
          vs EWMA ×: {rows.map((r) => r.width_ratio.toFixed(2)).join(" ")}
        </span>
        <span>p50 is not a direction call · H4* drawn but unscored by v13 · EWMA λ=0.94 outline</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write `DensityConeStrip.tsx`**

Full content:

```tsx
"use client";

import {
  useSpxDensityIssued,
  type SpxDensityForecast,
} from "@/lib/regime/useSpxDensity";
import { linearScale, pathFromBand, pathFromPoints, type Point } from "@/lib/svgChart";

const W = 160;
const H = 110;
const PAD = { top: 8, right: 8, bottom: 16, left: 8 };

const COLORS = {
  band: "var(--accent-vol, #7c6cf0)",
  realised: "var(--accent-warm, #F5A623)",
  muted: "var(--text-muted)",
  good: "var(--positive, #22c55e)",
  bad: "var(--negative, #ef4444)",
};

function MiniCone({ f }: { f: SpxDensityForecast }) {
  const rows = f.rows;
  const xScale = linearScale([0, 5], [PAD.left, W - PAD.right]);
  const vals: number[] = [0];
  for (const r of rows) {
    vals.push(r.q05, r.q95);
    if (r.realised_return != null) vals.push(r.realised_return);
  }
  const lo = Math.min(...vals) * 1.1;
  const hi = Math.max(...vals) * 1.1;
  const yScale = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);

  const edge = (key: "q05" | "q10" | "q25" | "q75" | "q90" | "q95"): Point[] => [
    [xScale(0), yScale(0)],
    ...rows.map((r, i) => [xScale(i + 1), yScale(r[key])] as Point),
  ];
  const realised: Point[] = [[xScale(0), yScale(0)]];
  for (const r of rows) {
    if (r.realised_return != null) realised.push([xScale(r.h), yScale(r.realised_return)]);
  }

  const settled = rows.filter((r) => r.inside_band80 != null && r.scored_horizon);
  const misses = settled.filter((r) => r.inside_band80 === false);
  const badge =
    settled.length === 0
      ? "PENDING"
      : misses.length === 0
        ? `IN ${settled.length}/${settled.length} ✓`
        : `OUT@H${misses[0].h} ✗`;
  const badgeColor =
    settled.length === 0 ? COLORS.muted : misses.length === 0 ? COLORS.good : COLORS.bad;

  return (
    <div style={{ border: "1px solid var(--border-dim)", borderRadius: 4, padding: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 9, color: COLORS.muted }}>
        <span>
          {f.as_of}
          {f.origin === "reconstructed" ? " · RECON" : ""}
          {f.fallback_used ? " · EWMA FB" : ""}
        </span>
        <span style={{ color: badgeColor }}>{badge}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", display: "block" }}>
        <path d={pathFromBand(edge("q05"), edge("q95"))} fill={COLORS.band} fillOpacity={0.12} />
        <path d={pathFromBand(edge("q10"), edge("q90"))} fill={COLORS.band} fillOpacity={0.2} />
        <path d={pathFromBand(edge("q25"), edge("q75"))} fill={COLORS.band} fillOpacity={0.32} />
        {realised.length >= 2 && (
          <path d={pathFromPoints(realised)} fill="none" stroke={COLORS.realised} strokeWidth={1.2} />
        )}
        {realised.slice(1).map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={2} fill={COLORS.realised} />
        ))}
      </svg>
    </div>
  );
}

export default function DensityConeStrip() {
  const { data } = useSpxDensityIssued();
  const forecasts = data?.forecasts ?? [];
  if (forecasts.length === 0) return null;

  const rates = data?.hit_rates ?? [];
  const fmt = (o: string) => {
    const r = rates.find((x) => x.origin === o);
    return r ? `${r.inside}/${r.total}` : "0/0";
  };

  return (
    <div data-testid="spx-density-strip">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
        {forecasts.map((f) => (
          <MiniCone key={f.as_of} f={f} />
        ))}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: COLORS.muted, marginTop: 6 }}>
        80%-band hit rate (scored horizons) · prospective {fmt("prospective")} · reconstructed {fmt("reconstructed")} (in-sample)
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Mount into the Market Tide sub-tab**

In `web/components/regime/MarketTideSubTab.tsx`, add imports:

```tsx
import DensityConePanel from "./DensityConePanel";
import DensityConeStrip from "./DensityConeStrip";
```

and inside the fragment, directly AFTER the `{priorData && priorData.sessions.length > 0 && (<MarketTideChart data={priorData} />)}` block (still inside the `section-body` flex column):

```tsx
            <DensityConePanel />
            <DensityConeStrip />
```

- [ ] **Step 4: Component vitest**

`web/tests/unit/density-cone.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DensityConePanel from "@/components/regime/DensityConePanel";

const HORIZON = (h: number) => ({
  h,
  target_date: `2026-08-0${h}`,
  scored_horizon: h !== 4,
  q05: -0.016, q10: -0.0117, q25: -0.0044, q50: 0.001, q75: 0.0069, q90: 0.0123, q95: 0.0154,
  baseline_q05: -0.0141, baseline_q10: -0.011, baseline_q25: -0.0058, baseline_q50: 0,
  baseline_q75: 0.0058, baseline_q90: 0.0111, baseline_q95: 0.0143,
  band80_width: 0.024, baseline_band80_width: 0.0221, width_ratio: 1.085,
  realised_return: null, inside_band80: null,
});

const LATEST = {
  forecast: {
    as_of: "2026-07-30",
    anchor_close: 7437.63,
    origin: "prospective",
    fallback_used: false,
    params: { omega: 0.039, alpha: 0.014, gamma: 0.236, beta: 0.834 },
    rows: [1, 2, 3, 4, 5].map(HORIZON),
  },
  recent_path: [
    { date: "2026-07-29", close: 7316.15 },
    { date: "2026-07-30", close: 7437.63 },
  ],
  disclaimer: "Display-only",
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => LATEST }),
  );
});

describe("DensityConePanel", () => {
  it("renders the display-only chip and the honesty copy", async () => {
    render(<DensityConePanel />);
    expect(
      await screen.findByText(/DISPLAY ONLY · NOT A TRADING SIGNAL/),
    ).toBeTruthy();
    expect(await screen.findByText(/p50 is not a direction call/)).toBeTruthy();
    expect(screen.getByTestId("spx-density-panel")).toBeTruthy();
  });

  it("shows the fallback warning when fallback_used", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        ...LATEST,
        forecast: { ...LATEST.forecast, fallback_used: true, params: null },
      }),
    });
    render(<DensityConePanel />);
    expect(
      await screen.findByText(/EWMA FALLBACK — GJR fit unavailable/),
    ).toBeTruthy();
  });
});
```

- [ ] **Step 5: Run + commit**

Run: `cd web && npm run test && npx tsc --noEmit`
Expected: all green.

```bash
git add web/components/regime/DensityConePanel.tsx web/components/regime/DensityConeStrip.tsx web/components/regime/MarketTideSubTab.tsx web/tests/unit/density-cone.test.tsx
git commit -m "feat(density-web): cone panel + issued strip on the Market Tide tab"
```

---

### Task 12: Backfill + refit-staleness scripts

**Recommended executor: sonnet.**

**Files:**
- Create: `scripts/backfill/spx_density_backfill.py`, `scripts/research/spx_density_refit_staleness.py`, `docs/research/spx-density-cone/refit_staleness.json`

**Interfaces:**
- Consumes: `compute_forecast(bars, as_of=...)`, `result_to_db_rows`, `SpxDensityRepository`, `spx_density_forecast_job._settle_pass`.
- Produces: `reconstructed` history rows; the committed staleness trace backing spec §2.1.

- [ ] **Step 1: Write the backfill script**

`scripts/backfill/spx_density_backfill.py` (full content):

```python
"""Seed origin='reconstructed' spx_density_forecast history (spec §5: in-sample rows,
badged and tallied separately from prospective).

Each historical as_of reuses compute_forecast's as_of truncation, so the seed is the
v13 panel-index convention — bit-faithful to what the model would have issued that night.
Settles all rows at the end.

Usage:
  uv run python scripts/backfill/spx_density_backfill.py --sessions 60 [--dry-run]
Persists to Postgres (uw_scan.spx_density_forecast) — the durable trace IS the table.
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.density.constants import PANEL_FIRST_DATE
from uw_scan.density.forecast import (
    PanelMismatchError,
    compute_forecast,
    result_to_db_rows,
)
from uw_scan.storage.spx_density_repository import SpxDensityRepository
from uw_scan.worker.jobs.spx_density_forecast import _settle_pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("spx_density_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        sdr = SpxDensityRepository(conn, schema=settings.db_schema)
        bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
        if len(bars) < 2:
            log.error("no SPX series in vol_index_daily — run vol_index_lake_sync first")
            return 1

        existing = set(sdr.fetch_recent_as_ofs(args.sessions + 10))
        # candidates: the last N session dates, excluding the freshest (that one is the
        # nightly job's prospective anchor, never the backfill's)
        candidates = [d for d, _ in bars[-(args.sessions + 1) : -1]]
        wrote = skipped = 0
        for as_of in candidates:
            if as_of in existing:
                skipped += 1
                continue
            try:
                result = compute_forecast(bars, as_of=as_of)
            except PanelMismatchError as exc:
                log.error("REFUSING (%s): %s", as_of, exc)
                return 1
            if args.dry_run:
                log.info("would write %s (fallback=%s)", as_of, result.fallback_used)
                continue
            sdr.upsert_rows(result_to_db_rows(result, origin="reconstructed"))
            wrote += 1
            log.info("wrote %s seed=%d fallback=%s", as_of, result.seed, result.fallback_used)

        settled = 0 if args.dry_run else _settle_pass(sdr)
        log.info("done: wrote=%d skipped=%d settled=%d", wrote, skipped, settled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the refit-staleness script**

`scripts/research/spx_density_refit_staleness.py` (full content — the spec §2.1 measurement, now self-contained on argon's vendored code + packaged panel, no signal-lab checkout needed):

```python
"""How much does refit cadence move the cone? (spec §2.1's measurement, committed)

Fits arm G at the committed 2026-07-30 anchor, then with params fitted 5/10/21/42/63
trading days earlier, drawing the SAME anchor cone from each vector — exactly what the
v13 recovery_ladder does on a non-refit day. Answers: is daily refitting worth anything
over monthly? (Measured 2026-08-01: worst delta 0.77 bp on a 240-510 bp band.)

Reproduce:
  uv run python scripts/research/spx_density_refit_staleness.py
Writes docs/research/spx-density-cone/refit_staleness.json (committed trace).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from uw_scan.density.cone import gjr_std_boot_cone
from uw_scan.density.constants import (
    BAND_80,
    H_MAX,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit
from uw_scan.density.forecast import load_frozen_panel

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
OUT = REPO / "docs" / "research" / "spx-density-cone" / "refit_staleness.json"


def main() -> int:
    golden = json.loads(GOLDEN.read_text())
    panel = load_frozen_panel()
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    arr = np.asarray(closes, dtype=float)
    r = arr[1:] / arr[:-1] - 1.0

    i = len(r) - 1
    hist = r[: i + 1]
    anchor_close = float(golden["anchor"]["close"])
    anchor_ts = pd.Timestamp(golden["anchor"]["date"])
    seed = int(seed_for(i))
    lo, hi = BAND_80

    rows = []
    for age in (0, 5, 10, 21, 42, 63):
        params, _ = _fit(ARMS["G"], r[: i + 1 - age])
        if params is None:
            rows.append({"param_age_days": age, "fitted": False})
            continue
        cone = gjr_std_boot_cone(
            hist, anchor_close, anchor_ts, H_MAX, params,
            M=M_PATHS, seed=seed, burn_in=OVERLAY_BURN_IN, min_pool=OVERLAY_MIN_POOL,
        )
        rows.append({
            "param_age_days": age,
            "fitted": True,
            "params": {k: float(v) for k, v in params.items()},
            "persistence": float(params["alpha"] + params["gamma"] / 2.0 + params["beta"]),
            "band80_pct": {
                h: round(float(cone.at(h)[hi] - cone.at(h)[lo]) * 100, 4)
                for h in range(1, H_MAX + 1)
            },
        })

    base = next(x for x in rows if x["param_age_days"] == 0 and x.get("fitted"))
    for x in rows:
        if x.get("fitted"):
            x["band80_delta_vs_fresh_bp"] = {
                h: round((x["band80_pct"][h] - base["band80_pct"][h]) * 100, 2)
                for h in base["band80_pct"]
            }

    out = {
        "reproduce": "uv run python scripts/research/spx_density_refit_staleness.py",
        "anchor": {"date": golden["anchor"]["date"], "close": anchor_close, "index": i, "seed": seed},
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the staleness script and check against the spec**

Run: `uv run python scripts/research/spx_density_refit_staleness.py`
Expected: fresh row shows persistence ≈ 0.96623, band80 H1 ≈ 2.4022%, H5 ≈ 5.0996%; deltas ≤ ~0.8 bp — matching the spec §2.1 table (small differences beyond the printed precision are a red flag: investigate before committing).

- [ ] **Step 4: Dry-run the backfill against the local dev DB**

Run: `uv run python scripts/backfill/spx_density_backfill.py --sessions 5 --dry-run`
Expected: either lists 5 would-write dates, or exits 1 with "no SPX series" if the local `vol_index_daily` is empty/stale (fine on the MacBook — the real backfill runs on the mini; see Task 13).

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill/spx_density_backfill.py scripts/research/spx_density_refit_staleness.py docs/research/spx-density-cone/refit_staleness.json
git commit -m "feat(density): reconstructed backfill + committed refit-staleness trace"
```

---

### Task 13: E2E, full-suite green, CHANGELOG, deploy checklist

**Recommended executor: sonnet.** Orchestrator runs the final review.

**Files:**
- Create: `web/tests/e2e/regime-density.spec.ts`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Playwright e2e**

`web/tests/e2e/regime-density.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

test("Market Tide tab renders the density cone area", async ({ page }) => {
  await page.goto("/regime/tide");
  await expect(page.getByTestId("market-tide-subtab")).toBeVisible();
  // Panel renders in every state (loading / empty / populated) — the testid is the contract.
  await expect(page.getByTestId("spx-density-panel")).toBeVisible();
});
```

Run: `cd web && npm run test:e2e -- regime-density` (requires the dev stack: `bash scripts/dev.sh`).
Expected: PASS.

- [ ] **Step 2: CHANGELOG entry**

In `CHANGELOG.md` under `[Unreleased]` (match the file's existing section style — Added/Changed):

```markdown
- SPX 1–5 day conditional density cone on the Regime → Market Tide tab: signal-lab
  v13 GJR-GARCH model (verdict PASS) ported verbatim with a zero-tolerance golden
  parity gate in CI; nightly issue + settle job (`UW_SCAN_SPX_DENSITY_ENABLED`,
  default off), `spx_density_forecast` table (migration 111), display-only fan chart
  + 5-up issued strip with prospective/reconstructed hit-rate tallies.
```

- [ ] **Step 3: Full local suite**

Run, in order (reproduce the FULL CI job locally per the standing rule):

```bash
uv run ruff check .
uv run pytest
cd web && npm run test && npx tsc --noEmit && cd ..
uv run python scripts/check_no_yahoo.py
```
Expected: all green. Ruff on the vendored files: fix ONLY with `# noqa` annotations, never by editing vendored bodies (Global Constraint 1).

- [ ] **Step 4: Smoke on the MacBook dev stack (real worker path)**

Per the standing rule — API → DB → worker → DB → web page, never a `/tmp` side-channel:

1. Ensure local `vol_index_daily` has current SPX (`bash scripts/dev.sh` runs the stack; the 03:15 sync job may need the lake mirror to be current — if the MacBook mirror is stale, this smoke moves to the mini, step 5).
2. Add `UW_SCAN_SPX_DENSITY_ENABLED=1` to `.env`, restart the dev stack (workers freeze env at fork).
3. Seed history through the productionised path: `uv run python scripts/backfill/spx_density_backfill.py --sessions 10`.
4. Verify API: `curl -s http://127.0.0.1:8400/api/regime/spx-density | python3 -m json.tool | head -40` — forecast non-null, 5 rows.
5. Verify web: open `http://localhost:3001/regime/tide` — cone panel + strip render; screenshot to `output/playwright/spx-density-cone.png`.

- [ ] **Step 5: Pre-enable checklist for the mini (record in the PR description)**

These run AFTER merge/deploy, but the checklist is written now:

1. ⚠️ **Verify SPX freshness on the mini** (spec §13.1): `SELECT MAX(trade_date) FROM uw_scan.vol_index_daily WHERE symbol='SPX'` against the mini's `option_wizard` DB (via the argon container's psql or a Tailscale-scoped session per the three-tier DB rules). Must be the last trading session. If stale, fix the lake sync BEFORE enabling — a stale anchor draws a cone from the wrong close.
2. Apply migration 111 via the profile-gated migrator (per the Docker deploy runbook).
3. Run the backfill (`--sessions 60`) in-container so the strip has history.
4. Set `UW_SCAN_SPX_DENSITY_ENABLED=1` in the mini's argon `.env`; restart the worker (env frozen at fork).
5. Next morning: check the 03:30 ET `spx_density_forecast_tick` log line shows `issued: 5, fallback_used: False`, and the tide tab renders it.

- [ ] **Step 6: Final commit + PR**

```bash
git add web/tests/e2e/regime-density.spec.ts CHANGELOG.md output/playwright/spx-density-cone.png
git commit -m "feat(density): e2e coverage + changelog"
git push -u origin feat/spx-density-cone
gh pr create --title "feat: SPX 1-5d density cone (signal-lab v13 port) on Market Tide" --body "<summary per template: what/why, the fidelity mechanism (verbatim vendoring + zero-tolerance golden gate), the pre-enable mini checklist from Task 13 Step 5, and the v13 authorisation ceiling>"
```
Wait for CI green. Do not merge before every check passes.

---

## Self-review checklist (orchestrator, after all tasks)

1. **Fidelity audit:** diff every vendored body in `density/{constants,cone,fit}.py` against its `$LAB` line range one final time; confirm the parity gate ran in CI (not skipped).
2. **Spec coverage:** §1-§3 → Tasks 1-4,6; §4-§5 → Tasks 5,8; §6 component table → Tasks 5-12; §7 → Task 7; §8 UI rules → Task 11 (check every copy rule); §9 error table → Tasks 6-7 (each row has a labelled path); §10 test table → Tasks 4,5,6,7,11,13; §11 fast alarms → provenance/params persisted (surfacing to /api/health is spec'd as optional ~15 lines — NOT in this plan; note as follow-up in the PR).
3. **No naked `git push origin main`, no merge before green, CHANGELOG rode the PR.**





