# VRP Tradable Iron Condor + Backtest (per-ticker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing VRP *measurement* layer (harvest = IV − RV in vol points, OOS-gated, keyed by bucket) into a **tradable defined-risk iron-condor layer** — a model-repriced backtest, a per-ticker candidate emitter, and a paper ledger — where the bucket verdict is demoted to a gate and execution is per individual ticker.

**Architecture:** A pure flat-vol Black-Scholes module turns `(spot, IV, hold-days)` into a concrete 16Δ/8Δ iron condor with a modeled entry credit. A backtest engine replays history per ticker (enter on RICH days, hold to expiry, settle against the corp-action-adjusted realized price path, net of a tunable cost model) and reports **two numbers per unit: full-history characterization and an honest latest-40%-holdout headline** (the same split the measurement's walk-forward already uses). A daily emitter writes per-ticker candidates gated by `ticker ∈ HARVEST_SELLABLE bucket`; a worker-path paper ledger opens/marks/closes simulated positions; a forward-NBBO recorder accrues a true-fill dataset for later model calibration. The bucket is **only ever a gate lookup** — every row, candidate, and position is keyed per ticker.

**Tech Stack:** Python 3.13 (`uv` only), psycopg 3, FastAPI + Pydantic v2, APScheduler 3, `statistics.NormalDist` for N(·)/N⁻¹(·) (stdlib — no scipy/numpy in the pricer), Next.js 16 + React 19 (hand-rolled SVG), Vitest + pytest/pytest-postgresql.

## Global Constraints

- **No naked shorts — defined-risk only.** The iron condor is the *only* structure; every short leg is covered by a long wing. No code path may emit an uncovered short. (CLAUDE.md standing rule.)
- **uv only.** `uv run pytest …`, never bare `python`/`pip`/`pytest`.
- **Persist analytical results to Postgres.** Every backtest/candidate/ledger output lands in a table in the same call — never in-memory-only. (Standing rule + `[[feedback_persist_results_to_db]]`.)
- **Per-row commit + rollback in worker jobs.** The scheduler's `_repo()` closes the connection WITHOUT committing (psycopg rolls back on close). Every job commits per ticker/position and `rollback()`s on a per-item `except` to recover `InFailedSqlTransaction`. (This is exactly the corp-actions P1 fixed in PR #149.)
- **Module size budget <500 lines/file; split at 1000.** New persistence goes in its own `storage/vrp_trading.py` mixin, never appended to `repository.py`. New API endpoints go in a new `api/routers/vrp.py`, not bolted onto `regime.py`.
- **Migrations idempotent** (`CREATE TABLE IF NOT EXISTS`, header `SET search_path TO uw_scan, public;`). Re-running is a no-op. Next lexical number: `081_`.
- **API contract additions only.** New models go in a new `models/vrp.py` domain module, re-exported from `models/__init__.py`; regenerate `web/lib/types.ts` via `npm run gen:types` (surgical, alphabetical — see `[[reference_generated_files_alphabetically_frozen]]`).
- **Reuse the measurement layer, don't fork it.** Entry trigger reuses `RICH_Z = 1.0` and `_deviation_class`; the realized path reuses `apply_split_adjustment` + the corp-action/earnings fetchers; the holdout split reuses `HOLDOUT_FRAC = 0.40`.
- **Flat-vol pricing is a disclosed approximation.** v1 prices all four legs off the single `vrp_daily.iv` (no skew). It is directionally faithful (sell rich IV, pay realized RV, truncated by wings) but the absolute credit is approximate; skew is a v2 overlay. Every result table and the UI must label this.
- **No Yahoo. Data priority IB → UW → FMP → massive.** The forward-NBBO recorder uses the UW option chain only.
- **No secrets to Codex subprocesses; never commit without explicit user request; never `git push origin main`.**

---

## File Structure

**Create:**
- `src/uw_scan/storage/migrations/081_vrp_trading.sql` — 5 tables (candidates, backtest_results, backtest_trades, paper_positions, leg_nbbo).
- `src/uw_scan/reports/vrp_structure.py` — **pure** pricer: `bs_price`, `bs_delta`, `strike_for_delta`, `build_iron_condor`, `condor_expiry_pnl`, `CostModel`, `IronCondor`.
- `src/uw_scan/reports/vrp_backtest.py` — per-ticker + universe model-repriced backtest engine (hold-to-expiry, full + holdout scopes).
- `src/uw_scan/reports/vrp_candidates.py` — today's per-ticker emitter (RICH × SELLABLE-bucket × earnings-clear).
- `src/uw_scan/storage/vrp_trading.py` — `_VrpTradingMixin` (candidates / backtest results / trades / positions / leg-nbbo).
- `src/uw_scan/worker/jobs/vrp_trading_jobs.py` — `vrp_candidates_refresh`, `vrp_paper_open`, `vrp_paper_mark`, `vrp_backtest_refresh`, `vrp_nbbo_record`.
- `src/uw_scan/models/vrp.py` — response/row Pydantic models.
- `src/uw_scan/api/routers/vrp.py` — `/vrp/candidates`, `/vrp/backtest`, `/vrp/paper`.
- `web/app/vrp/page.tsx` + `web/components/vrp/*` — candidates table, backtest summary, paper ledger.
- Tests mirroring each module under `tests/unit/` and `tests/integration/`.

**Modify:**
- `src/uw_scan/storage/repository.py` — add `_VrpTradingMixin` to imports + the `Repository` base list (before `_BaseMixin`).
- `src/uw_scan/config.py` — add tunable cost/structure settings.
- `src/uw_scan/worker/scheduler.py` — wire the 5 new jobs (wrappers + `add_job`).
- `src/uw_scan/api/server.py` — `include_router(vrp.router, prefix="/api", tags=["vrp"])`.
- `src/uw_scan/models/__init__.py` — re-export the new models.
- `web/lib/types.ts` — regenerated.

---

## Task 1: Config knobs for structure + cost model

**Files:**
- Modify: `src/uw_scan/config.py`
- Test: `tests/unit/test_config_vrp_trading.py`

**Interfaces:**
- Produces: `Settings.vrp_hold_days: int`, `vrp_short_delta: float`, `vrp_wing_delta: float`, `vrp_risk_free_rate: float`, `vrp_cost_per_contract: float`, `vrp_slippage_frac: float`, `vrp_slippage_min: float`, `vrp_cost_round_trip: bool`.

> **IMPORTANT (verified against config.py):** `Settings` is a plain `BaseModel` with `api_key: SecretStr = Field(...)` **required** — `Settings()` raises. Direct construction in tests uses `Settings(api_key=SecretStr("test"))`. Env overrides are NOT automatic (not `BaseSettings`); they are wired by `Settings.from_env()` mapping each `UW_SCAN_*` var inline via `int()`/`float()`/`_env_bool` (config.py has only `_env_bool` — no `_env_int`/`_env_float`). So new env vars require BOTH a class field (default) AND a line in `from_env()`'s `return cls(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_vrp_trading.py
from pathlib import Path

from pydantic import SecretStr

from uw_scan.config import Settings

_NO_ENV = Path("/nonexistent/.env")  # force from_env to read process env only


def test_vrp_trading_defaults():
    s = Settings(api_key=SecretStr("test"))
    assert s.vrp_hold_days == 20          # trading days; ≈ the harvest peak T+20
    assert s.vrp_short_delta == 0.16
    assert s.vrp_wing_delta == 0.08
    assert 0.0 <= s.vrp_risk_free_rate < 0.20
    assert s.vrp_cost_per_contract == 0.65
    assert s.vrp_slippage_frac == 0.01
    assert s.vrp_slippage_min == 0.05
    assert s.vrp_cost_round_trip is True


def test_vrp_env_override(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "test")
    monkeypatch.setenv("UW_SCAN_VRP_HOLD_DAYS", "30")
    monkeypatch.setenv("UW_SCAN_VRP_SLIPPAGE_MIN", "0.10")
    s = Settings.from_env(env_path=_NO_ENV)
    assert s.vrp_hold_days == 30
    assert s.vrp_slippage_min == 0.10


def test_vrp_delta_ordering_validated():
    import pytest
    with pytest.raises(ValueError):
        Settings(api_key=SecretStr("test"), vrp_wing_delta=0.20, vrp_short_delta=0.16)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config_vrp_trading.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'vrp_hold_days'`

- [ ] **Step 3: Add the fields + a validator + the from_env mapping**

Add to the `Settings` `BaseModel` (class body — defaults live here):

```python
    # --- VRP tradable iron-condor + backtest (plan 2026-06-22) ----------------
    # hold is in TRADING days to stay unit-consistent with the harvest measurement
    # (HORIZON=20). t_years = hold_days / 252 feeds Black-Scholes.
    vrp_hold_days: int = 20
    vrp_short_delta: float = 0.16        # short put/call strike target |delta|
    vrp_wing_delta: float = 0.08         # long wing strike target |delta|
    vrp_risk_free_rate: float = 0.04     # flat r for BS; tiny effect at short DTE
    vrp_cost_per_contract: float = 0.65  # commission per leg per side
    vrp_slippage_frac: float = 0.01      # half-spread as fraction of leg mid
    vrp_slippage_min: float = 0.05       # half-spread floor per leg (price points)
    vrp_cost_round_trip: bool = True     # charge open + close (conservative)
```

Add a `@model_validator(mode="after")` (or extend an existing one) enforcing the structure invariant (ISSUE-9):

```python
    @model_validator(mode="after")
    def _check_vrp(self) -> "Settings":
        if not (0.0 < self.vrp_wing_delta < self.vrp_short_delta < 0.5):
            raise ValueError("require 0 < vrp_wing_delta < vrp_short_delta < 0.5")
        if self.vrp_hold_days <= 0:
            raise ValueError("vrp_hold_days must be positive")
        return self
```

Wire env overrides into `from_env()`'s `return cls(...)`. NOTE (verified): config.py has only `_env_bool`; ints/floats are read inline as `int/float(os.environ.get(name, default))` (the same way `db_port` / `max_requests_per_minute` already are). Do NOT use `_env_int`/`_env_float` — they don't exist.

```python
            vrp_hold_days=int(os.environ.get("UW_SCAN_VRP_HOLD_DAYS", "20")),
            vrp_short_delta=float(os.environ.get("UW_SCAN_VRP_SHORT_DELTA", "0.16")),
            vrp_wing_delta=float(os.environ.get("UW_SCAN_VRP_WING_DELTA", "0.08")),
            vrp_risk_free_rate=float(os.environ.get("UW_SCAN_VRP_RISK_FREE_RATE", "0.04")),
            vrp_cost_per_contract=float(os.environ.get("UW_SCAN_VRP_COST_PER_CONTRACT", "0.65")),
            vrp_slippage_frac=float(os.environ.get("UW_SCAN_VRP_SLIPPAGE_FRAC", "0.01")),
            vrp_slippage_min=float(os.environ.get("UW_SCAN_VRP_SLIPPAGE_MIN", "0.05")),
            vrp_cost_round_trip=_env_bool("UW_SCAN_VRP_COST_ROUND_TRIP", True),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config_vrp_trading.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/config.py tests/unit/test_config_vrp_trading.py
git commit -m "feat(vrp): config knobs for iron-condor structure + cost model"
```

---

## Task 2: Pure pricer — Black-Scholes, strike-from-delta, iron condor, expiry P&L

**Files:**
- Create: `src/uw_scan/reports/vrp_structure.py`
- Test: `tests/unit/test_vrp_structure.py`

**Interfaces:**
- Produces:
  - `bs_price(S, K, T, r, sigma, *, is_call) -> float`
  - `bs_delta(S, K, T, r, sigma, *, is_call) -> float`
  - `strike_for_delta(S, T, r, sigma, target_delta, *, is_call) -> float` (target_delta is the OTM magnitude 0<δ<0.5)
  - `@dataclass(frozen=True) IronCondor` with `short_put, long_put, short_call, long_call, credit, put_width, call_width, max_loss, leg_premiums: tuple[float,float,float,float]`
  - `build_iron_condor(S, sigma, T, r, *, short_delta, wing_delta) -> IronCondor`
  - `condor_expiry_pnl(condor, S_T) -> float` (per-share gross, credit minus spread losses)
  - `@dataclass(frozen=True) CostModel(per_contract, slippage_frac, slippage_min, round_trip, n_legs=4, multiplier=100)` with `total(self, leg_premiums, contracts) -> float` (dollars)
- Consumes: nothing (pure; `math` + `statistics.NormalDist` only).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_vrp_structure.py
import math

import pytest

from uw_scan.reports.vrp_structure import (
    CostModel,
    bs_delta,
    bs_price,
    build_iron_condor,
    condor_expiry_pnl,
    strike_for_delta,
)

S, T, R, SIG = 100.0, 20 / 252, 0.04, 0.30


def test_bs_put_call_parity():
    c = bs_price(S, 100.0, T, R, SIG, is_call=True)
    p = bs_price(S, 100.0, T, R, SIG, is_call=False)
    # C - P = S - K e^{-rT}
    assert c - p == pytest.approx(S - 100.0 * math.exp(-R * T), abs=1e-9)


def test_strike_for_delta_recovers_delta():
    k_call = strike_for_delta(S, T, R, SIG, 0.16, is_call=True)
    k_put = strike_for_delta(S, T, R, SIG, 0.16, is_call=False)
    assert k_call > S > k_put  # OTM both sides
    assert bs_delta(S, k_call, T, R, SIG, is_call=True) == pytest.approx(0.16, abs=1e-3)
    assert abs(bs_delta(S, k_put, T, R, SIG, is_call=False)) == pytest.approx(
        0.16, abs=1e-3
    )


def test_iron_condor_well_formed():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    assert ic.long_put < ic.short_put < S < ic.short_call < ic.long_call
    assert ic.credit > 0
    assert ic.put_width > 0 and ic.call_width > 0
    # defined-risk identity: max loss = widest wing minus credit collected
    assert ic.max_loss == pytest.approx(
        max(ic.put_width, ic.call_width) - ic.credit, abs=1e-9
    )
    assert ic.credit < max(ic.put_width, ic.call_width)  # credit can't exceed width


def test_expiry_pnl_max_profit_inside_short_strikes():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    # settle dead center → both spreads expire worthless → keep full credit
    assert condor_expiry_pnl(ic, S) == pytest.approx(ic.credit, abs=1e-9)


def test_expiry_pnl_max_loss_below_long_put():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    deep = ic.long_put - 10.0  # below the long put → full put-spread loss
    pnl = condor_expiry_pnl(ic, deep)
    assert pnl == pytest.approx(ic.credit - ic.put_width, abs=1e-9)
    assert pnl < 0


def test_cost_model_positive_and_round_trip_doubles():
    legs = (1.0, 0.5, 1.0, 0.5)
    one = CostModel(0.65, 0.01, 0.05, round_trip=False)
    two = CostModel(0.65, 0.01, 0.05, round_trip=True)
    assert one.total(legs, contracts=1) > 0
    assert two.total(legs, contracts=1) == pytest.approx(2 * one.total(legs, 1), abs=1e-9)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_vrp_structure.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the pure module**

```python
# src/uw_scan/reports/vrp_structure.py
"""Pure flat-vol option pricing → defined-risk iron condor → expiry P&L.

No DB, no I/O, no scipy/numpy. N(·) and N⁻¹(·) come from statistics.NormalDist
(Python 3.13 stdlib). FLAT-VOL APPROXIMATION (plan §Global Constraints): all four
legs are priced off a single ATM IV — skew is ignored, so absolute credit is
approximate while the harvest direction (sell rich IV, pay realized RV, truncated
by wings) is faithful. Skew overlay is a v2.

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()  # standard normal; .cdf / .inv_cdf


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool) -> float:
    """Black-Scholes premium per share. Degenerate (T<=0 or sigma<=0) → intrinsic."""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    if is_call:
        return S * _N.cdf(d1) - K * disc * _N.cdf(d2)
    return K * disc * _N.cdf(-d2) - S * _N.cdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool) -> float:
    """Spot delta. Call ∈ (0,1); put ∈ (-1,0)."""
    if T <= 0 or sigma <= 0:
        intrinsic = (S > K) if is_call else (S < K)
        return (1.0 if is_call else -1.0) if intrinsic else 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _N.cdf(d1) if is_call else _N.cdf(d1) - 1.0


def strike_for_delta(
    S: float, T: float, r: float, sigma: float, target_delta: float, *, is_call: bool
) -> float:
    """Invert delta→strike under flat vol. target_delta is the OTM magnitude
    (0<δ<0.5). Call: d1 = N⁻¹(δ); Put: d1 = -N⁻¹(δ). K = S·exp((r+σ²/2)T − d1·σ√T)."""
    d1 = _N.inv_cdf(target_delta)
    if not is_call:
        d1 = -d1
    return S * math.exp((r + 0.5 * sigma * sigma) * T - d1 * sigma * math.sqrt(T))


@dataclass(frozen=True)
class IronCondor:
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    credit: float
    put_width: float
    call_width: float
    max_loss: float
    leg_premiums: tuple[float, float, float, float]  # sp, lp, sc, lc (per share)


def build_iron_condor(
    S: float, sigma: float, T: float, r: float, *, short_delta: float, wing_delta: float
) -> IronCondor:
    """Symmetric 4-leg condor at the given short/wing deltas, priced flat-vol.
    Guards: positive spot/vol/T and 0 < wing_delta < short_delta < 0.5, else the
    strikes collapse (sigma→0 maps every strike to spot·e^{rT}) or invert."""
    if S <= 0 or sigma <= 0 or T <= 0:
        raise ValueError(f"build_iron_condor needs S,sigma,T > 0 (got {S},{sigma},{T})")
    if not (0.0 < wing_delta < short_delta < 0.5):
        raise ValueError("require 0 < wing_delta < short_delta < 0.5")
    sp = strike_for_delta(S, T, r, sigma, short_delta, is_call=False)
    lp = strike_for_delta(S, T, r, sigma, wing_delta, is_call=False)
    sc = strike_for_delta(S, T, r, sigma, short_delta, is_call=True)
    lc = strike_for_delta(S, T, r, sigma, wing_delta, is_call=True)
    sp_p = bs_price(S, sp, T, r, sigma, is_call=False)
    lp_p = bs_price(S, lp, T, r, sigma, is_call=False)
    sc_p = bs_price(S, sc, T, r, sigma, is_call=True)
    lc_p = bs_price(S, lc, T, r, sigma, is_call=True)
    credit = (sp_p - lp_p) + (sc_p - lc_p)  # short premia minus long premia
    put_width = sp - lp
    call_width = lc - sc
    max_loss = max(put_width, call_width) - credit
    return IronCondor(
        short_put=sp,
        long_put=lp,
        short_call=sc,
        long_call=lc,
        credit=credit,
        put_width=put_width,
        call_width=call_width,
        max_loss=max_loss,
        leg_premiums=(sp_p, lp_p, sc_p, lc_p),
    )


def condor_expiry_pnl(condor: IronCondor, S_T: float) -> float:
    """Per-share gross P&L held to expiry against settlement price S_T:
    credit collected minus the realized loss on whichever spread is breached.
    Each spread loss is capped by its wing → defined risk."""
    put_loss = max(0.0, condor.short_put - S_T) - max(0.0, condor.long_put - S_T)
    call_loss = max(0.0, S_T - condor.short_call) - max(0.0, S_T - condor.long_call)
    return condor.credit - put_loss - call_loss


@dataclass(frozen=True)
class CostModel:
    per_contract: float          # commission per leg per side
    slippage_frac: float         # half-spread as fraction of leg mid
    slippage_min: float          # half-spread floor per leg (price points)
    round_trip: bool = True
    n_legs: int = 4
    multiplier: int = 100

    def total(self, leg_premiums: tuple[float, ...], contracts: int) -> float:
        """Dollar cost: per-leg half-spread (max of floor and frac·mid) + commission,
        ×(2 if round_trip)·contracts. Slippage is in price points → ×multiplier."""
        sides = 2 if self.round_trip else 1
        slip_pts = sum(max(self.slippage_min, self.slippage_frac * abs(p)) for p in leg_premiums)
        slip_dollars = slip_pts * self.multiplier * contracts * sides
        commission = self.per_contract * self.n_legs * contracts * sides
        return slip_dollars + commission
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_vrp_structure.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_structure.py tests/unit/test_vrp_structure.py
git commit -m "feat(vrp): pure flat-vol pricer — BS, strike-from-delta, iron condor, expiry P&L"
```

---

## Task 3: Schema — migration 081 (5 tables)

**Files:**
- Create: `src/uw_scan/storage/migrations/081_vrp_trading.sql`
- Test: `tests/integration/storage/test_migration_081_idempotent.py`

**Interfaces:**
- Produces tables: `vrp_trade_candidates`, `vrp_backtest_results`, `vrp_backtest_trades`, `vrp_paper_positions`, `vrp_leg_nbbo`.

- [ ] **Step 1: Write the migration**

```sql
-- 081_vrp_trading.sql
-- VRP tradable iron-condor layer: per-ticker candidates, model-repriced backtest
-- (results + per-trade detail), paper ledger, and forward true-fill NBBO capture.
-- Flat-vol pricing (skew ignored) — see plan. Idempotent.
-- Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_trade_candidates (
    ticker          TEXT NOT NULL,
    as_of           DATE NOT NULL,
    structure       TEXT NOT NULL DEFAULT 'iron_condor',
    spot            NUMERIC,
    iv              NUMERIC,
    vrp_z           NUMERIC,
    hold_days       INTEGER NOT NULL,
    short_put       NUMERIC, long_put  NUMERIC,
    short_call      NUMERIC, long_call NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    put_width       NUMERIC, call_width NUMERIC,
    entry_cost      NUMERIC,                 -- modeled round-trip cost (CostModel) carried to the paper ledger
    bucket_sector   TEXT,
    bucket_verdict  TEXT,
    earnings_clear  BOOLEAN NOT NULL DEFAULT TRUE,
    contracts       INTEGER NOT NULL DEFAULT 1,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);
COMMENT ON TABLE uw_scan.vrp_trade_candidates IS
    'Daily per-ticker iron-condor candidates (RICH × SELLABLE-bucket × earnings-clear). Flat-vol modeled credit.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_backtest_results (
    unit_type            TEXT NOT NULL,   -- 'ticker' | 'bucket'
    unit_key             TEXT NOT NULL,   -- ticker symbol | sector name
    hold_days            INTEGER NOT NULL,
    scope                TEXT NOT NULL,   -- 'full' | 'holdout'
    n_trades             INTEGER NOT NULL DEFAULT 0,
    n_wins               INTEGER NOT NULL DEFAULT 0,
    win_rate             NUMERIC,
    mean_net             NUMERIC,
    median_net           NUMERIC,
    total_net            NUMERIC,
    mean_return_on_risk  NUMERIC,
    breach_rate          NUMERIC,   -- fraction of trades that breached a SHORT strike (entered loss zone)
    mean_credit          NUMERIC,
    as_of                DATE,
    inserted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_type, unit_key, hold_days, scope)
);
COMMENT ON TABLE uw_scan.vrp_backtest_results IS
    'Model-repriced condor backtest summary per unit. scope=full is characterization; scope=holdout (latest 40%) is the honest headline.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_backtest_trades (
    ticker          TEXT NOT NULL,
    entry_date      DATE NOT NULL,
    hold_days       INTEGER NOT NULL,
    expiry_date     DATE,
    spot_entry      NUMERIC, spot_exit NUMERIC, iv_entry NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    gross_pnl       NUMERIC, net_pnl   NUMERIC,
    return_on_risk  NUMERIC,
    breached        BOOLEAN,
    in_holdout      BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, entry_date, hold_days)
);
COMMENT ON TABLE uw_scan.vrp_backtest_trades IS
    'Per-trade detail backing vrp_backtest_results (audit + holdout flag).';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_paper_positions (
    position_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker          TEXT NOT NULL,
    opened_on       DATE NOT NULL,
    hold_days       INTEGER NOT NULL,
    expiry_on       DATE NOT NULL,
    short_put       NUMERIC, long_put  NUMERIC,
    short_call      NUMERIC, long_call NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    entry_cost      NUMERIC,                 -- modeled round-trip cost; netted into realized/unrealized P&L
    contracts       INTEGER NOT NULL DEFAULT 1,
    spot_entry      NUMERIC, iv_entry  NUMERIC,
    status          TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'closed'
    last_mark_on    DATE,
    mark_value      NUMERIC,
    unrealized_pnl  NUMERIC,
    closed_on       DATE,
    exit_value      NUMERIC,
    realized_pnl    NUMERIC,
    mark_source     TEXT NOT NULL DEFAULT 'model', -- 'model' | 'nbbo'
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, opened_on)  -- one paper position per candidate per day (idempotent open)
);
COMMENT ON TABLE uw_scan.vrp_paper_positions IS
    'Simulated iron-condor positions: open → daily model mark → close at expiry (realized payoff vs adjusted price).';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_leg_nbbo (
    position_id     BIGINT NOT NULL REFERENCES uw_scan.vrp_paper_positions(position_id) ON DELETE CASCADE,
    leg             TEXT NOT NULL,   -- short_put | long_put | short_call | long_call
    capture_date    DATE NOT NULL,
    strike          NUMERIC,
    expiry          DATE,
    option_symbol   TEXT,
    nbbo_bid        NUMERIC, nbbo_ask NUMERIC, last_price NUMERIC, iv NUMERIC,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (position_id, leg, capture_date)
);
COMMENT ON TABLE uw_scan.vrp_leg_nbbo IS
    'Forward real NBBO per candidate leg — the true-fill dataset to later calibrate model credit error. No consumer yet.';

COMMIT;
```

- [ ] **Step 2: Write the idempotency test**

```python
# tests/integration/storage/test_migration_081_idempotent.py
def test_081_tables_present(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='uw_scan' AND table_name LIKE 'vrp_%'"
        )
        names = {r[0] for r in cur.fetchall()}
    assert {
        "vrp_trade_candidates",
        "vrp_backtest_results",
        "vrp_backtest_trades",
        "vrp_paper_positions",
        "vrp_leg_nbbo",
    } <= names
```

- [ ] **Step 3: Apply + verify idempotent locally**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh` (second run must be a clean no-op)
Then: `uv run pytest tests/integration/storage/test_migration_081_idempotent.py -v`
Expected: PASS (migrations apply once per session via conftest; the assert finds all 5 tables)

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/081_vrp_trading.sql tests/integration/storage/test_migration_081_idempotent.py
git commit -m "feat(vrp): migration 081 — candidates, backtest, paper ledger, leg-nbbo tables"
```

---

## Task 4: Storage mixin — `_VrpTradingMixin`

**Files:**
- Create: `src/uw_scan/storage/vrp_trading.py`
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_vrp_trading_repo.py`

**Interfaces:**
- Consumes: `self._conn`, `self._schema`, and the generic helpers from `_VrpResearchMixin` are NOT shared (different mixin) — replicate the tiny `_upsert` locally to stay self-contained.
- Produces (on `Repository`):
  - `upsert_vrp_candidate(**row)`, `clear_vrp_candidates(as_of)`, `fetch_vrp_candidates(as_of=None) -> list[dict]`
  - `upsert_vrp_backtest_result(**row)`, `clear_vrp_backtest_results()`, `fetch_vrp_backtest_results(hold_days=None) -> list[dict]`
  - `upsert_vrp_backtest_trade(**row)`, `clear_vrp_backtest_trades()`
  - `open_vrp_paper_position(**row) -> int | None` (returns position_id; `None` if `(ticker,opened_on)` already exists), `fetch_open_vrp_paper_positions() -> list[dict]`, `update_vrp_paper_mark(position_id, **fields)`, `close_vrp_paper_position(position_id, **fields)`, `fetch_vrp_paper_positions(status=None) -> list[dict]`
  - `upsert_vrp_leg_nbbo(**row)`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/storage/test_vrp_trading_repo.py
from datetime import date


def test_candidate_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_candidate(
        ticker="NVDA", as_of=date(2026, 6, 22), structure="iron_condor",
        spot=120.0, iv=0.45, vrp_z=1.8, hold_days=20,
        short_put=110.0, long_put=104.0, short_call=130.0, long_call=136.0,
        entry_credit=1.8, max_loss=4.2, put_width=6.0, call_width=6.0,
        bucket_sector="Semis", bucket_verdict="HARVEST_SELLABLE",
        earnings_clear=True, contracts=1,
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_candidates(as_of=date(2026, 6, 22))
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["bucket_verdict"] == "HARVEST_SELLABLE"


def test_paper_open_is_idempotent_per_day(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    base = dict(
        ticker="AAPL", opened_on=date(2026, 6, 22), hold_days=20,
        expiry_on=date(2026, 7, 21), short_put=180.0, long_put=174.0,
        short_call=200.0, long_call=206.0, entry_credit=1.5, max_loss=4.5,
        contracts=1, spot_entry=190.0, iv_entry=0.30,
    )
    pid = repo.open_vrp_paper_position(**base)
    repo.conn.commit()
    assert isinstance(pid, int)
    dup = repo.open_vrp_paper_position(**base)   # same (ticker, opened_on)
    repo.conn.commit()
    assert dup is None
    assert len(repo.fetch_open_vrp_paper_positions()) == 1


def test_close_position(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    pid = repo.open_vrp_paper_position(
        ticker="MSFT", opened_on=date(2026, 6, 1), hold_days=20,
        expiry_on=date(2026, 6, 29), short_put=400.0, long_put=390.0,
        short_call=450.0, long_call=460.0, entry_credit=2.0, max_loss=8.0,
        contracts=1, spot_entry=425.0, iv_entry=0.25,
    )
    repo.conn.commit()
    repo.close_vrp_paper_position(
        pid, closed_on=date(2026, 6, 29), exit_value=0.5, realized_pnl=150.0
    )
    repo.conn.commit()
    closed = repo.fetch_vrp_paper_positions(status="closed")
    assert closed[0]["realized_pnl"] == 150.0
    assert not repo.fetch_open_vrp_paper_positions()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/storage/test_vrp_trading_repo.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'upsert_vrp_candidate'`)

- [ ] **Step 3: Implement the mixin**

```python
# src/uw_scan/storage/vrp_trading.py
"""VRP tradable-layer persistence: candidates, backtest results/trades, paper
ledger, forward leg-NBBO. Self-contained generic upsert (identifiers hardcoded,
values always parameterized). Full-rewrite where noted; per-row commits are the
CALLER's responsibility (scheduler _repo() does not commit on close).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg


class _VrpTradingMixin:
    _conn: psycopg.Connection
    _schema: str

    def _vt_upsert(self, table: str, pk: tuple[str, ...], row: dict) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
        sql = (
            f"INSERT INTO {self._schema}.{table} ({', '.join(cols)}) "
            f"VALUES ({placeholders}) ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))

    def _vt_fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    # ── candidates ───────────────────────────────────────────────────────────
    def clear_vrp_candidates(self, as_of: _date) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.vrp_trade_candidates WHERE as_of = %s",
                (as_of,),
            )

    def upsert_vrp_candidate(self, **row: Any) -> None:
        self._vt_upsert("vrp_trade_candidates", ("ticker", "as_of"), row)

    def fetch_vrp_candidates(self, as_of: _date | None = None) -> list[dict[str, Any]]:
        if as_of is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_trade_candidates "
                "WHERE as_of = (SELECT max(as_of) FROM "
                f"{self._schema}.vrp_trade_candidates) ORDER BY ticker"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_trade_candidates WHERE as_of = %s ORDER BY ticker",
            (as_of,),
        )

    def fetch_distinct_vrp_tickers(self) -> list[str]:
        # convenience mirror of vrp_markout._all_vrp_tickers for the trading layer
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker FROM {self._schema}.vrp_daily ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]

    # ── backtest ─────────────────────────────────────────────────────────────
    def clear_vrp_backtest_results(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.vrp_backtest_results")

    def clear_vrp_backtest_trades(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.vrp_backtest_trades")

    def upsert_vrp_backtest_result(self, **row: Any) -> None:
        self._vt_upsert(
            "vrp_backtest_results", ("unit_type", "unit_key", "hold_days", "scope"), row
        )

    def upsert_vrp_backtest_trade(self, **row: Any) -> None:
        self._vt_upsert("vrp_backtest_trades", ("ticker", "entry_date", "hold_days"), row)

    def fetch_vrp_backtest_results(
        self, hold_days: int | None = None
    ) -> list[dict[str, Any]]:
        if hold_days is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_backtest_results "
                "ORDER BY unit_type, unit_key, scope"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_backtest_results WHERE hold_days = %s "
            "ORDER BY unit_type, unit_key, scope",
            (hold_days,),
        )

    # ── paper ledger ─────────────────────────────────────────────────────────
    def open_vrp_paper_position(self, **row: Any) -> int | None:
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        sql = (
            f"INSERT INTO {self._schema}.vrp_paper_positions ({', '.join(cols)}) "
            f"VALUES ({placeholders}) ON CONFLICT (ticker, opened_on) DO NOTHING "
            "RETURNING position_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))
            got = cur.fetchone()
        return int(got[0]) if got else None

    def fetch_open_vrp_paper_positions(self) -> list[dict[str, Any]]:
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_paper_positions WHERE status = 'open' "
            "ORDER BY opened_on, ticker"
        )

    def fetch_vrp_paper_positions(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_paper_positions ORDER BY opened_on DESC, ticker"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_paper_positions WHERE status = %s "
            "ORDER BY opened_on DESC, ticker",
            (status,),
        )

    def update_vrp_paper_mark(self, position_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k} = %s" for k in fields)
        sql = (
            f"UPDATE {self._schema}.vrp_paper_positions SET {sets}, updated_at = now() "
            "WHERE position_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (*fields.values(), position_id))

    def close_vrp_paper_position(self, position_id: int, **fields: Any) -> None:
        fields["status"] = "closed"
        sets = ", ".join(f"{k} = %s" for k in fields)
        sql = (
            f"UPDATE {self._schema}.vrp_paper_positions SET {sets}, updated_at = now() "
            "WHERE position_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (*fields.values(), position_id))

    # ── forward true-fill NBBO ───────────────────────────────────────────────
    def upsert_vrp_leg_nbbo(self, **row: Any) -> None:
        self._vt_upsert("vrp_leg_nbbo", ("position_id", "leg", "capture_date"), row)
```

- [ ] **Step 4: Register the mixin**

In `src/uw_scan/storage/repository.py`, add the import next to the other `from .vrp_*` lines:
```python
from .vrp_trading import _VrpTradingMixin
```
and add `_VrpTradingMixin,` to the `class Repository(...)` base list, immediately after `_VrpResearchMixin,` (before `_WatchlistMixin,` / `_BaseMixin`).

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/integration/storage/test_vrp_trading_repo.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/vrp_trading.py src/uw_scan/storage/repository.py tests/integration/storage/test_vrp_trading_repo.py
git commit -m "feat(vrp): _VrpTradingMixin — candidates, backtest, paper ledger persistence"
```

---

## Task 5: Backtest engine — per-ticker, hold-to-expiry, full + holdout

**Files:**
- Create: `src/uw_scan/reports/vrp_backtest.py`
- Test: `tests/integration/reports/test_vrp_backtest.py`, `tests/unit/test_vrp_backtest_pnl.py`

**Interfaces:**
- Consumes: `vrp_structure` (Task 2); `vrp_markout_core.apply_split_adjustment`; `vrp_markout.{RICH_Z,_load_vrp_series}`; repo fetchers `fetch_price_series`, `fetch_corporate_actions`, `fetch_earnings_events`.
- Produces:
  - `backtest_ticker(repo, ticker, *, hold_days, short_delta, wing_delta, r, cost_model, contracts=1) -> list[TradeResult]`
  - `@dataclass TradeResult(ticker, entry_date, expiry_date, spot_entry, spot_exit, iv_entry, entry_credit, max_loss, gross_pnl, net_pnl, return_on_risk, breached, in_holdout)`
  - `summarize(trades, *, scope) -> dict` (scope, n_trades, n_wins, win_rate, mean_net, median_net, total_net, mean_return_on_risk, breach_rate, mean_credit)
  - `run_vrp_backtest(*, repo, settings, hold_days=None) -> dict` (universe; full-rewrite results+trades; per-ticker AND per-sector-bucket rows; gated by `vrp_harvest_by_sector` verdict; commits)

- [ ] **Step 1: Write the unit test for trade mechanics**

```python
# tests/unit/test_vrp_backtest_pnl.py
from uw_scan.reports.vrp_structure import CostModel, build_iron_condor
from uw_scan.reports.vrp_backtest import single_trade_pnl

COST = CostModel(0.65, 0.01, 0.05, round_trip=True)


def test_quiet_settlement_is_profit():
    ic = build_iron_condor(100.0, 0.30, 20 / 252, 0.04, short_delta=0.16, wing_delta=0.08)
    net, ror, breached = single_trade_pnl(ic, S_T=100.0, cost=COST, contracts=1)
    assert net > 0 and not breached and ror > 0


def test_tail_settlement_caps_at_defined_risk():
    ic = build_iron_condor(100.0, 0.30, 20 / 252, 0.04, short_delta=0.16, wing_delta=0.08)
    net, ror, breached = single_trade_pnl(ic, S_T=ic.long_put - 20, cost=COST, contracts=1)
    # loss bounded by max_loss × 100 + costs; never worse than that
    assert net < 0 and breached
    assert net >= -(ic.max_loss * 100) - COST.total(ic.leg_premiums, 1) - 1e-6
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_vrp_backtest_pnl.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the engine**

```python
# src/uw_scan/reports/vrp_backtest.py
"""Model-repriced iron-condor backtest (hold-to-expiry).

For each RICH day with an earnings-clear forward window, build a flat-vol condor
at that day's spot+IV, then settle it against the corporate-action-adjusted
realized price `hold_days` trading days forward. Reports a full-history
characterization AND an honest latest-40%-holdout headline (HOLDOUT_FRAC). The
bucket verdict (vrp_harvest_by_sector) is a per-ticker GATE; rows are per ticker
and per sector. Full-rewrite; commits at the end.

LOOKAHEAD NOTE: scope='full' gates on the FINAL bucket verdict over the same
window it backtests → mild lookahead; scope='holdout' is the headline. Documented
in the plan (§Known limitations).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from statistics import median
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import RICH_Z, _load_vrp_series
from uw_scan.reports.vrp_markout_core import HOLDOUT_FRAC, apply_split_adjustment
from uw_scan.reports.vrp_structure import CostModel, build_iron_condor, condor_expiry_pnl
from uw_scan.reports.vrp_markout import _events_overlap

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeResult:
    ticker: str
    entry_date: _date
    expiry_date: _date
    spot_entry: float
    spot_exit: float
    iv_entry: float
    entry_credit: float
    max_loss: float
    gross_pnl: float
    net_pnl: float
    return_on_risk: float
    breached: bool
    in_holdout: bool


def single_trade_pnl(condor, S_T: float, *, cost: CostModel, contracts: int):
    """(net_dollars, return_on_risk, breached) for one condor held to expiry."""
    gross_per_share = condor_expiry_pnl(condor, S_T)
    gross = gross_per_share * cost.multiplier * contracts
    costs = cost.total(condor.leg_premiums, contracts)
    net = gross - costs
    risk = condor.max_loss * cost.multiplier * contracts
    ror = net / risk if risk > 0 else 0.0
    breached = S_T < condor.short_put or S_T > condor.short_call
    return net, ror, breached


def backtest_ticker(
    repo,
    ticker: str,
    *,
    hold_days: int,
    short_delta: float,
    wing_delta: float,
    r: float,
    cost_model: CostModel,
    contracts: int = 1,
) -> list[TradeResult]:
    rows = _load_vrp_series(repo, ticker)
    if not rows:
        return []
    adj = apply_split_adjustment(
        repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
    )
    if not adj:
        return []
    pidx = {d: k for k, (d, _v) in enumerate(adj)}
    events = repo.fetch_earnings_events(ticker)
    t_years = hold_days / 252.0
    ordered = sorted(rows, key=lambda x: x["market_date"])
    trades: list[TradeResult] = []
    for row in ordered:
        z = row["vrp_z_20"]
        iv = row["iv"]
        if z is None or iv is None or float(iv) <= 0 or float(z) < RICH_Z:
            continue  # iv<=0 collapses all strikes to spot (zero-width condor) — skip
        t = row["market_date"]
        pi = pidx.get(t)
        if pi is None or pi + hold_days >= len(adj):
            continue
        expiry_date, S_T = adj[pi + hold_days]
        # earnings-clear over the holding window (reuse the buffered overlap test)
        if _events_overlap(t, expiry_date, events):
            continue
        S0 = adj[pi][1]
        if S0 <= 0:
            continue
        condor = build_iron_condor(
            S0, float(iv), t_years, r, short_delta=short_delta, wing_delta=wing_delta
        )
        net, ror, breached = single_trade_pnl(
            condor, S_T, cost=cost_model, contracts=contracts
        )
        trades.append(
            TradeResult(
                ticker=ticker, entry_date=t, expiry_date=expiry_date,
                spot_entry=S0, spot_exit=S_T, iv_entry=float(iv),
                entry_credit=condor.credit, max_loss=condor.max_loss,
                gross_pnl=net + cost_model.total(condor.leg_premiums, contracts),
                net_pnl=net, return_on_risk=ror, breached=breached, in_holdout=False,
            )
        )
    # flag the latest HOLDOUT_FRAC of trades by entry_date as the honest holdout
    n = len(trades)
    if n:
        cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
        trades = [
            TradeResult(**{**t.__dict__, "in_holdout": i >= cut})
            for i, t in enumerate(sorted(trades, key=lambda x: x.entry_date))
        ]
    return trades


def summarize(trades: list[TradeResult], *, scope: str) -> dict[str, Any]:
    sel = trades if scope == "full" else [t for t in trades if t.in_holdout]
    n = len(sel)
    if n == 0:
        return {"scope": scope, "n_trades": 0, "n_wins": 0, "win_rate": None,
                "mean_net": None, "median_net": None, "total_net": None,
                "mean_return_on_risk": None, "breach_rate": None, "mean_credit": None}
    nets = [t.net_pnl for t in sel]
    wins = sum(1 for x in nets if x > 0)
    return {
        "scope": scope, "n_trades": n, "n_wins": wins, "win_rate": wins / n,
        "mean_net": sum(nets) / n, "median_net": median(nets), "total_net": sum(nets),
        "mean_return_on_risk": sum(t.return_on_risk for t in sel) / n,
        "breach_rate": sum(1 for t in sel if t.breached) / n,
        "mean_credit": sum(t.entry_credit for t in sel) / n,
    }


def _sellable_sectors(repo) -> set[str]:
    """Sectors whose RICH single-name bucket is HARVEST_SELLABLE (the gate)."""
    out: set[str] = set()
    for r in repo.fetch_vrp_harvest_by_sector():
        if r["deviation_class"] == "RICH" and r["verdict"] == "HARVEST_SELLABLE":
            out.add(r["sector"])
    return out


def run_vrp_backtest(*, repo, settings, hold_days: int | None = None) -> dict[str, Any]:
    today = _date.today()
    hd = hold_days or settings.vrp_hold_days
    cost = CostModel(
        settings.vrp_cost_per_contract, settings.vrp_slippage_frac,
        settings.vrp_slippage_min, round_trip=settings.vrp_cost_round_trip,
    )
    sellable = _sellable_sectors(repo)
    repo.clear_vrp_backtest_results()
    repo.clear_vrp_backtest_trades()
    by_sector: dict[str, list[TradeResult]] = defaultdict(list)
    n_units = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        sector = repo.fetch_watchlist_sector(ticker)
        ac = asset_class_baseline(ticker, sector=sector)["asset_class"]
        # v1 gate: ONLY the validated single-name-by-sector edge is tradable.
        # index_macro / sector_etf / credit have no studied sector bucket → skip.
        if ac != "single_name":
            continue
        if (sector or "unknown") not in sellable:
            continue
        # ISSUE-6: a single name with no earnings calendar cannot honor the
        # (entry, expiry] earnings exclusion → would manufacture a SELLABLE edge.
        # Mirrors run_vrp_markout's single_name skip-guard.
        if not repo.fetch_historical_earnings_dates(ticker):
            continue
        try:
            trades = backtest_ticker(
                repo, ticker, hold_days=hd, short_delta=settings.vrp_short_delta,
                wing_delta=settings.vrp_wing_delta, r=settings.vrp_risk_free_rate,
                cost_model=cost,
            )
            if not trades:
                continue
            # SAVEPOINT per ticker: one bad ticker's upsert cannot abort the whole
            # full-rewrite (psycopg3 conn.transaction() nests as a savepoint).
            with repo.conn.transaction():
                for t in trades:
                    repo.upsert_vrp_backtest_trade(
                        ticker=t.ticker, entry_date=t.entry_date, hold_days=hd,
                        expiry_date=t.expiry_date, spot_entry=t.spot_entry,
                        spot_exit=t.spot_exit, iv_entry=t.iv_entry,
                        entry_credit=t.entry_credit, max_loss=t.max_loss,
                        gross_pnl=t.gross_pnl, net_pnl=t.net_pnl,
                        return_on_risk=t.return_on_risk, breached=t.breached,
                        in_holdout=t.in_holdout,
                    )
                for scope in ("full", "holdout"):
                    repo.upsert_vrp_backtest_result(
                        unit_type="ticker", unit_key=ticker, hold_days=hd,
                        as_of=today, **summarize(trades, scope=scope)
                    )
            n_units += 1
            if sector:
                by_sector[sector].extend(trades)
        except Exception as exc:  # noqa: BLE001
            log.exception("vrp_backtest ticker %s failed: %s", ticker, repr(exc))
    with repo.conn.transaction():
        for sector, trades in by_sector.items():
            for scope in ("full", "holdout"):
                repo.upsert_vrp_backtest_result(
                    unit_type="bucket", unit_key=sector, hold_days=hd,
                    as_of=today, **summarize(trades, scope=scope)
                )
    repo.conn.commit()
    return {"units": n_units, "hold_days": hd, "sellable_sectors": sorted(sellable)}
```

- [ ] **Step 4: Run the unit test — pass**

Run: `uv run pytest tests/unit/test_vrp_backtest_pnl.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write + run the integration test (synthetic series → directional P&L)**

```python
# tests/integration/reports/test_vrp_backtest.py
from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_backtest import run_vrp_backtest


def _seed_quiet_rich_ticker(repo, ticker="TESTQ"):
    """High IV, then a FLAT realized path → condor expires at max profit every time."""
    start = date(2024, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(80):
            d = start + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 0.60, 0.10, 0.50, 2.0),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 100.0),  # flat → zero realized move
            )
    repo.conn.commit()


def test_quiet_rich_ticker_is_profitable(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_quiet_rich_ticker(repo)
    # make its sector SELLABLE so the gate admits it
    repo.upsert_vrp_harvest_by_sector(
        sector="unknown", deviation_class="RICH", verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.4, mean_holdout=0.4, rich_cheap_spread=None, n=80,
        n_holdout=32, survives_walkforward=True, survives_window_gate=True,
        confidence="med", as_of=date(2024, 4, 1),
    )
    repo.conn.commit()
    out = run_vrp_backtest(repo=repo, settings=Settings(api_key=SecretStr("test")), hold_days=20)
    assert out["units"] >= 1
    rows = {(r["unit_key"], r["scope"]): r for r in repo.fetch_vrp_backtest_results(20)}
    full = rows[("TESTQ", "full")]
    assert full["n_trades"] > 0
    assert full["total_net"] > 0          # flat path + rich IV → net positive after costs
    assert full["breach_rate"] == 0       # never breached a short strike
    assert ("TESTQ", "holdout") in rows    # honest headline present


def test_non_sellable_sector_is_excluded(seeded_db_empty_cards, monkeypatch):
    """Gate negative: a RICH single name whose sector bucket is NOT SELLABLE
    must produce zero backtest rows."""
    repo = seeded_db_empty_cards
    _seed_quiet_rich_ticker(repo, ticker="EXCL")
    monkeypatch.setattr(repo, "fetch_watchlist_sector", lambda t: "BadSector")
    # seed a SELLABLE bucket for a DIFFERENT sector only
    repo.upsert_vrp_harvest_by_sector(
        sector="GoodSector", deviation_class="RICH", verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.4, mean_holdout=0.4, rich_cheap_spread=None, n=80,
        n_holdout=32, survives_walkforward=True, survives_window_gate=True,
        confidence="med", as_of=date(2024, 4, 1),
    )
    repo.conn.commit()
    run_vrp_backtest(repo=repo, settings=Settings(api_key=SecretStr("test")), hold_days=20)
    rows = {(r["unit_key"], r["scope"]) for r in repo.fetch_vrp_backtest_results(20)}
    assert ("EXCL", "full") not in rows   # excluded by the SELLABLE-sector gate
```

Run: `uv run pytest tests/integration/reports/test_vrp_backtest.py -v`
Expected: PASS (asset_class for an unknown-sector synthetic ticker resolves to `single_name`; the `unknown` sector is seeded SELLABLE, so the gate admits it.)

> Implementer check: if `asset_class_baseline("TESTQ")` does not resolve to `single_name`, adjust the gate seed accordingly — verify with a quick `python -c` against `asset_class_baseline` before asserting.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/vrp_backtest.py tests/unit/test_vrp_backtest_pnl.py tests/integration/reports/test_vrp_backtest.py
git commit -m "feat(vrp): model-repriced condor backtest — per-ticker + sector, full + holdout"
```

---

## Task 6: Candidate emitter (today, per-ticker, bucket-gated)

**Files:**
- Create: `src/uw_scan/reports/vrp_candidates.py`
- Test: `tests/integration/reports/test_vrp_candidates.py`

**Interfaces:**
- Consumes: `vrp_structure.build_iron_condor`; repo `fetch_distinct_vrp_tickers`, `_load_vrp_series` (latest row), `fetch_watchlist_sector`, `fetch_vrp_harvest_by_sector`, `fetch_earnings_events`, `fetch_price_series`, `fetch_corporate_actions`.
- Produces: `run_vrp_candidates(*, repo, settings, as_of=None) -> dict` — clears today's candidates, writes one row per ticker that is currently RICH, in a SELLABLE sector, earnings-clear over the forward window; commits per ticker.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/reports/test_vrp_candidates.py
from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_candidates import run_vrp_candidates


def test_emits_rich_sellable_candidate(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 5, 1)
    with repo.conn.cursor() as cur:
        for i in range(30):
            d = start + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                ("CAND", d, 0.50, 0.20, 0.30, 2.0),  # currently RICH
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                ("CAND", d, 100.0),
            )
    repo.upsert_vrp_harvest_by_sector(
        sector="unknown", deviation_class="RICH", verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.3, mean_holdout=0.3, rich_cheap_spread=None, n=30,
        n_holdout=12, survives_walkforward=True, survives_window_gate=True,
        confidence="med", as_of=date(2026, 5, 30),
    )
    repo.conn.commit()
    out = run_vrp_candidates(repo=repo, settings=Settings(api_key=SecretStr("test")))
    assert out["written"] >= 1
    rows = repo.fetch_vrp_candidates()
    cand = next(r for r in rows if r["ticker"] == "CAND")
    assert cand["bucket_verdict"] == "HARVEST_SELLABLE"
    assert cand["long_put"] < cand["short_put"] < cand["short_call"] < cand["long_call"]
    assert cand["entry_credit"] > 0 and cand["max_loss"] > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/reports/test_vrp_candidates.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the emitter**

```python
# src/uw_scan/reports/vrp_candidates.py
"""Today's per-ticker iron-condor candidates: RICH × SELLABLE-sector × earnings-
clear. Flat-vol modeled credit. Full-rewrite for as_of; commits per ticker (the
scheduler _repo() does not commit on close — see plan §Global Constraints).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from datetime import date as _date, timedelta
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import RICH_Z, _events_overlap, _load_vrp_series
from uw_scan.reports.vrp_markout_core import apply_split_adjustment
from uw_scan.reports.vrp_structure import CostModel, build_iron_condor

log = logging.getLogger(__name__)


def _sellable_sectors(repo) -> set[str]:
    return {
        r["sector"]
        for r in repo.fetch_vrp_harvest_by_sector()
        if r["deviation_class"] == "RICH" and r["verdict"] == "HARVEST_SELLABLE"
    }


def run_vrp_candidates(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    today = as_of or _date.today()
    hd = settings.vrp_hold_days
    t_years = hd / 252.0
    sellable = _sellable_sectors(repo)
    cost = CostModel(
        settings.vrp_cost_per_contract, settings.vrp_slippage_frac,
        settings.vrp_slippage_min, round_trip=settings.vrp_cost_round_trip,
    )
    repo.clear_vrp_candidates(today)
    repo.conn.commit()  # durable even if zero tickers qualify (per-ticker commits
    #                     would otherwise leave the DELETE uncommitted → rolled back
    #                     on close → stale candidates survive; idempotency bug)
    written = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        try:
            rows = _load_vrp_series(repo, ticker)
            # ISSUE-7: align the signal to as_of (no future leak on backfill runs)
            eligible = [r for r in rows if r["market_date"] <= today]
            if not eligible:
                continue
            latest = eligible[-1]
            z, iv = latest["vrp_z_20"], latest["iv"]
            if z is None or iv is None or float(iv) <= 0 or float(z) < RICH_Z:
                continue  # iv<=0 → degenerate condor; skip
            sector = repo.fetch_watchlist_sector(ticker)
            ac = asset_class_baseline(ticker, sector=sector)["asset_class"]
            if ac != "single_name":               # v1: single-name-by-sector edge only
                continue
            if (sector or "unknown") not in sellable:
                continue
            # ISSUE-6: can't honor the earnings exclusion without a calendar → don't emit
            if not repo.fetch_historical_earnings_dates(ticker):
                continue
            # spot = adjusted close on the SIGNAL date (entry), not the series tail
            adj = apply_split_adjustment(
                repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
            )
            pmap = {d: v for d, v in adj}
            entry = latest["market_date"]
            spot = pmap.get(entry)
            if spot is None or spot <= 0:
                continue
            window_end = entry + timedelta(days=int(round(hd * 7 / 5)))  # ~cal days
            events = repo.fetch_earnings_events(ticker)
            if _events_overlap(entry, window_end, events):
                continue  # earnings inside the forward window → stand aside
            ic = build_iron_condor(
                spot, float(iv), t_years, settings.vrp_risk_free_rate,
                short_delta=settings.vrp_short_delta, wing_delta=settings.vrp_wing_delta,
            )
            verdict = "HARVEST_SELLABLE"  # passed the single-name + SELLABLE-sector gate
            repo.upsert_vrp_candidate(
                ticker=ticker, as_of=today, structure="iron_condor", spot=spot,
                iv=float(iv), vrp_z=float(z), hold_days=hd,
                short_put=ic.short_put, long_put=ic.long_put,
                short_call=ic.short_call, long_call=ic.long_call,
                entry_credit=ic.credit, max_loss=ic.max_loss,
                put_width=ic.put_width, call_width=ic.call_width,
                entry_cost=cost.total(ic.leg_premiums, 1),
                bucket_sector=sector, bucket_verdict=verdict,
                earnings_clear=True, contracts=1,
            )
            repo.conn.commit()
            written += 1
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_candidates failed for %s: %s", ticker, repr(exc))
    return {"written": written, "as_of": today.isoformat()}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/integration/reports/test_vrp_candidates.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_candidates.py tests/integration/reports/test_vrp_candidates.py
git commit -m "feat(vrp): daily per-ticker candidate emitter (RICH × SELLABLE × earnings-clear)"
```

---

## Task 7: Paper ledger jobs — open / mark / close (worker path)

**Files:**
- Create: `src/uw_scan/worker/jobs/vrp_trading_jobs.py`
- Test: `tests/integration/worker/test_vrp_paper_ledger.py`

**Interfaces:**
- Consumes: repo paper-ledger methods (Task 4); `vrp_structure.{build_iron_condor, condor_expiry_pnl}`; `vrp_candidates.run_vrp_candidates`; `vrp_backtest.run_vrp_backtest`.
- Produces:
  - `vrp_candidates_refresh(*, repo, settings) -> dict` (wraps `run_vrp_candidates`)
  - `vrp_backtest_refresh(*, repo, settings) -> dict` (wraps `run_vrp_backtest`)
  - `vrp_paper_open(*, repo, settings) -> dict` — open paper positions for today's candidates (idempotent via UNIQUE)
  - `vrp_paper_mark(*, repo, settings) -> dict` — for each open position: model-reprice at latest spot+IV; if today ≥ expiry, close with realized expiry payoff; else update unrealized. Per-position commit + rollback.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/worker/test_vrp_paper_ledger.py
from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.jobs.vrp_trading_jobs import vrp_paper_mark, vrp_paper_open


def _seed_candidate_and_prices(repo):
    open_day = date(2026, 5, 1)
    repo.upsert_vrp_candidate(
        ticker="PAP", as_of=open_day, structure="iron_condor", spot=100.0, iv=0.5,
        vrp_z=2.0, hold_days=20, short_put=90.0, long_put=84.0, short_call=110.0,
        long_call=116.0, entry_credit=2.0, max_loss=4.0, put_width=6.0, call_width=6.0,
        bucket_sector="unknown", bucket_verdict="HARVEST_SELLABLE",
        earnings_clear=True, contracts=1,
    )
    with repo.conn.cursor() as cur:
        for i in range(40):
            d = open_day + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                ("PAP", d, 0.40, 0.20, 0.20, 1.5),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                ("PAP", d, 100.0),  # flat → settles at max profit
            )
    repo.conn.commit()
    return open_day


def test_open_then_close_at_expiry(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    open_day = _seed_candidate_and_prices(repo)
    s = Settings(api_key=SecretStr("test"))
    opened = vrp_paper_open(repo=repo, settings=s, as_of=open_day)
    assert opened["opened"] == 1
    assert len(repo.fetch_open_vrp_paper_positions()) == 1
    # mark on a date past expiry → position closes at realized expiry payoff
    far = open_day + timedelta(days=35)
    marked = vrp_paper_mark(repo=repo, settings=s, as_of=far)
    assert marked["closed"] == 1
    closed = repo.fetch_vrp_paper_positions(status="closed")
    assert closed[0]["realized_pnl"] is not None
    assert closed[0]["realized_pnl"] > 0   # flat path → keep credit minus costs
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/worker/test_vrp_paper_ledger.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the jobs**

```python
# src/uw_scan/worker/jobs/vrp_trading_jobs.py
"""VRP tradable-layer worker jobs: candidate refresh, backtest refresh, paper
ledger open/mark/close. Each loop commits per ticker/position and rolls back on a
per-item except (scheduler _repo() does not commit on close; one bad row must not
poison the rest — InFailedSqlTransaction). Mirrors corporate_actions_jobs.

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from typing import Any

from uw_scan.reports.vrp_backtest import run_vrp_backtest
from uw_scan.reports.vrp_candidates import run_vrp_candidates
from uw_scan.reports.vrp_markout_core import apply_split_adjustment
from uw_scan.reports.vrp_structure import IronCondor, condor_expiry_pnl

log = logging.getLogger(__name__)
_MULT = 100


def vrp_candidates_refresh(*, repo, settings) -> dict[str, Any]:
    return run_vrp_candidates(repo=repo, settings=settings)


def vrp_backtest_refresh(*, repo, settings) -> dict[str, Any]:
    return run_vrp_backtest(repo=repo, settings=settings)


def vrp_paper_open(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    """Open a paper position for each of today's candidates (idempotent via the
    (ticker, opened_on) unique key). expiry_on is a FUTURE date (hold_days trading
    days ≈ calendar days); the mark job settles only once the realized price series
    actually reaches it — so a position can never close the same day it opens
    (ISSUE-1)."""
    today = as_of or _date.today()
    candidates = repo.fetch_vrp_candidates(as_of=today)
    opened = 0
    for c in candidates:
        try:
            expiry_on = c["as_of"] + timedelta(days=int(round(c["hold_days"] * 7 / 5)))
            pid = repo.open_vrp_paper_position(
                ticker=c["ticker"], opened_on=c["as_of"], hold_days=c["hold_days"],
                expiry_on=expiry_on, short_put=c["short_put"], long_put=c["long_put"],
                short_call=c["short_call"], long_call=c["long_call"],
                entry_credit=c["entry_credit"], max_loss=c["max_loss"],
                entry_cost=c.get("entry_cost"), contracts=c["contracts"],
                spot_entry=c["spot"], iv_entry=c["iv"],
            )
            repo.conn.commit()
            if pid is not None:
                opened += 1
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_paper_open failed for %s: %s", c["ticker"], repr(exc))
    return {"opened": opened, "as_of": today.isoformat()}


def _latest_iv_spot(repo, ticker: str, on: _date):
    """Latest vrp_daily IV AND corp-action-adjusted spot on/before `on` — no future
    leak (ISSUE-3). Returns (iv, spot, full_adj_series)."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT iv FROM {repo._schema}.vrp_daily WHERE ticker=%s AND market_date<=%s "
            "ORDER BY market_date DESC LIMIT 1",
            (ticker, on),
        )
        ivr = cur.fetchone()
    adj = apply_split_adjustment(
        repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
    )
    asof = [(d, v) for d, v in adj if d <= on]
    spot = asof[-1][1] if asof else None
    iv = float(ivr[0]) if ivr and ivr[0] is not None else None
    return iv, spot, adj


def _condor_of(p) -> IronCondor:
    return IronCondor(
        short_put=float(p["short_put"]), long_put=float(p["long_put"]),
        short_call=float(p["short_call"]), long_call=float(p["long_call"]),
        credit=float(p["entry_credit"]),
        put_width=float(p["short_put"]) - float(p["long_put"]),
        call_width=float(p["long_call"]) - float(p["short_call"]),
        max_loss=float(p["max_loss"]),
        leg_premiums=(0.0, 0.0, 0.0, 0.0),  # marks need no entry premia
    )


def vrp_paper_mark(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    """Mark each open position. CLOSE only when today >= expiry_on AND the realized
    price series has a trading close on/after expiry_on (settle at that exact row —
    no adj[-1] fallback, ISSUE-1/3); else crude intrinsic-at-spot unrealized mark.
    Both realized and unrealized P&L are NET of the modeled entry_cost (ISSUE-4)."""
    today = as_of or _date.today()
    marked = closed = 0
    for p in repo.fetch_open_vrp_paper_positions():
        try:
            _iv, spot, adj = _latest_iv_spot(repo, p["ticker"], today)  # _iv: v2 BS mark
            condor = _condor_of(p)
            entry_cost = float(p["entry_cost"] or 0.0)
            settle = next(((d, v) for d, v in adj if d >= p["expiry_on"]), None)
            if today >= p["expiry_on"] and settle is not None:
                S_T = settle[1]
                gross = condor_expiry_pnl(condor, S_T) * _MULT * p["contracts"]
                repo.close_vrp_paper_position(
                    p["position_id"], closed_on=settle[0], exit_value=S_T,
                    realized_pnl=gross - entry_cost,
                )
                closed += 1
            elif spot is not None:
                gross = condor_expiry_pnl(condor, spot) * _MULT * p["contracts"]
                repo.update_vrp_paper_mark(
                    p["position_id"], last_mark_on=today, mark_value=spot,
                    unrealized_pnl=gross - entry_cost, mark_source="model",
                )
                marked += 1
            repo.conn.commit()
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_paper_mark failed for %s: %s", p["ticker"], repr(exc))
    return {"marked": marked, "closed": closed, "as_of": today.isoformat()}
```

> Implementer note: the v1 unrealized mark uses intrinsic-at-spot (no time value) — documented as crude; a BS remaining-value mark (using `_iv`) is a fast follow.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/integration/worker/test_vrp_paper_ledger.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/vrp_trading_jobs.py tests/integration/worker/test_vrp_paper_ledger.py
git commit -m "feat(vrp): paper ledger worker jobs — open/mark/close + backtest/candidate refresh"
```

---

## Task 8: Scheduler wiring

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/unit/worker/test_vrp_scheduler_registration.py` (mirrors the existing `test_scheduler_registration.py` — registration is pure, runs before `start()`, so it's a unit test)

**Interfaces:**
- Consumes: `vrp_trading_jobs.*`. Produces: 4 scheduled jobs gated to the SAME primary-worker condition as `vrp_research_refresh` (massive role, index 0), mirroring its wrapper + `add_job` pattern.

Schedule (ET; all `0-4` weekdays; tunable):
| Job | Cron | Rationale |
|---|---|---|
| `vrp_candidates_refresh` | `25 19 * * 0-4` | after `vrp_research_refresh` (19:10) so the SELLABLE gate is fresh |
| `vrp_paper_open` | `30 19 * * 0-4` | open today's candidates |
| `vrp_paper_mark` | `40 19 * * 0-4` | mark/close after open; EOD prices settled (ohlc_pull 17:30) |
| `vrp_backtest_refresh` | `0 20 * * 6` | weekly (Sat 20:00) — heavier full-universe replay |

- [ ] **Step 1: Write the failing test** (mirror `tests/unit/worker/test_scheduler_registration.py` — boot the real `scheduler.main()` with a fake `BlockingScheduler` that records ids and aborts at `start()`)

```python
# tests/unit/worker/test_vrp_scheduler_registration.py
from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


def _registered_job_ids(monkeypatch, **env) -> set[str]:
    ids: list[str] = []

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_job(self, *_a, **kwargs) -> None:
            ids.append(kwargs.get("id"))

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(_StopStart):
        scheduler.main()
    return {i for i in ids if i is not None}


def test_vrp_trading_jobs_registered_on_primary_massive(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert {"vrp_candidates_refresh", "vrp_paper_open", "vrp_paper_mark",
            "vrp_backtest_refresh"} <= ids
```

> The existing registration test does not set `UW_SCAN_API_KEY` and passes in CI, so the test environment supplies it; this test inherits that. The 4 jobs must sit under the SAME primary-worker guard as `vrp_research_refresh`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/worker/test_vrp_scheduler_registration.py -v`
Expected: FAIL (jobs not registered)

- [ ] **Step 3: Wire the jobs**

Add the import near the other job imports:
```python
from uw_scan.worker.jobs.vrp_trading_jobs import (
    vrp_backtest_refresh,
    vrp_candidates_refresh,
    vrp_paper_mark,
    vrp_paper_open,
)
```
Add wrappers next to `_vrp_research_refresh` (massive-0 / primary only, matching its guard):
```python
    def _vrp_candidates_refresh() -> None:
        with _repo(settings) as repo:
            vrp_candidates_refresh(repo=repo, settings=settings)

    def _vrp_paper_open() -> None:
        with _repo(settings) as repo:
            vrp_paper_open(repo=repo, settings=settings)

    def _vrp_paper_mark() -> None:
        with _repo(settings) as repo:
            vrp_paper_mark(repo=repo, settings=settings)

    def _vrp_backtest_refresh() -> None:
        with _repo(settings) as repo:
            vrp_backtest_refresh(repo=repo, settings=settings)
```
Register with `add_job` (same `CronTrigger.from_crontab(..., timezone=settings.rth_tz)` + massive-0 gate as `vrp_research_refresh`):
```python
            sched.add_job(_vrp_candidates_refresh,
                CronTrigger.from_crontab("25 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_candidates_refresh")
            sched.add_job(_vrp_paper_open,
                CronTrigger.from_crontab("30 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_open")
            sched.add_job(_vrp_paper_mark,
                CronTrigger.from_crontab("40 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_mark")
            sched.add_job(_vrp_backtest_refresh,
                CronTrigger.from_crontab("0 20 * * 6", timezone=settings.rth_tz),
                id="vrp_backtest_refresh")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/worker/test_vrp_scheduler_registration.py -v`
Expected: PASS

- [ ] **Step 5: Update worker CLAUDE.md schedule table + commit**

Add the 4 rows to the schedule table in `src/uw_scan/worker/CLAUDE.md`.
```bash
git add src/uw_scan/worker/scheduler.py src/uw_scan/worker/CLAUDE.md tests/unit/worker/test_vrp_scheduler_registration.py
git commit -m "feat(vrp): schedule candidate/paper/backtest jobs (massive-0, weekdays ET)"
```

---

## Task 9: API — models + `/vrp` router

**Files:**
- Create: `src/uw_scan/models/vrp.py`, `src/uw_scan/api/routers/vrp.py`
- Modify: `src/uw_scan/models/__init__.py`, `src/uw_scan/api/server.py`
- Test: `tests/integration/api/test_vrp_endpoints.py`

**Interfaces:**
- Produces models: `VrpCandidateRow`, `VrpCandidatesResponse`, `VrpBacktestRow`, `VrpBacktestResponse`, `VrpPaperPositionRow`, `VrpPaperResponse` (all re-exported from `models/__init__.py`).
- Endpoints (prefix `/vrp`, under `/api`): `GET /vrp/candidates`, `GET /vrp/backtest?hold_days=`, `GET /vrp/paper?status=`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/api/test_vrp_endpoints.py
from datetime import date

from fastapi.testclient import TestClient

from uw_scan.api.server import create_app
from uw_scan.api.deps import get_repo


def _client(repo):
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def test_candidates_endpoint(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_candidate(
        ticker="NVDA", as_of=date(2026, 6, 22), structure="iron_condor", spot=120.0,
        iv=0.45, vrp_z=1.8, hold_days=20, short_put=110.0, long_put=104.0,
        short_call=130.0, long_call=136.0, entry_credit=1.8, max_loss=4.2,
        put_width=6.0, call_width=6.0, bucket_sector="Semis",
        bucket_verdict="HARVEST_SELLABLE", earnings_clear=True, contracts=1,
    )
    repo.conn.commit()
    r = _client(repo).get("/api/vrp/candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["ticker"] == "NVDA"
    assert body["disclaimer"]  # flat-vol limitation surfaced
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/api/test_vrp_endpoints.py -v`
Expected: FAIL (404 / no router)

- [ ] **Step 3: Implement models + router**

```python
# src/uw_scan/models/vrp.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models._base import _UwBase, _preserve_public_module

_FLAT_VOL_DISCLAIMER = (
    "Flat-vol modeled credit (skew ignored): direction is faithful, absolute "
    "credit is approximate. Paper/backtest only — not executed."
)


class VrpCandidateRow(_UwBase):
    ticker: str
    as_of: date
    structure: str
    spot: Decimal | None = None
    iv: Decimal | None = None
    vrp_z: Decimal | None = None
    hold_days: int
    short_put: Decimal | None = None
    long_put: Decimal | None = None
    short_call: Decimal | None = None
    long_call: Decimal | None = None
    entry_credit: Decimal | None = None
    max_loss: Decimal | None = None
    bucket_sector: str | None = None
    bucket_verdict: str | None = None
    earnings_clear: bool
    contracts: int


class VrpCandidatesResponse(_UwBase):
    candidates: list[VrpCandidateRow]
    disclaimer: str = _FLAT_VOL_DISCLAIMER


class VrpBacktestRow(_UwBase):
    unit_type: str
    unit_key: str
    hold_days: int
    scope: str
    n_trades: int
    n_wins: int = 0
    win_rate: Decimal | None = None
    mean_net: Decimal | None = None
    median_net: Decimal | None = None
    total_net: Decimal | None = None
    mean_return_on_risk: Decimal | None = None
    breach_rate: Decimal | None = None
    mean_credit: Decimal | None = None


class VrpBacktestResponse(_UwBase):
    results: list[VrpBacktestRow]
    disclaimer: str = _FLAT_VOL_DISCLAIMER


class VrpPaperPositionRow(_UwBase):
    position_id: int
    ticker: str
    opened_on: date
    expiry_on: date
    hold_days: int
    contracts: int
    short_put: Decimal | None = None
    long_put: Decimal | None = None
    short_call: Decimal | None = None
    long_call: Decimal | None = None
    status: str
    entry_credit: Decimal | None = None
    max_loss: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    mark_source: str


class VrpPaperResponse(_UwBase):
    positions: list[VrpPaperPositionRow]
    total_realized_pnl: Decimal | None = None
    disclaimer: str = _FLAT_VOL_DISCLAIMER


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
# (repo convention — CLAUDE.md "preserve public Pydantic model __module__ metadata").
_preserve_public_module(
    VrpCandidateRow, VrpCandidatesResponse, VrpBacktestRow,
    VrpBacktestResponse, VrpPaperPositionRow, VrpPaperResponse,
)
```

```python
# src/uw_scan/api/routers/vrp.py
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.models.vrp import (
    VrpBacktestResponse,
    VrpBacktestRow,
    VrpCandidateRow,
    VrpCandidatesResponse,
    VrpPaperPositionRow,
    VrpPaperResponse,
)
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/vrp")


@router.get("/candidates", response_model=VrpCandidatesResponse)
def get_vrp_candidates(repo: Repository = Depends(get_repo)) -> VrpCandidatesResponse:
    rows = repo.fetch_vrp_candidates()
    return VrpCandidatesResponse(candidates=[VrpCandidateRow(**r) for r in rows])


@router.get("/backtest", response_model=VrpBacktestResponse)
def get_vrp_backtest(
    hold_days: int | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> VrpBacktestResponse:
    rows = repo.fetch_vrp_backtest_results(hold_days=hold_days)
    return VrpBacktestResponse(results=[VrpBacktestRow(**r) for r in rows])


@router.get("/paper", response_model=VrpPaperResponse)
def get_vrp_paper(
    status: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> VrpPaperResponse:
    rows = repo.fetch_vrp_paper_positions(status=status)
    total = sum((Decimal(str(r["realized_pnl"])) for r in rows if r.get("realized_pnl") is not None), Decimal(0))
    return VrpPaperResponse(
        positions=[VrpPaperPositionRow(**r) for r in rows],
        total_realized_pnl=total,
    )
```

Re-export the 6 models from `src/uw_scan/models/__init__.py` (alphabetical block + `__all__`), and add to `server.py`:
```python
app.include_router(vrp.router, prefix="/api", tags=["vrp"])
```
(import `vrp` in the `from uw_scan.api.routers import (...)` block).

- [ ] **Step 4: Run to verify pass + model exports green**

Run: `uv run pytest tests/integration/api/test_vrp_endpoints.py tests/unit/test_models_exports.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate types + snapshot**

Run: `cd web && npm run gen:types` then `cd .. && uv run pytest tests/ -k openapi_snapshot -v` (or the repo's snapshot test name).
Verify `web/lib/types.ts` gained the 6 VRP types with no unrelated reordering (`[[reference_generated_files_alphabetically_frozen]]`).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models/vrp.py src/uw_scan/models/__init__.py src/uw_scan/api/routers/vrp.py src/uw_scan/api/server.py web/lib/types.ts tests/integration/api/test_vrp_endpoints.py
git commit -m "feat(vrp): /vrp API — candidates, backtest, paper ledger (+ flat-vol disclaimer)"
```

---

## Task 10: Web — VRP Trading page

**Files:**
- Create: `web/app/vrp/page.tsx`, `web/components/vrp/CandidatesTable.tsx`, `web/components/vrp/BacktestSummary.tsx`, `web/components/vrp/PaperLedger.tsx`
- Test: `web/tests/vrp/CandidatesTable.test.tsx`

**Interfaces:**
- Consumes: `GET /api/vrp/{candidates,backtest,paper}` via the existing fetch helper + generated `types.ts`.

- [ ] **Step 1: Write the failing component test**

```tsx
// web/tests/vrp/CandidatesTable.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CandidatesTable } from "@/components/vrp/CandidatesTable";

describe("CandidatesTable", () => {
  it("renders a candidate row with the four strikes", () => {
    render(
      <CandidatesTable
        candidates={[
          {
            ticker: "NVDA", as_of: "2026-06-22", structure: "iron_condor",
            spot: 120, iv: 0.45, vrp_z: 1.8, hold_days: 20,
            short_put: 110, long_put: 104, short_call: 130, long_call: 136,
            entry_credit: 1.8, max_loss: 4.2, bucket_sector: "Semis",
            bucket_verdict: "HARVEST_SELLABLE", earnings_clear: true, contracts: 1,
          },
        ]}
      />,
    );
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText(/110/)).toBeInTheDocument(); // short put
    expect(screen.getByText(/HARVEST_SELLABLE/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npm run test -- vrp/CandidatesTable`
Expected: FAIL (component not found)

- [ ] **Step 3: Implement the components + page**

Build `CandidatesTable` (props `{ candidates: VrpCandidateRow[] }`) as a hand-rolled table matching the Argon dark theme (mirror `components/regime/*` styling). `BacktestSummary` renders the per-bucket/per-ticker `full` vs `holdout` rows side-by-side with the holdout labeled "honest headline". `PaperLedger` lists open + closed positions with running/realized P&L. `web/app/vrp/page.tsx` is a server component that fetches the three endpoints and renders the three islands, with a prominent **flat-vol / paper-only disclaimer banner** (the `disclaimer` field).

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npm run test -- vrp/CandidatesTable`
Expected: PASS

- [ ] **Step 5: Typecheck + build + commit**

Run: `cd web && npm run typecheck && npm run build`
```bash
git add web/app/vrp web/components/vrp web/tests/vrp
git commit -m "feat(vrp): VRP Trading page — candidates, backtest (full vs holdout), paper ledger"
```

---

## Task 11 (deferred milestone): Forward NBBO recorder

> Implement only after Tasks 1–10 are green and reviewed. It is the only job that calls UW; it accrues a dataset with no consumer yet, so it is intentionally last and can ship in a follow-up PR.

**Files:**
- Modify: `src/uw_scan/worker/jobs/vrp_trading_jobs.py` (add `vrp_nbbo_record`), `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_vrp_nbbo_record.py` (UW client stubbed with a recorded fixture)

**Interface:** `vrp_nbbo_record(*, repo, client, settings)` — for each open position's 4 legs, fetch the UW option chain NBBO for `(ticker, expiry, strike, right)` and `upsert_vrp_leg_nbbo`. Runs in the UW flow window (`30 16 * * 0-4`), uw-role. No backtest consumes it yet.

---

## Known limitations & honesty (carry verbatim into UI + result tables)

1. **Flat-vol pricing ignores skew.** Absolute entry credit and put/call wing asymmetry are approximate; direction (sell rich IV, pay realized RV, truncated) is faithful. Skew overlay = v2.
2. **scope='full' has mild lookahead** (gates on the final bucket verdict over the backtested window). **scope='holdout' (latest 40%) is the headline.** A point-in-time bucket recompute is a future hardening.
3. **Hold-to-expiry only** in v1 (model-free exit). Early management (profit-target/stop) needs exit repricing → v2 toggle.
4. **Unrealized paper mark is intrinsic-at-spot** (no time value) in v1; BS remaining-value mark is a fast follow.
5. **Model fills, not real fills.** True-fill validation depends on the forward NBBO dataset (Task 11) accruing first.
6. **v1 trades single_name only.** The validated edge is "single-name vol IS sellable by sector." index_macro / sector_etf / credit have no studied sector bucket, so the backtest and emitter skip them (they would otherwise be emitted ungated). Asset-class-gated index/ETF condors are a v2 (would gate on `vrp_harvest_verdicts`).
7. **Paper hold is a calendar approximation of the backtest's trading-day hold.** The backtest settles at the EXACT `hold_days`-th forward trading row (positional); the paper ledger can't know the future trading calendar at open, so `expiry_on ≈ hold_days × 7/5` calendar days and it settles at the first realized close on/after that date — usually within a day of the precise 20th trading day. The two P&L streams are therefore close but not identical.

---

## Self-Review (run before handing off to /review-cycle)

- **Spec coverage:** Iron condor ✅ (Task 2); model-reprice now + NBBO forward ✅ (Tasks 5 + 11); bucket-gated per-ticker ✅ (Tasks 5/6 gate on `vrp_harvest_by_sector`, rows per ticker); candidate emitter + paper ledger ✅ (Tasks 6/7). UI ✅ (Task 10).
- **Type consistency:** `IronCondor` fields, `CostModel.total(leg_premiums, contracts)`, `single_trade_pnl` return tuple, repo method names, and model field names are used identically across tasks.
- **Standing rules:** defined-risk only ✅; per-row commit+rollback in every job ✅; new mixin/router files (not appended) ✅; idempotent migration ✅; persist-to-DB ✅; no Yahoo ✅.
