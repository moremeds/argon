# GOAS Put-Write Delta Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtest a GOAS-style systematic cash-secured SPY put-writing program over ~2006→present and find the short-put **delta** (and expiry tenor) that maximizes risk-adjusted, net-of-fee income, validated against GOAS's published 0.7%/96.2% quote and 3–6% net target.

**Architecture:** Three pure-Python report modules + one research runner. `goas_putwrite_pricing.py` adds a parametric volatility-skew layer over the existing flat-vol Black-Scholes primitives (skew affects only entry strike/credit; expiry settlement is model-free intrinsic). `goas_putwrite_account.py` simulates a laddered, constant-size, cash-secured put book on a daily NAV curve with a management-fee drag. `goas_putwrite_sweep.py` runs the delta×tenor×pricing×fee grid with regime slices and sweet-spot ranking. `scripts/research/goas_putwrite_run.py` wires the DB, runs the sweep, and writes CSV traces + a findings note.

**Tech Stack:** Python 3.13 via `uv` only; `statistics.NormalDist` (no numpy/scipy); psycopg 3 (runner only); pytest. Reuses `uw_scan.reports.vrp_structure` (`bs_price`, `bs_delta`, `strike_for_delta`, `CashSecuredPut`, `build_cash_secured_put`, `CostModel`) and `uw_scan.reports.vrp_macro_drawdown.load_index_vol`.

## Global Constraints

- `uv` only — `uv run pytest`, `uv run ruff check`; never bare `python`/`pip`/`pytest`.
- Defined-risk only — cash-secured puts; **no naked shorts**. Max loss per put = (strike − credit)·100.
- No fabricated data — test fixtures use **real, frozen** values (2026-05-05 SPY/VIX), fetched once and hardcoded with the as-of date. **No runtime network/DB in unit tests.**
- No synthetic prices passed off as real — synthetic *paths* in account tests are labeled as constructed test inputs, never as observed market data.
- Skew shape is **modeled, not observed** — every artifact states this; flat-vol is the conservative floor, skew is the GOAS-faithful estimate, truth is bracketed between them.
- Fees are **not invented** — GOAS published only gross (≈7.7% ann.) and net (3–6%); report gross / net-of-cost / net-of-fee side by side over a transparent fee grid `(0.0, 0.005, 0.010, 0.015)`.
- Exception handlers in `src/` log `repr(exc)` / `.exception(...)` or re-raise (CI Guardrail 2).
- Module size budget < 500 lines/file.
- Persist every research trace — CSVs + findings note committed under `docs/research/goas-putwrite/`; record the exact reproduce command.
- `Decimal` is used for *contract/API* prices elsewhere; this backtest is float-based math (matching `vrp_structure`/`vrp_macro_harvest`, which are float) — keep float for consistency with the reused primitives.

---

### Task 1: Skew pricing layer (`goas_putwrite_pricing.py`)

**Files:**
- Create: `src/uw_scan/reports/goas_putwrite_pricing.py`
- Test: `tests/unit/reports/test_goas_putwrite_pricing.py`

**Interfaces:**
- Consumes (from `uw_scan.reports.vrp_structure`): `bs_price(S,K,T,r,sigma,*,is_call) -> float`, `bs_delta(S,K,T,r,sigma,*,is_call) -> float`, `build_cash_secured_put(S,sigma,T,r,*,short_delta) -> CashSecuredPut`, `CashSecuredPut(short_put, credit, max_loss, leg_premiums)`.
- Produces:
  - `PutSkew(slope: float)` with method `iv(self, atm_sigma: float, S: float, K: float) -> float`.
  - `build_csp_skew(S: float, atm_sigma: float, T: float, r: float, *, short_delta: float, skew: PutSkew | None) -> CashSecuredPut`.
  - `calibrate_skew(S: float, atm_sigma: float, T: float, r: float, *, target_strike_frac: float, target_premium_frac: float) -> PutSkew`.
  - Module constants `GOAS_AS_OF = date(2026, 5, 5)`, `GOAS_STRIKE_FRAC = 0.962`, `GOAS_PREMIUM_FRAC = 0.007`, `GOAS_DTE_DAYS = 21` (1 month ≈ 21 trading days).

- [ ] **Step 1: Fetch the real frozen fixture values (one-time, authoring)**

Look up the real 2026-05-05 closes and record them for the test (no fabrication). Run against a DB that has the data (the mini, read-only) — set the env for a one-off browse per CLAUDE.md, then:

```bash
UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python -c "
import os, psycopg
conn=psycopg.connect(host=os.environ['UW_SCAN_DB_HOST'],dbname=os.environ['UW_SCAN_DB_NAME'],user='argon_app')
cur=conn.cursor()
cur.execute(\"SELECT symbol,close FROM uw_scan.vol_index_daily WHERE symbol IN ('VIX','SPX') AND trade_date='2026-05-05'\")
print('vol_index_daily:', cur.fetchall())
"
```

Also get the SPY close for 2026-05-05 from the equity lake (the runner/loader path) or from `vol_index_daily` SPX as the index proxy. Record both as comments in the test file with the as-of date. Expected: a VIX close (e.g., low-to-mid teens) and an SPX/SPY level. **Do not invent** — if the query returns nothing, fall back to the nearest prior trading day and note it.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/reports/test_goas_putwrite_pricing.py
from datetime import date

import pytest

from uw_scan.reports.goas_putwrite_pricing import (
    GOAS_AS_OF,
    GOAS_DTE_DAYS,
    GOAS_PREMIUM_FRAC,
    GOAS_STRIKE_FRAC,
    PutSkew,
    build_csp_skew,
    calibrate_skew,
)
from uw_scan.reports.vrp_structure import bs_delta, bs_price, build_cash_secured_put

# Real frozen fixture — SPY/VIX as of 2026-05-05 (fetched once from
# uw_scan.vol_index_daily; see Step 1). Replace the two literals below with the
# real values recorded in Step 1.
SPY_2026_05_05 = 0.0  # TODO-AUTHOR: substitute the real SPY close from Task 1 Step 1
VIX_2026_05_05 = 0.0  # TODO-AUTHOR: substitute the real VIX close from Task 1 Step 1
R = 0.04
T_1M = GOAS_DTE_DAYS / 252.0  # 1-month tenor, consistent with the calibration


def test_goas_as_of_constant():
    assert GOAS_AS_OF == date(2026, 5, 5)


def test_flat_skew_is_noop():
    # slope=0 → iv == atm at every strike
    sk = PutSkew(slope=0.0)
    assert sk.iv(0.18, 100.0, 95.0) == pytest.approx(0.18)


def test_skew_is_monotone_downside():
    # lower strike (deeper OTM put) → higher IV for a positive slope
    sk = PutSkew(slope=1.5)
    iv_atm = sk.iv(0.18, 100.0, 100.0)
    iv_otm = sk.iv(0.18, 100.0, 90.0)
    assert iv_otm > iv_atm == pytest.approx(0.18)


def test_build_csp_skew_none_matches_flat():
    S, sigma = 100.0, 0.18
    a = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=None)
    b = build_cash_secured_put(S, sigma, T_1M, R, short_delta=0.15)
    assert a.short_put == pytest.approx(b.short_put)
    assert a.credit == pytest.approx(b.credit)


def test_build_csp_skew_is_delta_consistent():
    # the chosen strike must actually be ~short_delta under its OWN skew-IV
    S, sigma = 100.0, 0.18
    sk = PutSkew(slope=1.2)
    csp = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=sk)
    iv_k = sk.iv(sigma, S, csp.short_put)
    recovered = -bs_delta(S, csp.short_put, T_1M, R, iv_k, is_call=False)
    assert recovered == pytest.approx(0.15, abs=1e-3)


def test_skew_credit_richer_than_flat():
    # at the same target delta, skew enriches the credit vs flat-vol
    S, sigma = 100.0, 0.18
    flat = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=None)
    skew = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=PutSkew(slope=1.2))
    assert skew.credit > flat.credit


def test_calibrate_reproduces_goas_quote():
    # the calibrated skew reproduces GOAS's published 96.2% strike / 0.7% premium
    S, sigma = SPY_2026_05_05, VIX_2026_05_05 / 100.0
    sk = calibrate_skew(
        S, sigma, T_1M, R,
        target_strike_frac=GOAS_STRIKE_FRAC, target_premium_frac=GOAS_PREMIUM_FRAC,
    )
    k_star = GOAS_STRIKE_FRAC * S
    prem = bs_price(S, k_star, T_1M, R, sk.iv(sigma, S, k_star), is_call=False)
    assert prem == pytest.approx(GOAS_PREMIUM_FRAC * S, rel=0.02)


def test_build_csp_skew_rejects_degenerate():
    with pytest.raises(ValueError):
        build_csp_skew(100.0, 0.18, T_1M, R, short_delta=0.6, skew=PutSkew(slope=1.0))
    with pytest.raises(ValueError):
        build_csp_skew(-1.0, 0.18, T_1M, R, short_delta=0.15, skew=None)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_pricing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.reports.goas_putwrite_pricing'`.

- [ ] **Step 4: Write minimal implementation**

```python
# src/uw_scan/reports/goas_putwrite_pricing.py
"""Parametric downside-skew layer over the flat-vol BS primitives.

A put held to expiry settles at intrinsic (vol-independent), so skew changes only
(a) the strike chosen for a target delta and (b) the entry credit — settlement is
reused unchanged. The historical skew SHAPE here is MODELED (calibrated to one
recent GOAS quote), not observed: no multi-year IV surface exists on our data.
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

from uw_scan.reports.vrp_structure import (
    CashSecuredPut,
    bs_delta,
    bs_price,
    build_cash_secured_put,
)

log = logging.getLogger(__name__)

# GOAS published quote (illustrative option price table, as of 2026-05-05):
# SPDR S&P 500 ETF, 1-month ~15%-exercise-probability put → strike 96.2% of spot,
# premium 0.7% of spot. Used to calibrate the skew slope.
GOAS_AS_OF = date(2026, 5, 5)
GOAS_STRIKE_FRAC = 0.962
GOAS_PREMIUM_FRAC = 0.007
GOAS_DTE_DAYS = 21  # GOAS "1 month" ≈ 21 trading days; dte_days are trading-day offsets


@dataclass(frozen=True)
class PutSkew:
    """Downside vol skew: iv(K) = atm·(1 − slope·ln(K/S)). For a put strike below
    spot, ln(K/S) < 0, so a positive slope RAISES iv as strikes fall (the observed
    index shape). slope=0 ⇒ flat-vol."""

    slope: float

    def iv(self, atm_sigma: float, S: float, K: float) -> float:
        return atm_sigma * (1.0 - self.slope * math.log(K / S))


def build_csp_skew(
    S: float,
    atm_sigma: float,
    T: float,
    r: float,
    *,
    short_delta: float,
    skew: PutSkew | None,
) -> CashSecuredPut:
    """Cash-secured put at the delta-consistent strike under `skew`. When skew is
    None, delegates to the flat-vol builder. The put delta magnitude N(−d1)
    decreases monotonically as K falls, so a bisection on K ∈ (0, S) converges."""
    if skew is None:
        return build_cash_secured_put(S, atm_sigma, T, r, short_delta=short_delta)
    if S <= 0 or atm_sigma <= 0 or T <= 0:
        raise ValueError(f"build_csp_skew needs S,atm_sigma,T > 0 (got {S},{atm_sigma},{T})")
    if not (0.0 < short_delta < 0.5):
        raise ValueError("require 0 < short_delta < 0.5")
    lo, hi = 1e-9 * S, S
    # admissible-delta guard (ISSUE-4): max attainable |put delta| is near K=S; a target
    # at/above it cannot be bracketed in (0, S) and bisection would converge to K≈S (a
    # wrong strike). Raise so the caller skips this entry rather than mis-pricing it.
    k_atm = S * (1.0 - 1e-9)
    dmag_max = -bs_delta(S, k_atm, T, r, skew.iv(atm_sigma, S, k_atm), is_call=False)
    if short_delta >= dmag_max:
        raise ValueError(
            f"short_delta {short_delta} >= max attainable |put delta| {dmag_max:.3f} "
            "at this tenor/vol — not bracketable in (0, S)"
        )
    k = 0.5 * (lo + hi)
    for _ in range(200):
        k = 0.5 * (lo + hi)
        iv_k = skew.iv(atm_sigma, S, k)
        if iv_k <= 0:
            lo = k  # iv blew up at very low strike; push up
            continue
        dmag = -bs_delta(S, k, T, r, iv_k, is_call=False)  # |put delta| ∈ (0, 0.5)
        if dmag > short_delta:  # strike too close to money → lower the ceiling
            hi = k
        else:
            lo = k
        if hi - lo < 1e-9 * S:
            break
    iv_k = skew.iv(atm_sigma, S, k)
    recovered = -bs_delta(S, k, T, r, iv_k, is_call=False)  # |put delta| at the solved strike
    if abs(recovered - short_delta) > 1e-3:
        # |put delta| can be non-monotone in K when IV depends on K (steep skew);
        # the bisection then lands off-target. Surface it loudly rather than
        # silently mis-pricing the whole sweep.
        log.warning(
            "build_csp_skew non-convergent: target Δ=%.3f recovered Δ=%.3f K=%.2f slope=%.3f",
            short_delta, recovered, k, skew.slope,
        )
    credit = bs_price(S, k, T, r, iv_k, is_call=False)
    return CashSecuredPut(k, credit, k - credit, (credit,))


def calibrate_skew(
    S: float,
    atm_sigma: float,
    T: float,
    r: float,
    *,
    target_strike_frac: float,
    target_premium_frac: float,
) -> PutSkew:
    """Solve the skew `slope` so a put struck at target_strike_frac·S prices to
    target_premium_frac·S at the given ATM σ. One equation, one unknown — premium
    rises monotonically with slope (higher downside IV). If flat-vol (slope=0)
    already exceeds the target premium, returns slope=0 and logs it."""
    if S <= 0 or atm_sigma <= 0 or T <= 0:
        raise ValueError("calibrate_skew needs S,atm_sigma,T > 0")
    k_star = target_strike_frac * S
    target_prem = target_premium_frac * S
    flat_prem = bs_price(S, k_star, T, r, atm_sigma, is_call=False)
    if flat_prem >= target_prem:
        log.info(
            "calibrate_skew: flat-vol premium %.4f already ≥ target %.4f → slope=0",
            flat_prem, target_prem,
        )
        return PutSkew(slope=0.0)
    lo, hi = 0.0, 10.0
    slope = 0.5 * (lo + hi)
    for _ in range(200):
        slope = 0.5 * (lo + hi)
        iv_k = atm_sigma * (1.0 - slope * math.log(k_star / S))
        prem = bs_price(S, k_star, T, r, iv_k, is_call=False)
        if prem > target_prem:
            hi = slope
        else:
            lo = slope
        if hi - lo < 1e-9:
            break
    final_iv = atm_sigma * (1.0 - slope * math.log(k_star / S))
    final_prem = bs_price(S, k_star, T, r, final_iv, is_call=False)
    if abs(final_prem - target_prem) > 0.05 * target_prem:
        # target premium unreachable within slope<=10 → calibration did not converge.
        log.warning(
            "calibrate_skew non-convergent: got premium %.4f want %.4f at slope=%.3f",
            final_prem, target_prem, slope,
        )
    return PutSkew(slope=slope)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_pricing.py -v`
Expected: PASS (all 8 tests). If `test_calibrate_reproduces_goas_quote` fails because flat-vol at the real 2026-05-05 VIX already exceeds 0.7% (slope clamps to 0), do NOT relax the assert to `>=` — that hides a broken anchor. Treat it as an explicit finding: the GOAS quote is inconsistent with our flat-vol at that VIX. Keep the equality-style assert (premium ≈ target within tol); record the discrepancy in the findings note and reconcile (fixture/VIX/quote), don't paper over it.

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/uw_scan/reports/goas_putwrite_pricing.py && uv run python scripts/_lint_except.py src`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/reports/goas_putwrite_pricing.py tests/unit/reports/test_goas_putwrite_pricing.py
git commit -m "feat(goas): add parametric put-skew pricing layer + GOAS-quote calibration"
```

---

### Task 2: Laddered put-write account simulator (`goas_putwrite_account.py`)

**Files:**
- Create: `src/uw_scan/reports/goas_putwrite_account.py`
- Test: `tests/unit/reports/test_goas_putwrite_account.py`

**Interfaces:**
- Consumes: `build_csp_skew`, `PutSkew` (Task 1); `CostModel` (`uw_scan.reports.vrp_structure`); `_Loaded` (`uw_scan.reports.vrp_macro_harvest._Loaded` — fields `adj: list[tuple[date,float]]`, `pidx: dict[date,int]`, `rows: list[dict]` with `iv`, `market_date`).
- Produces:
  - `GoasConfig(short_delta, dte_days, cadence_days=5, capital=1_000_000.0, skew=None, r=0.04, cost=None, multiplier=100)` (frozen; no mgmt-fee field — fee is a downstream drag).
  - `PutWriteTrade(entry_date, expiry_date, strike, credit, iv_entry, contracts, intrinsic, net_pnl, return_on_risk, breached)`.
  - `PutWriteResult(equity_curve_gross, equity_curve_costed, trades, span)` — `equity_curve_gross` is pre-cost/pre-fee, `equity_curve_costed` is post-cost/pre-fee; both `list[tuple[date,float]]` daily NAV.
  - `simulate_putwrite(loaded, cfg: GoasConfig) -> PutWriteResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reports/test_goas_putwrite_account.py
from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_account import GoasConfig, simulate_putwrite
from uw_scan.reports.vrp_macro_harvest import _Loaded
from uw_scan.reports.vrp_structure import CostModel

ZERO_COST = CostModel(per_contract=0.0, slippage_frac=0.0, slippage_min=0.0, round_trip=True)


def _flat_loaded(n_days: int, spot: float, iv: float) -> _Loaded:
    """Constructed test input (NOT market data): n consecutive business-ish days at
    a constant spot and IV."""
    d0 = date(2010, 1, 4)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    adj = [(d, spot) for d in dates]
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def _selloff_loaded(n_days: int, spot0: float, iv: float, *, drop_to: float, drop_at: int) -> _Loaded:
    d0 = date(2010, 1, 4)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    spots = [spot0 if i < drop_at else drop_to for i in range(n_days)]
    adj = list(zip(dates, spots, strict=True))
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_flat_path_no_breach_nav_rises_by_net_credit():
    loaded = _flat_loaded(400, spot=100.0, iv=0.18)
    cfg = GoasConfig(short_delta=0.15, dte_days=30, cadence_days=5, capital=1_000_000.0,
                     cost=ZERO_COST)
    res = simulate_putwrite(loaded, cfg)
    assert res.trades, "expected trades on a 400-day flat path"
    # flat spot, all puts expire OTM → every trade keeps full credit, none breached
    assert all(not t.breached for t in res.trades)
    assert all(t.net_pnl > 0 for t in res.trades)
    # post-cost NAV ends above start (premium harvested); equals gross at zero cost
    assert res.equity_curve_costed[-1][1] > res.equity_curve_costed[0][1]
    assert res.equity_curve_costed[-1][1] == pytest.approx(res.equity_curve_gross[-1][1])


def test_selloff_loss_bounded_by_defined_risk():
    # spot crashes 100 → 50; a 0.15-delta put can lose at most (strike − credit)·100·contracts
    loaded = _selloff_loaded(120, spot0=100.0, iv=0.30, drop_to=50.0, drop_at=40)
    cfg = GoasConfig(short_delta=0.15, dte_days=30, cadence_days=5, capital=1_000_000.0,
                     cost=ZERO_COST)
    res = simulate_putwrite(loaded, cfg)
    for t in res.trades:
        floor = -(t.strike - t.credit) * cfg.multiplier * t.contracts
        assert t.net_pnl >= floor - 1e-6  # never worse than the assignment-to-zero floor


def test_deterministic():
    loaded = _flat_loaded(200, spot=100.0, iv=0.18)
    cfg = GoasConfig(short_delta=0.20, dte_days=30, cost=ZERO_COST)
    a = simulate_putwrite(loaded, cfg)
    b = simulate_putwrite(loaded, cfg)
    assert [t.net_pnl for t in a.trades] == [t.net_pnl for t in b.trades]
    assert a.equity_curve_costed == b.equity_curve_costed


def test_no_entry_day_premium_frontload():
    # fair-value marking ⇒ at entry the open put marks ≈ credit, so unrealized ≈ 0
    # and NAV does NOT jump by the full premium on day 0. cadence > n_days ⇒ a single
    # entry at i=0 to isolate the behavior.
    loaded = _flat_loaded(120, spot=100.0, iv=0.18)
    cfg = GoasConfig(short_delta=0.15, dte_days=30, cadence_days=200, capital=1_000_000.0,
                     cost=ZERO_COST)
    res = simulate_putwrite(loaded, cfg)
    assert len(res.trades) == 1
    t = res.trades[0]
    full_credit = t.credit * cfg.multiplier * t.contracts
    nav0 = res.equity_curve_gross[0][1]
    assert abs(nav0 - cfg.capital) < 0.1 * full_credit  # no entry-day front-load
    # the full credit is realized by expiry (flat path, OTM → keeps all credit)
    assert res.equity_curve_gross[-1][1] == pytest.approx(cfg.capital + full_credit, rel=1e-6)


def test_costs_reduce_net_pnl():
    # cost path must be exercised (all other tests use ZERO_COST). Same path/strikes;
    # transaction costs strictly lower every trade's net P&L and the ending NAV.
    loaded = _flat_loaded(200, spot=100.0, iv=0.18)
    costed = CostModel(per_contract=0.65, slippage_frac=0.01, slippage_min=0.05, round_trip=True)
    res_cost = simulate_putwrite(loaded, GoasConfig(short_delta=0.15, dte_days=21, cost=costed))
    res_free = simulate_putwrite(loaded, GoasConfig(short_delta=0.15, dte_days=21, cost=ZERO_COST))
    assert res_cost.trades and len(res_cost.trades) == len(res_free.trades)
    for tc, tf in zip(res_cost.trades, res_free.trades, strict=True):
        assert tc.net_pnl < tf.net_pnl
    assert res_cost.equity_curve_costed[-1][1] < res_free.equity_curve_costed[-1][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_account.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.reports.goas_putwrite_account'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/uw_scan/reports/goas_putwrite_account.py
"""Laddered, constant-size, cash-secured SPY put-writing account on a daily NAV
curve. Always-on (no vol gate). Held to expiry; expiry SETTLEMENT and realized
P&L are intrinsic (model-free). Open positions are marked daily at FAIR VALUE
(BS at the current ATM vol + same skew) so theta is earned gradually and
selloffs draw the curve down properly — NO entry-day premium front-loading
(at entry, fair value ≈ credit → unrealized ≈ 0). Management fee accrues daily
on NAV.

GOAS's 4–5 week ramp-in is realized by NATURAL laddered accumulation: the book
fills to ~dte_days/cadence_days concurrent puts over the first ~dte_days. No
separate ramp knob.
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from statistics import fmean, pstdev

from uw_scan.reports.goas_putwrite_pricing import PutSkew, build_csp_skew
from uw_scan.reports.vrp_macro_harvest import _Loaded
from uw_scan.reports.vrp_structure import CostModel, bs_price

log = logging.getLogger(__name__)

_DEFAULT_COST = CostModel(per_contract=0.65, slippage_frac=0.01, slippage_min=0.05, round_trip=True)


@dataclass(frozen=True)
class GoasConfig:
    short_delta: float
    dte_days: int
    cadence_days: int = 5
    capital: float = 1_000_000.0
    skew: PutSkew | None = None
    r: float = 0.04
    cost: CostModel | None = None
    multiplier: int = 100
    # NOTE: no mgmt-fee field — the fee is a deterministic downstream NAV drag
    # (apply_mgmt_fee on the post-cost curve), swept over FEE_GRID, so the sim runs once.

    @property
    def cost_model(self) -> CostModel:
        return self.cost if self.cost is not None else _DEFAULT_COST


@dataclass
class PutWriteTrade:
    entry_date: _date
    expiry_date: _date
    strike: float
    credit: float
    iv_entry: float
    contracts: float
    intrinsic: float
    net_pnl: float
    return_on_risk: float
    breached: bool


@dataclass
class PutWriteResult:
    equity_curve_gross: list[tuple[_date, float]]   # pre-cost, pre-fee (TRUE gross)
    equity_curve_costed: list[tuple[_date, float]]  # post-cost, pre-fee
    trades: list[PutWriteTrade]
    span: tuple[str, str]


def simulate_putwrite(loaded: _Loaded, cfg: GoasConfig) -> PutWriteResult:
    adj = loaded.adj
    n = len(adj)
    iv_at = {row["market_date"]: row["iv"] for row in loaded.rows}
    cost = cfg.cost_model
    mult = cfg.multiplier
    slots = max(1, round(cfg.dte_days / cfg.cadence_days))
    collateral_per_put = cfg.capital / slots
    t_years = cfg.dte_days / 252.0

    # open positions: list of dicts with expiry_index, strike, credit, contracts.
    # Two ledgers: realized_gross (pre-cost) and realized_cost (transaction costs).
    open_pos: list[dict] = []
    trades: list[PutWriteTrade] = []
    realized_gross = 0.0
    realized_cost = 0.0
    curve_gross: list[tuple[_date, float]] = []
    curve_costed: list[tuple[_date, float]] = []

    for i in range(n):
        d, S = adj[i]
        # 1) settle expiries due today
        still_open: list[dict] = []
        for p in open_pos:
            if p["expiry_index"] == i:
                _, s_exp = adj[i]
                intrinsic = max(0.0, p["strike"] - s_exp)
                gross = (p["credit"] - intrinsic) * mult * p["contracts"]
                trade_cost = cost.total((p["credit"],), p["contracts"])
                net = gross - trade_cost
                realized_gross += gross
                realized_cost += trade_cost
                risk = (p["strike"] - p["credit"]) * mult * p["contracts"]
                trades.append(
                    PutWriteTrade(
                        entry_date=p["entry_date"], expiry_date=d, strike=p["strike"],
                        credit=p["credit"], iv_entry=p["iv_entry"], contracts=p["contracts"],
                        intrinsic=intrinsic, net_pnl=net,
                        return_on_risk=(net / risk if risk > 0 else 0.0),
                        breached=(s_exp < p["strike"]),
                    )
                )
            else:
                still_open.append(p)
        open_pos = still_open

        # 2) open a new put on cadence days when there is room before history ends
        iv = iv_at.get(d)
        if i % cfg.cadence_days == 0 and iv is not None and float(iv) > 0 and S > 0 and i + cfg.dte_days < n:
            try:
                csp = build_csp_skew(S, float(iv), t_years, cfg.r, short_delta=cfg.short_delta, skew=cfg.skew)
                contracts = collateral_per_put / (csp.short_put * mult)
                open_pos.append({
                    "entry_index": i, "expiry_index": i + cfg.dte_days,
                    "entry_date": d, "strike": csp.short_put, "credit": csp.credit,
                    "iv_entry": float(iv), "contracts": contracts,
                })
            except ValueError as exc:  # degenerate strike — skip this entry
                log.debug("putwrite entry skipped %s: %s", d, repr(exc))

        # 3) mark NAV: realized + unrealized(open marked at FAIR VALUE) − fees.
        # Fair-value marks (BS at the current ATM vol + same skew) earn theta
        # gradually and draw down on selloffs; at entry value ≈ credit so the
        # mark adds ≈ 0 (no premium front-load). Falls back to intrinsic only if
        # the day's IV is missing or the position is at expiry.
        atm_t = iv_at.get(d)
        unrealized = 0.0
        for p in open_pos:
            t_rem = (p["expiry_index"] - i) / 252.0
            if atm_t is not None and float(atm_t) > 0 and t_rem > 0:
                iv_mark = cfg.skew.iv(float(atm_t), S, p["strike"]) if cfg.skew else float(atm_t)
                val = bs_price(S, p["strike"], t_rem, cfg.r, iv_mark, is_call=False)
            else:
                val = max(0.0, p["strike"] - S)
            unrealized += (p["credit"] - val) * mult * p["contracts"]
        nav_gross = cfg.capital + realized_gross + unrealized
        nav_costed = cfg.capital + realized_gross - realized_cost + unrealized
        curve_gross.append((d, nav_gross))
        curve_costed.append((d, nav_costed))

    span = (adj[0][0].isoformat(), adj[-1][0].isoformat()) if adj else ("", "")
    return PutWriteResult(curve_gross, curve_costed, trades, span)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_account.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/uw_scan/reports/goas_putwrite_account.py && uv run python scripts/_lint_except.py src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/goas_putwrite_account.py tests/unit/reports/test_goas_putwrite_account.py
git commit -m "feat(goas): laddered cash-secured put-write account simulator with daily NAV + mgmt fee"
```

---

### Task 3: Metrics + SPY buy-hold benchmark (in `goas_putwrite_account.py`)

**Files:**
- Modify: `src/uw_scan/reports/goas_putwrite_account.py` (append functions)
- Test: `tests/unit/reports/test_goas_putwrite_metrics.py`

**Interfaces:**
- Consumes: `PutWriteResult`, `_Loaded`.
- Produces:
  - `curve_metrics(curve: list[tuple[date,float]], *, r: float = 0.04) -> dict` → keys `ann_return`, `ann_vol`, `sharpe`, `max_drawdown`, `calmar`, `cvar5`, `worst_month`, `n_days`.
  - `putwrite_metrics(result: PutWriteResult, *, r: float = 0.04) -> dict` → `{**curve_metrics(net), "gross": curve_metrics(gross), "win_rate", "breach_rate", "mean_credit", "n_trades"}`.
  - `spy_buy_hold(loaded: _Loaded, *, capital: float = 1_000_000.0, r: float = 0.04) -> dict` → `curve_metrics` of the price-return curve (labeled price-return, no dividends).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reports/test_goas_putwrite_metrics.py
from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_account import curve_metrics


def _curve(values: list[float]) -> list[tuple[date, float]]:
    d0 = date(2010, 1, 4)
    return [(d0 + timedelta(days=i), v) for i, v in enumerate(values)]


def test_flat_curve_zero_vol_zero_sharpe():
    m = curve_metrics(_curve([100.0] * 50))
    assert m["ann_vol"] == pytest.approx(0.0)
    assert m["max_drawdown"] == pytest.approx(0.0)
    assert m["sharpe"] == 0.0  # guarded: zero vol → 0, not div-by-zero


def test_drawdown_is_peak_to_trough():
    # 100 → 120 → 60 → 90 : max drawdown = (60-120)/120 = -0.5
    m = curve_metrics(_curve([100.0, 120.0, 60.0, 90.0]))
    assert m["max_drawdown"] == pytest.approx(-0.5, abs=1e-9)


def test_positive_drift_with_variance_positive_sharpe():
    # positive mean daily return WITH dispersion → vol>0 and Sharpe>0. (A constant-
    # return curve has zero vol → Sharpe 0, so the test must vary the steps.)
    navs = [100.0]
    for i in range(300):
        navs.append(navs[-1] * (1 + (0.0012 if i % 2 == 0 else 0.0004)))
    m = curve_metrics(_curve(navs))
    assert m["ann_return"] > 0
    assert m["ann_vol"] > 0
    assert m["sharpe"] > 0
    assert m["max_drawdown"] == pytest.approx(0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_metrics.py -v`
Expected: FAIL with `ImportError: cannot import name 'curve_metrics'`.

- [ ] **Step 3: Write minimal implementation (append the functions to `goas_putwrite_account.py`)**

NOTE: `math`, `collections.defaultdict`, `statistics.fmean/pstdev` are already at the
module top (added in Task 2) — do NOT add mid-file imports here (ruff E402). Append
only the three functions below.

```python
def curve_metrics(curve: list[tuple[_date, float]], *, r: float = 0.04) -> dict:
    """Risk metrics from a daily NAV curve. Sharpe/vol annualized ×√252; CVaR is the
    mean of the worst 5% daily returns; worst_month is the min calendar-month return."""
    navs = [v for _, v in curve]
    n = len(navs)
    if n < 2 or navs[0] <= 0:
        return {"ann_return": 0.0, "ann_vol": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
                "calmar": 0.0, "cvar5": 0.0, "worst_month": 0.0, "n_days": n}
    rets = [(navs[i] / navs[i - 1] - 1.0) if navs[i - 1] > 0 else 0.0 for i in range(1, n)]
    years = (n - 1) / 252.0  # n NAV points → n-1 daily return intervals
    ann_return = (navs[-1] / navs[0]) ** (1.0 / years) - 1.0 if navs[-1] > 0 else -1.0
    ann_vol = pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    # Sharpe: arithmetic mean daily EXCESS return / daily vol, annualized ×√252
    # (conventional; avoids mixing geometric CAGR with arithmetic vol). ann_return
    # stays CAGR for reporting.
    daily_rf = r / 252.0
    _sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean([x - daily_rf for x in rets]) / _sd) * math.sqrt(252) if _sd > 0 else 0.0
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1.0)
    calmar = ann_return / abs(max_dd) if max_dd < 0 else 0.0
    k = max(1, int(len(rets) * 0.05))
    cvar5 = fmean(sorted(rets)[:k]) if rets else 0.0
    by_month: dict[tuple[int, int], list[float]] = defaultdict(list)
    for (d, _), ret in zip(curve[1:], rets, strict=True):
        by_month[(d.year, d.month)].append(ret)
    monthly = [math.prod(1.0 + x for x in v) - 1.0 for v in by_month.values()]
    worst_month = min(monthly) if monthly else 0.0
    return {"ann_return": ann_return, "ann_vol": ann_vol, "sharpe": sharpe,
            "max_drawdown": max_dd, "calmar": calmar, "cvar5": cvar5,
            "worst_month": worst_month, "n_days": n}


def putwrite_metrics(result: "PutWriteResult", *, r: float = 0.04) -> dict:
    # base tier = post-cost/pre-fee (costed); gross (pre-cost) nested under "gross".
    # Fee tiers are derived downstream (apply_fee_to_curve over FEE_GRID).
    gross = curve_metrics(result.equity_curve_gross, r=r)
    costed = curve_metrics(result.equity_curve_costed, r=r)
    tr = result.trades
    n = len(tr)
    return {**costed, "gross": gross,
            "win_rate": (sum(1 for t in tr if t.net_pnl > 0) / n) if n else 0.0,
            "breach_rate": (sum(1 for t in tr if t.breached) / n) if n else 0.0,
            "mean_credit": (fmean([t.credit for t in tr]) if n else 0.0),
            "n_trades": n}


def spy_buy_hold(loaded: _Loaded, *, capital: float = 1_000_000.0, r: float = 0.04) -> dict:
    """Price-return SPY benchmark (lake has no dividends → understates total return)."""
    if not loaded.adj:
        return curve_metrics([], r=r)
    s0 = loaded.adj[0][1]
    curve = [(d, capital * (s / s0)) for d, s in loaded.adj]
    return curve_metrics(curve, r=r)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_metrics.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

Run: `uv run ruff check src/uw_scan/reports/goas_putwrite_account.py && uv run python scripts/_lint_except.py src`

```bash
git add src/uw_scan/reports/goas_putwrite_account.py tests/unit/reports/test_goas_putwrite_metrics.py
git commit -m "feat(goas): NAV risk metrics (Sharpe/maxDD/Calmar/CVaR/worst-month) + SPY buy-hold benchmark"
```

---

### Task 4: Delta×tenor×pricing×fee sweep + regimes + ranking (`goas_putwrite_sweep.py`)

**Files:**
- Create: `src/uw_scan/reports/goas_putwrite_sweep.py`
- Test: `tests/unit/reports/test_goas_putwrite_sweep.py`

**Interfaces:**
- Consumes: `GoasConfig`, `simulate_putwrite`, `putwrite_metrics`, `curve_metrics`, `spy_buy_hold` (Tasks 2–3); `PutSkew`, `calibrate_skew` (Task 1); `_Loaded`.
- Produces:
  - `DELTAS`, `DTES`, `FEE_GRID`, `RANK_FEE`, `PRICING_MODES`, `REGIMES` (module constants; `RANK_FEE ∈ FEE_GRID`).
  - `apply_fee_to_curve(curve, mgmt_fee_annual) -> list[tuple[date,float]]` — correct multiplicative fee drag on the post-cost curve (no day-0 charge, no re-sim).
  - `slice_curve(curve, start, end) -> list[tuple[date,float]]`; `_calm_slice(curve)` (full minus stress windows).
  - `run_sweep(loaded, *, skew: PutSkew | None, fee_grid=FEE_GRID, rank_fee=RANK_FEE, r=0.04) -> dict` — one loaded series + a pre-calibrated skew → all cells; returns `{"cells": [...], "benchmark": {...}, "rank_fee": float, "ranking": [...]}`. Each cell has `gross`, `costed`, `fees`, `rank`, `regimes` (incl. `calm`).
  - `rank_cells(cells) -> list[dict]` — ranks on net-of-fee Sharpe (@RANK_FEE) with the per-regime catastrophic gate.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reports/test_goas_putwrite_sweep.py
from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_sweep import (
    DELTAS, DTES, FEE_GRID, RANK_FEE, apply_fee_to_curve, run_sweep, slice_curve,
)
from uw_scan.reports.vrp_macro_harvest import _Loaded


def _flat_loaded(n_days: int, spot: float, iv: float) -> _Loaded:
    d0 = date(2007, 1, 3)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    adj = [(d, spot) for d in dates]
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_grids_are_specified():
    assert DELTAS == (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
    assert DTES == (21, 30, 42, 63)
    assert FEE_GRID == (0.0, 0.005, 0.010, 0.015)
    assert RANK_FEE in FEE_GRID  # ranking fee basis must be a swept level


def test_apply_fee_monotone():
    curve = [(date(2010, 1, 1) + timedelta(days=i), 100.0) for i in range(252)]
    base = apply_fee_to_curve(curve, 0.0)
    fee1 = apply_fee_to_curve(curve, 0.01)
    assert base[-1][1] == pytest.approx(100.0)
    assert fee1[0][1] == pytest.approx(100.0)  # no fee charged on the seed day
    assert fee1[-1][1] < base[-1][1]


def test_slice_curve_bounds():
    curve = [(date(2010, 1, 1) + timedelta(days=i), float(i)) for i in range(100)]
    sub = slice_curve(curve, date(2010, 1, 10), date(2010, 1, 20))
    assert sub[0][0] >= date(2010, 1, 10) and sub[-1][0] <= date(2010, 1, 20)


def test_run_sweep_covers_full_grid():
    loaded = _flat_loaded(500, spot=100.0, iv=0.18)
    out = run_sweep(loaded, skew=None)
    # one cell per (delta, dte, pricing-mode) — pricing handled by skew arg here = flat only
    assert len(out["cells"]) == len(DELTAS) * len(DTES)
    assert "benchmark" in out and "ranking" in out
    assert all("costed" in c and "gross" in c and "regimes" in c for c in out["cells"])
    assert all("calm" in c["regimes"] for c in out["cells"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_sweep.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/uw_scan/reports/goas_putwrite_sweep.py
"""Delta×tenor×fee sweep for the GOAS put-write, with regime slices and a
sweet-spot ranking. Caller runs it once per pricing mode (flat vs calibrated
skew) by passing skew=None or the calibrated PutSkew. Fee levels are derived
analytically from the zero-fee NAV curve (no re-simulation).
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

from datetime import date as _date

from uw_scan.reports.goas_putwrite_account import (
    GoasConfig, curve_metrics, putwrite_metrics, simulate_putwrite, spy_buy_hold,
)
from uw_scan.reports.goas_putwrite_pricing import PutSkew
from uw_scan.reports.vrp_macro_harvest import _Loaded

DELTAS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
DTES: tuple[int, ...] = (21, 30, 42, 63)
FEE_GRID: tuple[float, ...] = (0.0, 0.005, 0.010, 0.015)
RANK_FEE: float = 0.010  # management-fee basis for the sweet-spot ranking (GOAS-like 1%/yr)
PRICING_MODES: tuple[str, ...] = ("flat", "skew")
# (label, start, end) — stress windows + a full-history marker (None,None → all).
# "calm" (full minus the stress windows) is added per cell in run_sweep.
REGIMES: tuple[tuple[str, _date | None, _date | None], ...] = (
    ("full", None, None),
    ("gfc_2008", _date(2008, 1, 1), _date(2009, 6, 30)),
    ("covid_2020", _date(2020, 2, 15), _date(2020, 4, 30)),
    ("bear_2022", _date(2022, 1, 1), _date(2022, 12, 31)),
)
_STRESS = tuple((s, e) for _label, s, e in REGIMES if s is not None)


def apply_fee_to_curve(curve, mgmt_fee_annual: float):
    """Daily management-fee drag: net[t] = net[t-1]·(1 + pre-fee return_t)·(1 − fee/252).
    No fee on the seed point (day 0); compounds on the prior NET NAV (not gross)."""
    if not curve:
        return []
    daily = mgmt_fee_annual / 252.0
    out = [curve[0]]
    prev_src, prev_net = curve[0][1], curve[0][1]
    for d, v in curve[1:]:
        r_t = (v / prev_src - 1.0) if prev_src > 0 else 0.0
        net = prev_net * (1.0 + r_t) * (1.0 - daily)
        out.append((d, net))
        prev_src, prev_net = v, net
    return out


def slice_curve(curve, start: _date | None, end: _date | None):
    return [(d, v) for d, v in curve if (start is None or d >= start) and (end is None or d <= end)]


def _calm_slice(curve):
    """Full history minus the named stress windows."""
    return [(d, v) for d, v in curve if not any(s <= d <= e for s, e in _STRESS)]


def run_sweep(loaded: _Loaded, *, skew: PutSkew | None, fee_grid=FEE_GRID,
              rank_fee: float = RANK_FEE, r: float = 0.04) -> dict:
    """All cells for ONE pricing mode (skew=None → flat; a PutSkew → skew). Fee tiers
    derived from the post-cost curve; ranking + regimes measured net-of-fee at rank_fee."""
    pricing = "skew" if skew is not None else "flat"
    cells: list[dict] = []
    for delta in DELTAS:
        for dte in DTES:
            cfg = GoasConfig(short_delta=delta, dte_days=dte, skew=skew, r=r)
            res = simulate_putwrite(loaded, cfg)
            base = putwrite_metrics(res, r=r)  # post-cost/pre-fee; "gross" nested
            fees = {f: curve_metrics(apply_fee_to_curve(res.equity_curve_costed, f), r=r)
                    for f in fee_grid}
            rank_curve = apply_fee_to_curve(res.equity_curve_costed, rank_fee)
            rank_metric = curve_metrics(rank_curve, r=r)
            regimes = {label: curve_metrics(slice_curve(rank_curve, s, e), r=r)
                       for label, s, e in REGIMES}
            regimes["calm"] = curve_metrics(_calm_slice(rank_curve), r=r)
            cells.append({
                "delta": delta, "dte": dte, "pricing": pricing,
                "n_trades": base["n_trades"], "span": res.span,
                "gross": base["gross"],
                "costed": {k: v for k, v in base.items() if k != "gross"},
                "fees": fees, "rank": rank_metric, "regimes": regimes,
            })
    benchmark = spy_buy_hold(loaded, r=r)
    return {"cells": cells, "benchmark": benchmark, "rank_fee": rank_fee,
            "ranking": rank_cells(cells)}


def rank_cells(cells: list[dict]) -> list[dict]:
    """Rank by net-of-fee Sharpe (measured at RANK_FEE), DROPPING any cell that
    catastrophically degrades in a stress regime (per-regime gate, AC-F4 style):
    a stress-window Sharpe below −1.0 disqualifies."""
    def survives(c: dict) -> bool:
        for label in ("gfc_2008", "covid_2020", "bear_2022"):
            reg = c["regimes"].get(label, {})
            if reg.get("n_days", 0) > 5 and reg.get("sharpe", 0.0) < -1.0:
                return False
        return True
    ranked = sorted((c for c in cells if survives(c)),
                    key=lambda c: c["rank"]["sharpe"], reverse=True)
    return [{"delta": c["delta"], "dte": c["dte"], "pricing": c["pricing"],
             "sharpe": c["rank"]["sharpe"], "ann_return": c["rank"]["ann_return"],
             "max_drawdown": c["rank"]["max_drawdown"], "calmar": c["rank"]["calmar"]}
            for c in ranked]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_sweep.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

Run: `uv run ruff check src/uw_scan/reports/goas_putwrite_sweep.py && uv run python scripts/_lint_except.py src`

```bash
git add src/uw_scan/reports/goas_putwrite_sweep.py tests/unit/reports/test_goas_putwrite_sweep.py
git commit -m "feat(goas): delta×tenor×fee sweep with regime slices + per-regime-gated sweet-spot ranking"
```

---

### Task 5: Research runner — real-data run, CSV traces, findings note (`scripts/research/goas_putwrite_run.py`)

**Files:**
- Create: `scripts/research/goas_putwrite_run.py`
- Create (output, generated by the run): `docs/research/goas-putwrite/goas-delta-dte-sweep-2026-06-23.csv`, `goas-trade-log-2026-06-23.csv`, `goas-skew-vs-flat-2026-06-23.csv`, `goas-regime-2026-06-23.csv`, `MASTER-goas-putwrite-2026-06-23.md`

**Interfaces:**
- Consumes: `run_sweep`, `DELTAS`, `DTES`, `FEE_GRID` (Task 4); `calibrate_skew`, `GOAS_*` constants (Task 1); `load_index_vol` (`uw_scan.reports.vrp_macro_drawdown`); `Settings`/repo construction.

- [ ] **Step 1: Write the runner (no unit test — verification is the real-data run)**

This script mirrors the DB/repo/settings wiring of `scripts/research/vrp_robustness_run.py` (env-var DB selection: `UW_SCAN_DB_HOST` / `UW_SCAN_DB_NAME` / `UW_SCAN_DB_USER` / `UW_SCAN_API_KEY`). Copy that connection boilerplate verbatim, then:

```python
#!/usr/bin/env python
"""GOAS put-write delta sweep — real-data run.

Loads SPY (spot from the equity lake + VIX/100 as ATM IV) from 2006, calibrates
the downside skew to GOAS's published 96.2%/0.7% 1-month quote at the 2026-05-05
VIX, runs the delta×tenor sweep under BOTH flat and skew pricing, writes CSV
traces + a findings note under docs/research/goas-putwrite/.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
    uv run python scripts/research/goas_putwrite_run.py
(or point at any DB whose uw_scan.vol_index_daily has VIX+SPX and the equity lake has SPY)
"""
from __future__ import annotations

import csv
import pathlib
from datetime import date

# --- DB/repo/settings setup: copy from scripts/research/vrp_robustness_run.py ---
# (constructs `settings` and `repo` from env)
from uw_scan.reports.goas_putwrite_pricing import (
    GOAS_AS_OF, GOAS_DTE_DAYS, GOAS_PREMIUM_FRAC, GOAS_STRIKE_FRAC, calibrate_skew,
)
from uw_scan.reports.goas_putwrite_sweep import FEE_GRID, run_sweep
from uw_scan.reports.vrp_macro_drawdown import _vol_index_close, load_index_vol

OUT = pathlib.Path("docs/research/goas-putwrite")
STAMP = "2026-06-23"


def _calibrate(repo, loaded, r: float):
    # ATM VIX on GOAS_AS_OF (nearest prior day if the exact date is missing)
    vix = _vol_index_close(repo, "VIX", date(2006, 1, 1))
    asof_vix = vix.get(GOAS_AS_OF) or vix[max(d for d in vix if d <= GOAS_AS_OF)]
    spot = dict(loaded.adj)
    asof_spot = spot.get(GOAS_AS_OF) or spot[max(d for d in spot if d <= GOAS_AS_OF)]
    skew = calibrate_skew(
        asof_spot, asof_vix / 100.0, GOAS_DTE_DAYS / 252.0, r,
        target_strike_frac=GOAS_STRIKE_FRAC, target_premium_frac=GOAS_PREMIUM_FRAC,
    )
    return skew, asof_spot, asof_vix


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # ... build `settings`, `repo` from env (per vrp_robustness_run.py) ...
    r = settings.vrp_risk_free_rate  # noqa: F821  (settings from the copied boilerplate)
    loaded = load_index_vol(repo, "SPY")  # noqa: F821
    skew, asof_spot, asof_vix = _calibrate(repo, loaded, r)  # noqa: F821

    flat = run_sweep(loaded, skew=None, r=r)
    skewed = run_sweep(loaded, skew=skew, r=r)

    # 1) full sweep CSV (both pricing modes, every fee level)
    with (OUT / f"goas-delta-dte-sweep-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pricing", "delta", "dte", "fee", "ann_return", "ann_vol",
                    "sharpe", "max_drawdown", "calmar", "cvar5", "worst_month",
                    "win_rate", "breach_rate", "mean_credit", "n_trades"])
        for out in (flat, skewed):
            for c in out["cells"]:
                for fee, m in c["fees"].items():
                    w.writerow([c["pricing"], c["delta"], c["dte"], fee,
                                m["ann_return"], m["ann_vol"], m["sharpe"],
                                m["max_drawdown"], m["calmar"], m["cvar5"],
                                m["worst_month"], c["costed"]["win_rate"],
                                c["costed"]["breach_rate"], c["costed"]["mean_credit"],
                                c["n_trades"]])

    # 2) skew-vs-flat at fee=0 (ranking-flip check) — one row per (delta,dte)
    with (OUT / f"goas-skew-vs-flat-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["delta", "dte", "flat_sharpe", "skew_sharpe",
                    "flat_ann_return", "skew_ann_return"])
        fmap = {(c["delta"], c["dte"]): c for c in flat["cells"]}
        smap = {(c["delta"], c["dte"]): c for c in skewed["cells"]}
        for key in sorted(fmap):
            fc, sc = fmap[key], smap[key]
            # compare on the ranking basis (net-of-fee @ RANK_FEE) → the flip check
            w.writerow([key[0], key[1], fc["rank"]["sharpe"], sc["rank"]["sharpe"],
                        fc["rank"]["ann_return"], sc["rank"]["ann_return"]])

    # 3) regime CSV for the top skew cell
    top = skewed["ranking"][0] if skewed["ranking"] else None
    with (OUT / f"goas-regime-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pricing", "delta", "dte", "regime", "sharpe", "ann_return",
                    "max_drawdown", "worst_month", "n_days"])
        for out in (flat, skewed):
            for c in out["cells"]:
                if top and (c["delta"], c["dte"]) != (top["delta"], top["dte"]):
                    continue
                for label, m in c["regimes"].items():
                    w.writerow([c["pricing"], c["delta"], c["dte"], label,
                                m["sharpe"], m["ann_return"], m["max_drawdown"],
                                m["worst_month"], m["n_days"]])

    # 4) trade log for the top skew cell
    # (re-simulate the single winning config to dump its trades)
    from uw_scan.reports.goas_putwrite_account import GoasConfig, simulate_putwrite
    if top:
        res = simulate_putwrite(loaded, GoasConfig(short_delta=top["delta"],
                                                   dte_days=top["dte"], skew=skew, r=r))
        with (OUT / f"goas-trade-log-{STAMP}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["entry_date", "expiry_date", "strike", "credit", "iv_entry",
                        "contracts", "intrinsic", "net_pnl", "return_on_risk", "breached"])
            for t in res.trades:
                w.writerow([t.entry_date, t.expiry_date, t.strike, t.credit, t.iv_entry,
                            t.contracts, t.intrinsic, t.net_pnl, t.return_on_risk, t.breached])

    # 5) findings note (skeleton with the real headline numbers filled by the run)
    _write_master_note(flat, skewed, asof_spot, asof_vix)
    print("GOAS put-write sweep complete →", OUT)


if __name__ == "__main__":
    main()
```

`_write_master_note` must be DEFINED in the runner (not just described) — define it above `main()`:

```python
def _write_master_note(flat: dict, skewed: dict, asof_spot: float, asof_vix: float) -> None:
    ftop = flat["ranking"][0] if flat["ranking"] else None
    stop = skewed["ranking"][0] if skewed["ranking"] else None
    agree = bool(ftop and stop and (ftop["delta"], ftop["dte"]) == (stop["delta"], stop["dte"]))
    bench = skewed["benchmark"]
    flip = "" if agree else (
        " → ranking is skew-sensitive; treat the sweet spot as UNRESOLVED pending a "
        "real historical surface."
    )
    lines = [
        f"# GOAS Put-Write Delta Sweep — Findings ({STAMP})",
        "",
        "**Exploratory research.** Skew shape is MODELED (calibrated to one real GOAS "
        "quote), not observed — flat-vol is the conservative floor, skew the GOAS-faithful "
        "estimate; the truth is bracketed between them.",
        "",
        f"## Sweet spot (net-of-fee Sharpe @ {int(skewed['rank_fee'] * 10000)}bps, "
        "per-regime catastrophe gate applied)",
        f"- Flat-vol top: {ftop}",
        f"- Skew top:     {stop}",
        f"- Flat & skew AGREE on top (delta, dte): **{agree}**{flip}",
        "",
        "## GOAS validation",
        f"- Calibration anchor: {GOAS_AS_OF} SPY={asof_spot:.2f} VIX={asof_vix:.2f}; "
        f"target strike {GOAS_STRIKE_FRAC:.3f}·S, premium {GOAS_PREMIUM_FRAC:.3f}·S "
        "(~7.7% annualized in GOAS's table).",
        "- Net result at ~15Δ / 1-month vs GOAS's 3–6% net: see the fee column in "
        "goas-delta-dte-sweep CSV.",
        "",
        f"## SPY buy-and-hold (price-return): Sharpe {bench['sharpe']:.2f}, "
        f"maxDD {bench['max_drawdown']:.2%}, CAGR {bench['ann_return']:.2%}",
        "",
        "## Caveats: constant-slope modeled skew (understates crisis put richness); "
        "European cash-settle vs GOAS's American roll-managed book; price-return SPY "
        "benchmark (no dividends); VIX constant-maturity 30d applied across tenors.",
        "",
        f"## Honest de-rating: the headline is the best of {len(skewed['cells'])} cells "
        "× 2 pricing modes — expect favorable-corner overfit; de-rate the in-sample "
        "Sharpe and prefer the delta that wins under BOTH pricing modes and all regimes.",
        "",
        "## Reproduce:",
        "```",
        "UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard "
        "UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/research/goas_putwrite_run.py",
        "```",
    ]
    (OUT / f"MASTER-goas-putwrite-{STAMP}.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 2: Run the runner against real data (verification = evidence)**

Run (env per the docstring; the mini has the data):
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python scripts/research/goas_putwrite_run.py
```
Expected: prints "GOAS put-write sweep complete"; five files appear under `docs/research/goas-putwrite/`. Sanity-check the headline: at ≈15Δ / 30d the **gross** annualized premium is in the neighborhood of GOAS's 7.7%, and a net column lands inside 3–6% at some fee level. If wildly off, debug pricing/sizing before proceeding (do not paper over a discrepancy).

- [ ] **Step 3: Lint the runner**

Run: `uv run ruff check scripts/research/goas_putwrite_run.py && uv run python scripts/_lint_except.py scripts`
Expected: clean (the `scripts` guardrail scope includes research scripts).

- [ ] **Step 4: Commit (code + traces + note together)**

```bash
git add scripts/research/goas_putwrite_run.py docs/research/goas-putwrite/
git commit -m "feat(goas): research runner + delta-sweep traces + findings note (SPY put-write)"
```

---

### Task 6: Full test + lint parity pass (CI-equivalent)

**Files:** none (verification only)

- [ ] **Step 1: Run the full new unit suite**

Run: `uv run pytest tests/unit/reports/test_goas_putwrite_pricing.py tests/unit/reports/test_goas_putwrite_account.py tests/unit/reports/test_goas_putwrite_metrics.py tests/unit/reports/test_goas_putwrite_sweep.py -v`
Expected: all green.

- [ ] **Step 2: Reproduce the CI `lint + unit` gates locally**

Run each, expect clean/green (per the check-CI-green memory — ruff+pytest is NOT sufficient):
```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/_lint_except.py scripts
uv run pytest tests/unit/ -q
```

- [ ] **Step 3: Confirm no stray artifacts / standing-rule check**

Confirm: no naked shorts (CSP only); no Yahoo; traces committed under `docs/research/goas-putwrite/`; no DB writes (research-only); modules each < 500 lines (`wc -l src/uw_scan/reports/goas_putwrite_*.py`).

---

## Self-Review

**1. Spec coverage:**
- Skew model + delta-consistent strike + calibration → Task 1. ✅
- Laddered NAV account, hold-to-expiry intrinsic, daily mgmt fee, defined-risk → Task 2. ✅
- Metrics (Sharpe/maxDD/Calmar/CVaR/worst-month, gross+net), SPY buy-hold → Task 3. ✅
- Delta×tenor×pricing×fee sweep, regime slices, per-regime-gated ranking → Task 4. ✅
- Runner, CSV traces, findings note, GOAS validation, reproduce command → Task 5. ✅
- CI parity → Task 6. ✅
- Frozen real fixtures / no runtime network → Task 1 Step 1 + test design. ✅
- Skew-vs-flat ranking-flip check → Task 5 CSV #2 + note. ✅
- Out-of-scope (QQQ/IWM, margin, MC, DB/API) → not in any task. ✅ (intentional)

**2. Placeholder scan:** The only `TODO-AUTHOR` markers are in Task 1 Step 1 (the two real fixture literals) — these are *deliberately* filled by fetching real data once (Step 1's query), not invented; this is the no-fabrication rule in action, not a plan gap. No other TBD/TODO.

**3. Type consistency:** `GoasConfig`, `PutWriteResult.equity_curve_gross/_costed`, `PutWriteTrade` fields, `PutSkew(slope).iv(atm,S,K)`, `build_csp_skew(...,skew=)`, `calibrate_skew(...,target_strike_frac=,target_premium_frac=)`, `curve_metrics`/`putwrite_metrics`/`spy_buy_hold`, `run_sweep(loaded,*,skew=)`, `apply_fee_to_curve`/`slice_curve`/`rank_cells` — names match across Tasks 1→5. `_Loaded` is imported from `vrp_macro_harvest` everywhere. ✅

## Spec consistency note (applied)

The spec's `GoasConfig.ramp_weeks` is **replaced** by natural laddered accumulation (Task 2 docstring) — simpler and equally faithful (the book fills over ~DTE ≈ GOAS's 4–5 weeks at 30d weekly). The spec will be synced to match before review.
