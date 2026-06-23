# VRP Capital-Utilisation Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the annualised return and capital utilisation of a two-layer macro short-vol book — the deployed Sharpe-1.65 `ramp+` bull-put-spread as the always-eligible **base**, plus a **binary overlay** that sells an extra set when vol is very rich — run on a single shared **$50,000** cash account across SPY/QQQ/IWM.

**Architecture:** A new dollar-accounting layer (`reports/vrp_capital_account.py`) that *reuses* the validated, untouched pricing/loaders (`build_bull_put_spread`, `_settle`, `load_index_vol`, `size_weight`/`WINNER`) and adds an event-driven $50k ledger: candidate weekly entries across all names share one buying-power line; each rung's contract count is floored to a risk-% of $50k and capped by available capital (shortfalls logged, never silent); the full daily margin path → utilisation, and per-month dollar P&L → CAGR/Sharpe/maxDD. A research runner sweeps `(base_risk_pct × overlay_mult × rich_threshold)`, persists the full result set to a committed CSV, and emits a findings notebook + verdict markdown.

**Tech Stack:** Python 3.13 (`uv` only), psycopg 3, stdlib `statistics`/`math` (no numpy/scipy — match `vrp_structure.py`), pytest, pyarrow (lake reads, transitively via `load_index_vol`).

## Global Constraints

- **uv only** — `uv run pytest`, `uv run python …`; never bare `python`/`pip`.
- **Reuse, do not modify, the validated engine** — `reports/vrp_structure.py`, `reports/vrp_macro_harvest.py`, `reports/vrp_macro_signal.py`, and the pricing/loader bodies of `reports/vrp_macro_drawdown.py` are imported unchanged. The **only** edit to an existing file is an additive `INDEX_SPECS["SPY"]` entry (Task 1).
- **Do not touch `scripts/_vrp_macro_param_sweep.py`** — it is the reproducer for `docs/research/vrp/macro-short-vol-verdict.md`; the new work is a sibling, not a replacement.
- **Base = the deployed 1.65-Sharpe winner** — `WINNER` from `vrp_macro_signal.py`: bull put spread, `short_delta=0.25`, `wing_frac=0.5` (→ wing_delta 0.125), `hold_days=30`, `cadence=5` (weekly), `sizing="ramp+"` (`size_weight` = `clamp(z/0.5, 0, 1)`), held to expiry. The base keeps its vrp-z gate (idle when vol is cheap).
- **Overlay = binary fixed extra** — when `vrp_z >= rich_threshold`, add `floor(overlay_mult × base_risk_pct × $50k / max_loss_per_contract)` extra contracts of the *same* spread. Overlay size is **not** w-scaled.
- **Flat-vol BS model** (skew ignored) — conservative for put spreads (real put-skew credit ≥ modeled). Same caveat as the prior verdict; state it in the verdict doc.
- **No Yahoo.** Data is `vol_index_daily` (VIX/VXN/RVX, the local mirror of the R2 vol-complex lake) + the equity lake (SPY/QQQ/IWM bars) — both reached through the existing `load_index_vol`.
- **Persist the full trace** — every `(config × every metric)` row → committed `docs/research/vrp/capital-sweep-results.csv`; reproduce command in the runner docstring; deterministic (no RNG, no seed).
- **Module size budget** — `reports/vrp_capital_account.py` stays < 500 lines (one cohesive ledger domain).
- **DB tier** — runs on the MacBook against `option_wizard_local` (read-only: it only SELECTs `vol_index_daily` + reads lake parquet). Integration tests that need the DB are marked and skipped by default `pytest`.
- **Lake dependency** — SPY/QQQ/IWM spot comes from the equity lake (`$MARKET_WAREHOUSE_LAKE`, default `~/market-warehouse/data-lake`); SPX/VIX/VXN/RVX come from `vol_index_daily`. A missing lake fails the run loudly at `load_index_vol` — confirm the local mirror is present before running Task 5.
- **Capital model** — one shared $50k; idle cash earns rf (4%) so reported P&L is **excess**; "gross" = excess + rf. Constant $50k base (P&L accrues to a separate tally; base does not compound into sizing). Report BOTH the arithmetic annualised return (mean monthly × 12) and the geometric `cagr_*` — they are different views, never conflate them.
- **Contract multiplier** = 100. Integer contracts only (`floor`); a rung that cannot afford 1 contract is a skip. The overlay is an *extra set on a base* — no base contract ⇒ no overlay.
- **Same-date priority** — entries across names on the same date are economically simultaneous; their order for consuming the shared line rotates deterministically by date ordinal (no name is systematically first). Capital-binding frequency is surfaced via `skip_rate`/`fill_rate`, never silently.
- **Margin release** — buying power frees at expiry (same-day reuse allowed); T+1 settlement is NOT modeled — a minor optimism on the subset of entries landing on an expiry date. Documented, not corrected (research-grade convention).

---

## File Structure

- **Create** `src/uw_scan/reports/vrp_capital_account.py` — `CapitalConfig`, `desired_contracts`, `simulate_account`, `account_metrics`, `AccountResult`/`Rung` dataclasses. The whole ledger domain.
- **Modify** `src/uw_scan/reports/vrp_macro_drawdown.py:31-50` — add `INDEX_SPECS["SPY"]` (additive).
- **Create** `tests/unit/reports/test_vrp_capital_account.py` — ledger math, capital cap/skip, overlay gating, metrics (synthetic `_Loaded` doubles; no network).
- **Create** `tests/integration/reports/test_vrp_capital_account_db.py` — SPY loads from real data; new dollar ledger reconciles with the validated `backtest_laddered` Sharpe (marked, DB-gated).
- **Create** `scripts/research/vrp_capital_sweep.py` — the sweep runner; writes the full CSV; prints the headline frontier + the reconciliation self-check.
- **Create** `scripts/_build_vrp_capital_notebook.py` — throwaway notebook builder (mirrors `scripts/_build_vrp_macro_notebook.py`).
- **Create** `docs/research/vrp/capital-sweep-results.csv` — the durable full result set (written by the runner).
- **Create** `docs/research/vrp/macro-capital-utilisation-findings.ipynb` — findings notebook.
- **Create** `docs/research/vrp/macro-capital-utilisation-verdict.md` — the verdict.

---

### Task 1: Add SPY to INDEX_SPECS

**Files:**
- Modify: `src/uw_scan/reports/vrp_macro_drawdown.py:31-50`
- Test: `tests/unit/reports/test_vrp_capital_account.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `INDEX_SPECS["SPY"]` → `load_index_vol(repo, "SPY")` becomes valid (VIX proxy, lake spot symbol `SPY`, start 2006-01-01).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reports/test_vrp_capital_account.py
from datetime import date
from uw_scan.reports.vrp_macro_drawdown import INDEX_SPECS


def test_spy_in_index_specs():
    spec = INDEX_SPECS["SPY"]
    assert spec["vol"] == "VIX"
    assert spec["spot_source"] == "lake"
    assert spec["spot_symbol"] == "SPY"
    assert spec["start"] == date(2006, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py::test_spy_in_index_specs -v`
Expected: FAIL with `KeyError: 'SPY'`.

- [ ] **Step 3: Add the SPY entry**

In `src/uw_scan/reports/vrp_macro_drawdown.py`, inside the `INDEX_SPECS` dict (after the `IWM` entry, before the closing `}`):

```python
    "SPY": {
        "vol": "VIX",
        "spot_source": "lake",
        "spot_symbol": "SPY",
        "start": _date(2006, 1, 1),
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py::test_spy_in_index_specs -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_macro_drawdown.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): add SPY to macro INDEX_SPECS (VIX proxy + lake spot)"
```

---

### Task 2: CapitalConfig + desired_contracts (sizing → integer contracts)

**Files:**
- Create: `src/uw_scan/reports/vrp_capital_account.py`
- Test: `tests/unit/reports/test_vrp_capital_account.py`

**Interfaces:**
- Consumes: `MacroSignalConfig`, `WINNER` from `uw_scan.reports.vrp_macro_signal`.
- Produces:
  - `CONTRACT_MULTIPLIER: int = 100`
  - `CapitalConfig(capital=50_000.0, base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0, names=("SPY","QQQ","IWM"), min_date: date|None=None, base_cfg: MacroSignalConfig=WINNER)` — frozen dataclass.
  - `desired_contracts(w: float, z: float|None, max_loss_per_contract: float, capcfg: CapitalConfig) -> tuple[int, int]` returning `(base_contracts, overlay_contracts)`. `max_loss_per_contract` is the dollar margin of one spread (`spread.max_loss × 100`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/reports/test_vrp_capital_account.py  (append)
import math
from uw_scan.reports.vrp_capital_account import CapitalConfig, desired_contracts


def test_desired_contracts_base_floor_no_overlay():
    # w=1 full base, 5% of $50k = $2500 risk; mlpc=$1000 → floor(2.5)=2 base, z below threshold → 0 overlay
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 0.4, 1000.0, cfg)
    assert (base, overlay) == (2, 0)


def test_desired_contracts_base_scaled_by_w():
    # ramp+ half-size w=0.5 → $1250 risk / $1000 = floor(1.25)=1
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(0.5, 0.25, 1000.0, cfg)
    assert (base, overlay) == (1, 0)


def test_desired_contracts_overlay_fires_when_rich():
    # z >= rich_threshold=1.0 → overlay = floor(overlay_mult(1.0)*0.05*50000 / 1000) = floor(2.5)=2
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.2, 1000.0, cfg)
    assert (base, overlay) == (2, 2)


def test_desired_contracts_overlay_not_w_scaled():
    # overlay is binary-fixed, independent of w; double mult → floor(2*2500/1000)=5
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=2.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.5, 1000.0, cfg)
    assert overlay == 5


def test_desired_contracts_zero_weight_zero_base():
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(0.0, None, 1000.0, cfg)
    assert (base, overlay) == (0, 0)


def test_desired_contracts_unaffordable_single_contract_is_zero():
    # mlpc bigger than the whole risk budget → 0 base
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 0.4, 9000.0, cfg)  # 2500/9000 → floor 0
    assert base == 0


def test_desired_contracts_no_overlay_without_base():
    # base floors to 0 (budget < 1 contract) but overlay_mult=2 would round up → must be 0:
    # an "extra set" needs a base set to add to. base_risk%=0.03×50k=$1500 < mlpc $1600.
    cfg = CapitalConfig(base_risk_pct=0.03, overlay_mult=2.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.5, 1600.0, cfg)  # base floor(1500/1600)=0
    assert (base, overlay) == (0, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k desired_contracts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.reports.vrp_capital_account'`.

- [ ] **Step 3: Create the module with config + desired_contracts**

```python
# src/uw_scan/reports/vrp_capital_account.py
"""$50k dollar-account ledger for the two-layer macro short-vol book.

REUSES (does not reimplement) the validated flat-vol pricing and VRP loaders:
`build_bull_put_spread` + `_settle` (P&L), `load_index_vol` (IV/spot/vrp_z),
`size_weight`/`WINNER` (the deployed 1.65-Sharpe ramp+ sizing). This layer adds the
dollar accounting the ROR engine deliberately discards: a single shared $50k
buying-power line, integer contracts floored to a risk-% of capital, capital-capped
entries (shortfalls logged, never silent), a daily margin path → utilisation, and
per-month dollar P&L → CAGR / Sharpe / maxDD.

Base layer  = WINNER (ramp+ vrp-z-sized bull put spread, weekly, DTE30, 0.25/0.125Δ).
Overlay     = binary: + overlay_mult sets of the same spread when vrp_z >= rich_threshold.

Research/engine layer — returns results; the runner (scripts/research/vrp_capital_sweep.py)
persists them. Reproduce: see that script's docstring.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date

from uw_scan.reports.vrp_macro_signal import WINNER, MacroSignalConfig

log = logging.getLogger(__name__)

CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class CapitalConfig:
    """One shared cash account. `base_risk_pct` is the fraction of `capital` that a
    full-size (w=1) base rung risks; the overlay risks `overlay_mult × base_risk_pct`
    of capital when `vrp_z >= rich_threshold`. `base_cfg` is the deployed winner."""

    capital: float = 50_000.0
    base_risk_pct: float = 0.05
    overlay_mult: float = 1.0
    rich_threshold: float = 1.0
    names: tuple[str, ...] = ("SPY", "QQQ", "IWM")
    min_date: _date | None = None
    base_cfg: MacroSignalConfig = WINNER


def desired_contracts(
    w: float, z: float | None, max_loss_per_contract: float, capcfg: CapitalConfig
) -> tuple[int, int]:
    """(base, overlay) integer contract counts before the shared-capital cap.

    base    = floor(w × base_risk_pct × capital / max_loss_per_contract)   (ramp+ w)
    overlay = floor(overlay_mult × base_risk_pct × capital / max_loss_per_contract)
              when base >= 1 and z >= rich_threshold, else 0  (binary, not w-scaled)

    The overlay is an *extra set added to a base* — if the account can't afford even
    one base contract (base == 0), there is no position to add to, so overlay is 0 too.
    This prevents a degenerate "overlay-only, no base" trade when base floors to 0 but
    overlay_mult rounds up (e.g. base_risk_pct=0.03 on SPY at $1.6k margin, overlay_mult=2).
    """
    if max_loss_per_contract <= 0:
        return 0, 0
    base = 0
    if w > 0:
        base = math.floor(w * capcfg.base_risk_pct * capcfg.capital / max_loss_per_contract)
    overlay = 0
    if (
        base >= 1
        and z is not None
        and z >= capcfg.rich_threshold
        and capcfg.overlay_mult > 0
    ):
        overlay = math.floor(
            capcfg.overlay_mult * capcfg.base_risk_pct * capcfg.capital / max_loss_per_contract
        )
    return base, overlay
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k desired_contracts -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): CapitalConfig + desired_contracts sizing for the $50k ledger"
```

---

### Task 3: simulate_account (event-driven shared-$50k ledger)

**Files:**
- Modify: `src/uw_scan/reports/vrp_capital_account.py`
- Test: `tests/unit/reports/test_vrp_capital_account.py`

**Interfaces:**
- Consumes: `_Loaded` from `uw_scan.reports.vrp_macro_drawdown`; `_settle` from `uw_scan.reports.vrp_macro_harvest`; `CostModel`, `build_bull_put_spread` from `uw_scan.reports.vrp_structure`; `size_weight` from `uw_scan.reports.vrp_macro_signal`; `desired_contracts`, `CapitalConfig`, `CONTRACT_MULTIPLIER` from this module.
- Produces:
  - `Rung(name, entry_date, exit_date, contracts, margin, net_pnl, breached)` — frozen dataclass.
  - `AccountResult(rungs: list[Rung], monthly_excess: dict[tuple[int,int],float], util_by_date: list[tuple[date,float]], n_desired_rungs: int, n_skipped_rungs: int, contracts_desired_total: int, contracts_filled_total: int, span: tuple[date,date])` — dataclass.
  - `simulate_account(loadeds: dict[str, _Loaded], settings, capcfg: CapitalConfig) -> AccountResult`. `monthly_excess` values are P&L as a fraction of `capital`. `settings` supplies `vrp_risk_free_rate` + the four `vrp_cost_*` knobs.

**Ledger semantics (must hold):** candidate weekly entries (per name, trading-day indices `0, cadence, 2·cadence, …`, restricted to `>= min_date`) are processed in `(entry_date, name)` order against one shared `capital`. Before an entry, capital still held by rungs whose `exit_date > entry_date` is unavailable. Each entry: size base+overlay desire, cap at `floor(available / max_loss_per_contract)`, open `actual = min(desired, affordable)` contracts (log a shortfall if `actual < desired`; count a skip if `desired > 0` but `actual == 0`). P&L via `_settle(..., contracts=actual)` booked into the exit month. Margin = `max_loss × 100 × actual`, held `[entry_date, exit_date)`.

- [ ] **Step 1: Write the failing tests (synthetic `_Loaded` doubles)**

```python
# tests/unit/reports/test_vrp_capital_account.py  (append)
from datetime import date, timedelta
from types import SimpleNamespace
from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_capital_account import AccountResult, simulate_account


def _settings():
    # real config defaults, frozen here so the unit test needs no env/DB
    return SimpleNamespace(
        vrp_risk_free_rate=0.04,
        vrp_cost_per_contract=0.65,
        vrp_slippage_frac=0.01,
        vrp_slippage_min=0.05,
        vrp_cost_round_trip=True,
    )


def _synthetic_loaded(*, spot, iv, z, start=date(2020, 1, 1), n=80):
    """A labelled SYNTHETIC _Loaded (test double of load_index_vol output) for
    exercising the LEDGER — not market data. Flat spot/iv/z across n trading days
    (weekday-spaced) so contract math is hand-checkable."""
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    adj = [(dd, float(spot)) for dd in dates]
    pidx = {dd: k for k, dd in enumerate(dates)}
    rows = [
        {"market_date": dd, "iv": float(iv), "rv": None, "vrp": None, "vrp_z_20": z}
        for dd in dates
    ]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_simulate_single_name_opens_weekly_rungs():
    # one name, ample capital, cheap-but-positive z (w<1 via ramp+) → base only, no skips
    loaded = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0, names=("SPY",))
    res = simulate_account({"SPY": loaded}, _settings(), cfg)
    assert isinstance(res, AccountResult)
    assert res.n_skipped_rungs == 0
    assert all(r.contracts >= 1 for r in res.rungs)
    # weekly cadence over (n - hold_days) = (80 - 30) trading days → entries at 0,5,...,45 → 10 rungs
    assert len(res.rungs) == 10


def test_simulate_overlay_adds_contracts_when_rich():
    cheap = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)   # w<1, no overlay
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)    # w=1 + overlay fires
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0, names=("SPY",))
    c_cheap = sum(r.contracts for r in simulate_account({"SPY": cheap}, _settings(), cfg).rungs)
    c_rich = sum(r.contracts for r in simulate_account({"SPY": rich}, _settings(), cfg).rungs)
    assert c_rich > c_cheap


def test_simulate_capital_cap_forces_skips():
    # tiny capital + rich z (wants base+overlay) → most rungs can't fit → skips logged
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)
    cfg = CapitalConfig(capital=3_000.0, base_risk_pct=0.50, overlay_mult=2.0, rich_threshold=1.0, names=("SPY",))
    res = simulate_account({"SPY": rich}, _settings(), cfg)
    assert res.contracts_filled_total < res.contracts_desired_total
    assert res.n_skipped_rungs > 0


def test_simulate_exit_frees_capital():
    # capital sized so exactly one rung's margin fits at a time; with 30-day hold and
    # weekly entries, overlapping rungs are skipped until earlier ones expire.
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5, n=120)
    big = CapitalConfig(capital=1_000_000.0, base_risk_pct=0.05, overlay_mult=0.0, rich_threshold=1.0, names=("SPY",))
    res_big = simulate_account({"SPY": rich}, _settings(), big)
    one_slot = res_big.rungs[0].margin  # margin of a single full base rung
    tight = CapitalConfig(capital=one_slot * 1.4, base_risk_pct=0.05, overlay_mult=0.0, rich_threshold=1.0, names=("SPY",))
    res_tight = simulate_account({"SPY": rich}, _settings(), tight)
    # can't hold the ~6 concurrent rungs a 30d hold / weekly cadence implies → some skipped
    assert res_tight.n_skipped_rungs > 0
    # but never exceeds capital: peak deployed <= capital
    peak = max(u for _, u in res_tight.util_by_date)
    assert peak <= 1.0 + 1e-9


def test_simulate_shared_capital_across_names():
    # two names competing for one pool deploy more total than each alone but never > capital
    a = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)
    b = _synthetic_loaded(spot=300.0, iv=0.22, z=1.5)
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0, names=("SPY", "QQQ"))
    res = simulate_account({"SPY": a, "QQQ": b}, _settings(), cfg)
    assert {r.name for r in res.rungs} == {"SPY", "QQQ"}
    assert max(u for _, u in res.util_by_date) <= 1.0 + 1e-9


def test_simulate_respects_capcfg_names_ignores_extra_loadeds():
    # a loaded sleeve absent from capcfg.names must NOT trade (names is authoritative)
    spy = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    extra = _synthetic_loaded(spot=100.0, iv=0.50, z=2.0)
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0, names=("SPY",))
    res = simulate_account({"SPY": spy, "ZZZ": extra}, _settings(), cfg)
    assert {r.name for r in res.rungs} == {"SPY"}  # ZZZ ignored despite being passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k simulate -v`
Expected: FAIL with `ImportError: cannot import name 'simulate_account'`.

- [ ] **Step 3: Implement the ledger**

Append to `src/uw_scan/reports/vrp_capital_account.py` (add the imports to the existing import block at the top of the file):

```python
# --- add to the import block at the top of the module ---
from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_macro_harvest import _settle
from uw_scan.reports.vrp_macro_signal import size_weight
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread
```

```python
# --- append after desired_contracts ---


@dataclass(frozen=True)
class Rung:
    name: str
    entry_date: _date
    exit_date: _date
    contracts: int
    margin: float
    net_pnl: float
    breached: bool


@dataclass
class AccountResult:
    rungs: list[Rung]
    monthly_excess: dict[tuple[int, int], float]
    util_by_date: list[tuple[_date, float]]
    n_desired_rungs: int
    n_skipped_rungs: int
    contracts_desired_total: int
    contracts_filled_total: int
    span: tuple[_date, _date]


def _cost_model(settings) -> CostModel:
    return CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )


def simulate_account(
    loadeds: dict[str, _Loaded], settings, capcfg: CapitalConfig
) -> AccountResult:
    """Event-driven shared-$50k ledger. See module docstring + plan Task 3 semantics."""
    cfg = capcfg.base_cfg
    cost = _cost_model(settings)
    r = settings.vrp_risk_free_rate
    hold = cfg.hold_days

    # per-name lookups — capcfg.names is authoritative (KeyError if a name is missing
    # from loadeds, which is the correct loud failure; extra loadeds keys are ignored).
    iv_maps = {nm: {row["market_date"]: row["iv"] for row in loadeds[nm].rows} for nm in capcfg.names}
    z_maps = {nm: {row["market_date"]: row["vrp_z_20"] for row in loadeds[nm].rows} for nm in capcfg.names}

    # 1. candidate weekly entries across names. Same-date entries are economically
    # simultaneous; rotate their order by date ordinal so no name is systematically
    # first to consume shared buying power (plain alphabetical would bias, e.g. always
    # filling IWM/QQQ before SPY when capital binds). Rotation is unbiased on average.
    name_pos = {nm: i for i, nm in enumerate(capcfg.names)}
    k_names = max(1, len(capcfg.names))
    candidates: list[tuple[_date, str, int]] = []
    for nm in capcfg.names:
        ld = loadeds[nm]
        n = len(ld.adj)
        for pi in range(0, max(0, n - hold), cfg.cadence):
            d = ld.adj[pi][0]
            if capcfg.min_date and d < capcfg.min_date:
                continue
            candidates.append((d, nm, pi))
    candidates.sort(key=lambda c: (c[0], (name_pos[c[1]] + c[0].toordinal()) % k_names))

    # 2. simulate
    opened: list[tuple[_date, _date, float]] = []  # (entry, exit, margin) for utilisation + cap
    rungs: list[Rung] = []
    monthly: dict[tuple[int, int], float] = defaultdict(float)
    n_desired = n_skipped = desired_tot = filled_tot = 0

    for d, nm, pi in candidates:
        ld = loadeds[nm]
        iv = iv_maps[nm].get(d)
        s0 = ld.adj[pi][1]
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        z = z_maps[nm].get(d)
        w = size_weight(z, cfg)
        try:
            st = build_bull_put_spread(
                s0, float(iv), hold / 252.0, r,
                short_delta=cfg.short_delta, wing_delta=cfg.wing_delta,
            )
        except ValueError as exc:  # degenerate strikes
            log.debug("bull-put build skipped %s %s: %s", nm, d, repr(exc))
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        base_d, overlay_d = desired_contracts(w, z, mlpc, capcfg)
        total_d = base_d + overlay_d
        if total_d <= 0:
            continue
        n_desired += 1
        desired_tot += total_d
        exit_date = ld.adj[pi + hold][0]
        deployed = sum(m for (_e, xd, m) in opened if xd > d)
        available = capcfg.capital - deployed
        affordable = math.floor(available / mlpc) if mlpc > 0 else 0
        actual = min(total_d, max(0, affordable))
        if actual <= 0:
            n_skipped += 1
            log.debug("capital-skip %s %s: desired=%d available=%.0f mlpc=%.0f", nm, d, total_d, available, mlpc)
            continue
        if actual < total_d:
            log.debug("capital-partial %s %s: filled=%d/%d", nm, d, actual, total_d)
        filled_tot += actual
        net, _ror, breached, x_d, _x_spot = _settle(
            st, pi, hold, ld.adj, iv_maps[nm], r, cost=cost, contracts=actual
        )
        margin = mlpc * actual
        monthly[(x_d.year, x_d.month)] += net / capcfg.capital
        opened.append((d, exit_date, margin))
        rungs.append(Rung(nm, d, exit_date, actual, margin, net, bool(breached)))

    # 3. daily utilisation over the union of trading dates on [first_entry, last_exit).
    # Exposure is [entry, exit) so margin is already 0 on last_exit — exclude it (dd >=
    # last_exit) rather than appending a spurious zero point that would dilute util_mean.
    all_dates = sorted({dd for nm in capcfg.names for dd, _ in loadeds[nm].adj})
    lo = capcfg.min_date or (all_dates[0] if all_dates else None)
    util_by_date: list[tuple[_date, float]] = []
    if rungs and lo is not None:
        last_exit = max(r_.exit_date for r_ in rungs)
        for dd in all_dates:
            if dd < lo or dd >= last_exit:
                continue
            deployed = sum(m for (e, xd, m) in opened if e <= dd < xd)
            util_by_date.append((dd, deployed / capcfg.capital))

    if rungs:
        span = (min(r_.entry_date for r_ in rungs), max(r_.exit_date for r_ in rungs))
    else:
        span = (lo or _date(1970, 1, 1), lo or _date(1970, 1, 1))

    return AccountResult(
        rungs=rungs,
        monthly_excess=dict(monthly),
        util_by_date=util_by_date,
        n_desired_rungs=n_desired,
        n_skipped_rungs=n_skipped,
        contracts_desired_total=desired_tot,
        contracts_filled_total=filled_tot,
        span=span,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k simulate -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): event-driven shared-\$50k ledger (simulate_account)"
```

---

### Task 4: account_metrics (annualised return, utilisation, Sharpe, maxDD)

**Files:**
- Modify: `src/uw_scan/reports/vrp_capital_account.py`
- Test: `tests/unit/reports/test_vrp_capital_account.py`

**Interfaces:**
- Consumes: `AccountResult`, `CapitalConfig` from this module; `settings.vrp_risk_free_rate`.
- Produces: `account_metrics(res: AccountResult, capcfg: CapitalConfig, rf: float) -> dict[str, float|int]` with keys: `n_rungs`, `n_skipped_rungs`, `skip_rate`, `contracts_desired_total`, `contracts_filled_total`, `fill_rate`, `total_return_excess`, `years`, `ann_return_excess` (arithmetic mean monthly ×12), `ann_return_gross` (arithmetic + rf), `cagr_excess` (geometric-equivalent harvest), `cagr_gross` (geometric, rf-compounded), `sharpe`, `maxdd_dollars`, `maxdd_pct`, `util_mean`, `util_peak`, `win_rate`, `breach_rate`. Helper `_contiguous_monthly(monthly) -> list[float]` (zero-filled month span) is internal.

**Formula reference (lock these):**
- contiguous monthly series = `monthly_excess` zero-filled across its `(y,m)` span (same construction as `vrp_macro_signal._sharpe_maxdd`).
- `sharpe = mean(series) / pstdev(series) × sqrt(12)` (NaN if `sd == 0`).
- `years = len(series) / 12` (the return-accrual window — keeps arithmetic and geometric annualisations on one horizon).
- `total_return_excess = sum(monthly_excess.values())`.
- **Arithmetic** (primary, constant-base non-compounding): `ann_return_excess = mean(series) × 12`; `ann_return_gross = ann_return_excess + rf`.
- **Geometric-equivalent** (secondary): `cagr_excess = (1 + total_return_excess)^(1/years) − 1`; `gross_total = (1+rf)^years − 1 + total_return_excess`, `cagr_gross = (1 + gross_total)^(1/years) − 1`. Both NaN-guard `years <= 0` or non-positive base.
- `maxdd_dollars` = min of `(cum − running_peak)` over the cumulative **dollar** P&L curve (`series × capital`); `maxdd_pct = maxdd_dollars / capital`.
- `util_mean`/`util_peak` = mean/max of `util_by_date` values (0.0 if empty).
- `win_rate` = `#{rungs: net_pnl > 0} / n_rungs`; `breach_rate` = `#{rungs: breached} / n_rungs`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/reports/test_vrp_capital_account.py  (append)
from uw_scan.reports.vrp_capital_account import account_metrics, Rung, AccountResult


def test_account_metrics_handcomputed_returns():
    # two months: +1% then -0.5% of $50k → mean 0.25%/mo → ann excess 3%, gross 7% (rf 4%)
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 500.0, False),
            Rung("SPY", date(2020, 2, 3), date(2020, 2, 28), 1, 1000.0, -250.0, True),
        ],
        monthly_excess={(2020, 1): 0.01, (2020, 2): -0.005},
        util_by_date=[(date(2020, 1, 6), 0.02), (date(2020, 1, 7), 0.04)],
        n_desired_rungs=2, n_skipped_rungs=0,
        contracts_desired_total=2, contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert m["n_rungs"] == 2
    assert abs(m["ann_return_excess"] - 0.03) < 1e-9      # 0.0025 * 12
    assert abs(m["ann_return_gross"] - 0.07) < 1e-9
    assert abs(m["total_return_excess"] - 0.005) < 1e-9
    assert abs(m["win_rate"] - 0.5) < 1e-9
    assert abs(m["breach_rate"] - 0.5) < 1e-9
    assert abs(m["util_peak"] - 0.04) < 1e-9
    assert abs(m["util_mean"] - 0.03) < 1e-9


def test_account_metrics_maxdd_dollars():
    # +$1000 then -$1500 of P&L on $50k → peak +0.02, trough +0.02-0.03 → maxdd -0.03*50000 = -1500
    res = AccountResult(
        rungs=[Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 1000.0, False)],
        monthly_excess={(2020, 1): 0.02, (2020, 2): -0.03},
        util_by_date=[],
        n_desired_rungs=1, n_skipped_rungs=0,
        contracts_desired_total=1, contracts_filled_total=1,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["maxdd_dollars"] + 1500.0) < 1e-6
    assert abs(m["maxdd_pct"] + 0.03) < 1e-9


def test_account_metrics_cagr_geometric():
    # series [+1%, -0.5%] over 2 months → years=2/12, total_excess=0.005.
    # cagr_excess = 1.005^(12/2) - 1; gross adds rf-compounded cash over 1/6 year.
    res = AccountResult(
        rungs=[Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 500.0, False)],
        monthly_excess={(2020, 1): 0.01, (2020, 2): -0.005},
        util_by_date=[],
        n_desired_rungs=2, n_skipped_rungs=0,
        contracts_desired_total=2, contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["years"] - 2 / 12) < 1e-12
    assert abs(m["cagr_excess"] - (1.005 ** (12 / 2) - 1)) < 1e-9
    gross_total = (1.04) ** (2 / 12) - 1 + 0.005
    assert abs(m["cagr_gross"] - ((1 + gross_total) ** (12 / 2) - 1)) < 1e-9


def test_account_metrics_skip_and_fill_rates():
    res = AccountResult(
        rungs=[Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 10.0, False)],
        monthly_excess={(2020, 1): 0.0002},
        util_by_date=[(date(2020, 1, 6), 0.02)],
        n_desired_rungs=4, n_skipped_rungs=1,
        contracts_desired_total=10, contracts_filled_total=6,
        span=(date(2020, 1, 6), date(2020, 1, 31)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["skip_rate"] - 0.25) < 1e-9
    assert abs(m["fill_rate"] - 0.6) < 1e-9


def test_account_metrics_zero_fills_gap_months():
    # Jan +2%, (Feb empty), Mar +2% → contiguous series [0.02, 0.0, 0.02] over 3 months.
    # mean = 0.0133.. → ann excess 0.16; the empty Feb must be zero-filled, not dropped,
    # or Sharpe/maxDD would be wrong.
    res = AccountResult(
        rungs=[Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 1000.0, False)],
        monthly_excess={(2020, 1): 0.02, (2020, 3): 0.02},
        util_by_date=[],
        n_desired_rungs=2, n_skipped_rungs=0,
        contracts_desired_total=2, contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 3, 31)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["ann_return_excess"] - (0.04 / 3 * 12)) < 1e-9   # mean of [.02,0,.02]=.0133*12
    assert abs(m["total_return_excess"] - 0.04) < 1e-9
    assert m["maxdd_dollars"] <= 0.0   # monotone-up curve → no drawdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k account_metrics -v`
Expected: FAIL with `ImportError: cannot import name 'account_metrics'`.

- [ ] **Step 3: Implement metrics**

Append to `src/uw_scan/reports/vrp_capital_account.py` (add `from statistics import fmean, pstdev` and `from math import sqrt` to the import block):

```python
# --- add to the import block ---
from math import sqrt
from statistics import fmean, pstdev
```

```python
# --- append after simulate_account ---


def _contiguous_monthly(monthly: dict[tuple[int, int], float]) -> list[float]:
    """Zero-fill the contiguous (year, month) span — matches vrp_macro_signal._sharpe_maxdd."""
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series: list[float] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        series.append(monthly.get((y, m), 0.0))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return series


def account_metrics(res: AccountResult, capcfg: CapitalConfig, rf: float) -> dict:
    """Headline metrics on the $50k account. Excess = P&L only (rf earned on the cash);
    gross = excess + rf. See plan Task 4 formula reference."""
    series = _contiguous_monthly(res.monthly_excess)
    n_rungs = len(res.rungs)
    sd = pstdev(series) if len(series) > 1 else 0.0
    mean_m = fmean(series) if series else 0.0
    sharpe = (mean_m / sd * sqrt(12)) if sd > 0 else float("nan")
    # max drawdown on the cumulative dollar P&L curve
    cum = peak = mdd = 0.0
    for x in series:
        cum += x * capcfg.capital
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    util_vals = [u for _, u in res.util_by_date]
    # years basis = the return-accrual window (zero-filled month span / 12), so the
    # arithmetic and geometric annualisations share one consistent horizon (Gemini-4).
    years = len(series) / 12.0 if series else 0.0
    total_excess = sum(res.monthly_excess.values())

    def _cagr(total: float, yrs: float) -> float:
        base = 1.0 + total
        return base ** (1.0 / yrs) - 1.0 if (yrs > 0 and base > 0) else float("nan")

    # excess CAGR = geometric-equivalent of the cumulative option harvest on the constant
    # base; gross adds rf compounding on the cash sleeve over the same horizon.
    cagr_excess = _cagr(total_excess, years)
    gross_total = ((1.0 + rf) ** years - 1.0 + total_excess) if years > 0 else 0.0
    cagr_gross = _cagr(gross_total, years)
    return {
        "n_rungs": n_rungs,
        "n_skipped_rungs": res.n_skipped_rungs,
        "skip_rate": (res.n_skipped_rungs / res.n_desired_rungs) if res.n_desired_rungs else 0.0,
        "contracts_desired_total": res.contracts_desired_total,
        "contracts_filled_total": res.contracts_filled_total,
        "fill_rate": (res.contracts_filled_total / res.contracts_desired_total) if res.contracts_desired_total else 0.0,
        "total_return_excess": total_excess,
        "years": years,
        "ann_return_excess": mean_m * 12,          # arithmetic (mean monthly × 12)
        "ann_return_gross": mean_m * 12 + rf,       # arithmetic + rf on cash
        "cagr_excess": cagr_excess,                 # geometric-equivalent harvest
        "cagr_gross": cagr_gross,                   # geometric, rf-compounded cash + harvest
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capcfg.capital if capcfg.capital else 0.0,
        "util_mean": fmean(util_vals) if util_vals else 0.0,
        "util_peak": max(util_vals) if util_vals else 0.0,
        "win_rate": (sum(1 for r_ in res.rungs if r_.net_pnl > 0) / n_rungs) if n_rungs else 0.0,
        "breach_rate": (sum(1 for r_ in res.rungs if r_.breached) / n_rungs) if n_rungs else 0.0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -v`
Expected: PASS (all unit tests in the file).

- [ ] **Step 5: Confirm module stays under budget + commit**

Run: `wc -l src/uw_scan/reports/vrp_capital_account.py` (expect < 500).

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): account_metrics — annualised return, utilisation, Sharpe, maxDD"
```

---

### Task 5: Sweep runner + full-trace CSV + engine reconciliation

**Files:**
- Create: `scripts/research/vrp_capital_sweep.py`
- Create (by running it): `docs/research/vrp/capital-sweep-results.csv`
- Test: `tests/integration/reports/test_vrp_capital_account_db.py`

**Interfaces:**
- Consumes: `Settings.from_env`, `Repository`, `load_index_vol`, `CapitalConfig`, `simulate_account`, `account_metrics`; `backtest_laddered`, `WINNER` (reconciliation only).
- Produces: a `main()` that loads SPY/QQQ/IWM once, sweeps `base_risk_pct × overlay_mult × rich_threshold` (plus base-only baselines), writes every `(config × every metric)` row to the CSV, and prints the frontier + a reconciliation line. Module-level `SWEEP_BASE_RISK_PCT`, `SWEEP_OVERLAY_MULT`, `SWEEP_RICH_THRESHOLD`, `COMMON_START = date(2009, 1, 1)`.

**Reconciliation (correctness anchor):** a single-name (SPX), uncapped (`capital` huge), base-only (`overlay_mult=0`), full-size (`base_risk_pct` large so `w=1` always floors to many contracts) ledger run must produce a monthly-return **Sharpe within ±0.15 of `backtest_laddered`'s** Sharpe for SPX. This proves the dollar ledger did not silently diverge from the validated ROR engine (both settle the same rungs via `_settle`; per-contract scaling cancels in the Sharpe ratio).

- [ ] **Step 1: Write the failing reconciliation test (DB-gated)**

```python
# tests/integration/reports/test_vrp_capital_account_db.py
"""Real-data checks for the $50k ledger. Reads option_wizard_local + the lake.
Run: UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
     UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x uv run pytest \
     tests/integration/reports/test_vrp_capital_account_db.py -v
"""
from __future__ import annotations

import os
from datetime import date

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, backtest_laddered
from uw_scan.storage.repository import Repository

pytestmark = pytest.mark.integration

_HAVE_DB = os.environ.get("UW_SCAN_DB_HOST") and os.environ.get("UW_SCAN_DB_NAME")


@pytest.fixture
def repo_settings():
    if not _HAVE_DB:
        pytest.skip("needs UW_SCAN_DB_HOST/NAME pointing at a vol_index_daily DB")
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema), settings
    finally:
        conn.close()


def test_spy_loads_from_real_data(repo_settings):
    repo, _ = repo_settings
    loaded = load_index_vol(repo, "SPY")
    assert len(loaded.adj) > 2000           # ~2006→ daily bars
    assert any(r["vrp_z_20"] is not None for r in loaded.rows)


def test_dollar_ledger_reconciles_with_backtest_laddered(repo_settings):
    repo, settings = repo_settings
    loaded = load_index_vol(repo, "SPX")
    engine = backtest_laddered(loaded, settings, WINNER, min_date=date(2009, 1, 1))
    # TRULY uncapped: base_risk_pct=0.05 × ~6 overlapping rungs = ~30% peak ≪ 100%, so
    # NOTHING is ever skipped or partial-filled (the constant-multiple proof needs the
    # identical rung set the engine uses). Capital=1e9 makes w=1 floor to ~10^5 contracts
    # → integer-floor noise ≪ the 0.15 tolerance. overlay off, rich_threshold unreachable.
    cfg = CapitalConfig(
        capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
        rich_threshold=99.0, names=("SPX",), min_date=date(2009, 1, 1),
    )
    res = simulate_account({"SPX": loaded}, settings, cfg)
    m = account_metrics(res, cfg, settings.vrp_risk_free_rate)
    assert res.n_skipped_rungs == 0                 # genuinely uncapped → no skips
    assert m["util_peak"] < 0.90                    # confirms capital never bound
    assert abs(m["sharpe"] - engine["sharpe"]) < 0.15
```

- [ ] **Step 2: Run to verify it fails (no runner/module path yet, or skip without DB)**

Run: `uv run pytest tests/integration/reports/test_vrp_capital_account_db.py -v`
Expected: with DB env set → FAIL only if the ledger diverges; without DB env → SKIP. (At this point the module exists from Tasks 2–4, so the import resolves; the test is the live correctness gate.)

- [ ] **Step 3: Write the runner**

```python
# scripts/research/vrp_capital_sweep.py
"""Two-layer macro short-vol on ONE shared $50k account — capital-utilisation sweep.

Strategy:
  BASE    = the deployed winner (reports/vrp_macro_signal.WINNER): bull put spread,
            0.25Δ / 0.125Δ wing, ~30 trading-day hold, weekly entry, ramp+ vrp-z
            sizing, held to expiry. SPX 20-yr monthly-ROR Sharpe ≈ 1.65.
  OVERLAY = binary: when vrp_z >= rich_threshold, sell `overlay_mult` extra sets of
            the same spread.
Account: $50,000 shared across SPY/QQQ/IWM; integer contracts floored to a risk-% of
$50k; a rung opens only if its margin fits the remaining buying power (else skipped,
logged). Idle cash earns rf (4%) → reported P&L is excess; gross = excess + rf.

Pricing/loaders are REUSED unchanged (flat-vol BS; VIX/VXN/RVX + equity lake). Flat-vol
ignores skew → the put-spread credit is a conservative floor (real fills ≥ modeled).

Persists the FULL result set to docs/research/vrp/capital-sweep-results.csv (every config
× every metric). Deterministic — no RNG.

Run (MacBook local, reads option_wizard_local + the lake):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_capital_sweep.py
"""
from __future__ import annotations

import csv
import pathlib
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, backtest_laddered
from uw_scan.storage.repository import Repository

NAMES = ("SPY", "QQQ", "IWM")
# VXN (2009-09-14) / RVX (2009-09-16) gate the QQQ/IWM sleeves; with the 252-day
# vrp-z warmup the first QQQ/IWM rung is ~Sep 2010. SPY (VIX, from 2006) trades
# earlier. min_date filters entries; the true span is read from the result.
COMMON_START = date(2009, 1, 1)
CAPITAL = 50_000.0

SWEEP_BASE_RISK_PCT = (0.03, 0.05, 0.08, 0.10)
SWEEP_OVERLAY_MULT = (1.0, 2.0)
SWEEP_RICH_THRESHOLD = (0.5, 1.0, 1.5)

OUT_CSV = pathlib.Path("docs/research/vrp/capital-sweep-results.csv")

_FIELDS = [
    "base_risk_pct", "overlay_mult", "rich_threshold", "overlay_enabled",
    "n_rungs", "n_skipped_rungs", "skip_rate",
    "contracts_desired_total", "contracts_filled_total", "fill_rate",
    "total_return_excess", "years",
    "ann_return_excess", "ann_return_gross", "cagr_excess", "cagr_gross",
    "sharpe", "maxdd_dollars", "maxdd_pct", "util_mean", "util_peak",
    "win_rate", "breach_rate",
]


def _row(capcfg: CapitalConfig, overlay_enabled: bool, m: dict) -> dict:
    return {
        "base_risk_pct": capcfg.base_risk_pct,
        "overlay_mult": capcfg.overlay_mult if overlay_enabled else 0.0,
        "rich_threshold": capcfg.rich_threshold,
        "overlay_enabled": int(overlay_enabled),
        **{k: m[k] for k in _FIELDS if k in m},
    }


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    rf = settings.vrp_risk_free_rate
    try:
        loadeds = {nm: load_index_vol(repo, nm) for nm in NAMES}

        # reconciliation: SPX TRULY-uncapped base-only ledger Sharpe vs backtest_laddered
        # (capital=1e9, base_risk_pct=0.05 → ~30% peak, no skips; huge N → floor noise ≪ 0.15)
        spx = load_index_vol(repo, "SPX")
        eng = backtest_laddered(spx, settings, WINNER, min_date=COMMON_START)
        recon_cfg = CapitalConfig(
            capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
            rich_threshold=99.0, names=("SPX",), min_date=COMMON_START,
        )
        recon = account_metrics(simulate_account({"SPX": spx}, settings, recon_cfg), recon_cfg, rf)
        print(
            f"RECONCILE SPX base-only uncapped: ledger Sharpe {recon['sharpe']:.3f} "
            f"vs backtest_laddered {eng['sharpe']:.3f} (Δ {abs(recon['sharpe'] - eng['sharpe']):.3f}); "
            f"skipped={recon['n_skipped_rungs']} util_peak={recon['util_peak']:.3f}\n"
        )

        rows: list[dict] = []
        # base-only baselines (one per base_risk_pct; overlay disabled)
        for brp in SWEEP_BASE_RISK_PCT:
            cfg = CapitalConfig(
                capital=CAPITAL, base_risk_pct=brp, overlay_mult=0.0,
                rich_threshold=99.0, names=NAMES, min_date=COMMON_START,
            )
            m = account_metrics(simulate_account(loadeds, settings, cfg), cfg, rf)
            rows.append(_row(cfg, overlay_enabled=False, m=m))

        # base + overlay grid
        for brp in SWEEP_BASE_RISK_PCT:
            for omult in SWEEP_OVERLAY_MULT:
                for rt in SWEEP_RICH_THRESHOLD:
                    cfg = CapitalConfig(
                        capital=CAPITAL, base_risk_pct=brp, overlay_mult=omult,
                        rich_threshold=rt, names=NAMES, min_date=COMMON_START,
                    )
                    m = account_metrics(simulate_account(loadeds, settings, cfg), cfg, rf)
                    rows.append(_row(cfg, overlay_enabled=True, m=m))

        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with OUT_CSV.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows → {OUT_CSV}\n")

        # headline frontier: top 8 base+overlay by ann_return_gross
        bo = sorted([r for r in rows if r["overlay_enabled"]], key=lambda r: -r["ann_return_gross"])[:8]
        print(f"{'brp':>5}{'omlt':>6}{'rich':>6}{'annGross':>10}{'sharpe':>8}{'maxDD%':>8}{'util_avg':>9}{'util_pk':>8}{'skip%':>7}")
        for r in bo:
            print(
                f"{r['base_risk_pct']:>5.2f}{r['overlay_mult']:>6.1f}{r['rich_threshold']:>6.1f}"
                f"{r['ann_return_gross']:>10.3f}{r['sharpe']:>8.2f}{r['maxdd_pct']:>8.3f}"
                f"{r['util_mean']:>9.3f}{r['util_peak']:>8.3f}{r['skip_rate']:>7.2f}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the sweep on real data**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
uv run python scripts/research/vrp_capital_sweep.py
```
Expected: a `RECONCILE …` line with `Δ < 0.15`, `wrote 28 rows → docs/research/vrp/capital-sweep-results.csv`, and the headline frontier table. If `Δ >= 0.15`, STOP — the ledger diverges from the validated engine; debug before trusting any number.

- [ ] **Step 5: Run the reconciliation test against real data**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
uv run pytest tests/integration/reports/test_vrp_capital_account_db.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/research/vrp_capital_sweep.py tests/integration/reports/test_vrp_capital_account_db.py docs/research/vrp/capital-sweep-results.csv
git commit -m "feat(vrp): \$50k capital-utilisation sweep runner + full-trace CSV + engine reconciliation"
```

---

### Task 6: Findings notebook + verdict markdown

**Files:**
- Create: `scripts/_build_vrp_capital_notebook.py`
- Create (by running it): `docs/research/vrp/macro-capital-utilisation-findings.ipynb`
- Create: `docs/research/vrp/macro-capital-utilisation-verdict.md`

**Interfaces:**
- Consumes: `docs/research/vrp/capital-sweep-results.csv` (from Task 5).
- Produces: a notebook that loads the CSV and renders the frontier + base-only-vs-overlay comparison, and a verdict doc citing the headline numbers (filled in from the real CSV — no placeholders).

- [ ] **Step 1: Write the notebook builder (mirrors scripts/_build_vrp_macro_notebook.py)**

```python
# scripts/_build_vrp_capital_notebook.py
"""Throwaway builder for docs/research/vrp/macro-capital-utilisation-findings.ipynb.
Reads docs/research/vrp/capital-sweep-results.csv. Run:
  uv run python scripts/_build_vrp_capital_notebook.py
"""
from __future__ import annotations

import json
import pathlib

OUT = pathlib.Path("docs/research/vrp/macro-capital-utilisation-findings.ipynb")


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code(src: str) -> dict:
    return {
        "cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
        "source": src.splitlines(keepends=True),
    }


def main() -> None:
    cells = [
        _md(
            "# Macro Short-Vol — Two-Layer $50k Capital-Utilisation Study\n\n"
            "Base = deployed WINNER (ramp+ vrp-z-sized bull put spread, Sharpe ≈1.65). "
            "Overlay = binary extra set when `vrp_z >= rich_threshold`. One shared $50k "
            "across SPY/QQQ/IWM. Full results: `capital-sweep-results.csv`.\n"
        ),
        _code(
            "import pandas as pd\n"
            "df = pd.read_csv('capital-sweep-results.csv')\n"
            "df\n"
        ),
        _md("## Base-only baselines (overlay disabled)\n"),
        _code("df[df.overlay_enabled == 0].sort_values('ann_return_gross', ascending=False)\n"),
        _md("## Base + overlay — frontier by gross annualised return\n"),
        _code(
            "bo = df[df.overlay_enabled == 1].sort_values('ann_return_gross', ascending=False)\n"
            "bo[['base_risk_pct','overlay_mult','rich_threshold','ann_return_gross','cagr_gross',"
            "'sharpe','maxdd_pct','util_mean','util_peak','skip_rate']].head(12)\n"
        ),
        _md(
            "## Does the overlay earn its capital?\n\n"
            "Compare each base+overlay cell against its base-only sibling at the same "
            "`base_risk_pct`: Δ ann_return_gross vs Δ utilisation vs Δ maxDD.\n"
        ),
        _code(
            "base = df[df.overlay_enabled == 0].set_index('base_risk_pct')\n"
            "rows = []\n"
            "for _, r in df[df.overlay_enabled == 1].iterrows():\n"
            "    b = base.loc[r.base_risk_pct]\n"
            "    rows.append({'base_risk_pct': r.base_risk_pct, 'overlay_mult': r.overlay_mult,\n"
            "        'rich_threshold': r.rich_threshold,\n"
            "        'd_ann_gross': r.ann_return_gross - b.ann_return_gross,\n"
            "        'd_util_mean': r.util_mean - b.util_mean,\n"
            "        'd_maxdd_pct': r.maxdd_pct - b.maxdd_pct,\n"
            "        'd_sharpe': r.sharpe - b.sharpe})\n"
            "pd.DataFrame(rows).sort_values('d_ann_gross', ascending=False)\n"
        ),
    ]
    nb = {
        "cells": cells,
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(nb, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Build the notebook**

Run: `uv run python scripts/_build_vrp_capital_notebook.py`
Expected: `wrote docs/research/vrp/macro-capital-utilisation-findings.ipynb`.

- [ ] **Step 3: Write the verdict doc from the REAL CSV numbers**

Open `docs/research/vrp/capital-sweep-results.csv` and the runner's printed frontier. Create `docs/research/vrp/macro-capital-utilisation-verdict.md` filling every bracketed value from the actual results (no placeholders left):

```markdown
# Macro Short-Vol — Two-Layer $50k Capital-Utilisation Verdict (2026-06-23)

**Question.** Run the deployed Sharpe-1.65 macro short-vol winner as an always-eligible
**base** (ramp+ vrp-z-sized bull put spread) plus a **binary overlay** (extra set when
`vrp_z >= rich_threshold`) on ONE shared **$50,000** account across SPY/QQQ/IWM. What is
the annualised return, and how hard does the capital work?

**Method.** New dollar ledger `reports/vrp_capital_account.py` (reuses the validated
flat-vol pricing + `_settle` + `load_index_vol` + `WINNER` sizing). Integer contracts
floored to a risk-% of $50k; a rung opens only if its margin fits remaining buying power
(else skipped, logged). Idle cash earns rf 4% → P&L is excess, gross = excess + rf.
Window: `min_date` 2009-01-01, but VXN/RVX begin 2009-09 and a 252-day vrp-z warmup
delays the first QQQ/IWM rung to ~Sep 2010 — `<START>`→`<END>` is the TRUE span read
from the result (SPY trades from ~2007). Reproduce:
`uv run python scripts/research/vrp_capital_sweep.py`. Full trace:
`capital-sweep-results.csv`. Reconciliation: SPX base-only uncapped ledger Sharpe
<RECON_LEDGER> vs `backtest_laddered` <RECON_ENGINE> (Δ <RECON_DELTA>).

## Headline

- **Best base+overlay cell:** base_risk_pct <BRP>, overlay_mult <OMULT>, rich_threshold
  <RT> → **gross annualised <ANN_GROSS>** (arith; excess <ANN_EXCESS>; geometric CAGR
  gross <CAGR_GROSS>), Sharpe <SHARPE>, maxDD <MAXDD_PCT> of $50k, mean utilisation
  <UTIL_MEAN>, peak <UTIL_PEAK>, skip-rate <SKIP>.
- **Best base-only cell:** base_risk_pct <B_BRP> → gross annualised <B_ANN_GROSS> (CAGR
  <B_CAGR_GROSS>), Sharpe <B_SHARPE>, mean utilisation <B_UTIL_MEAN>.
- **Does the overlay earn its capital?** <one paragraph: Δ gross return vs Δ utilisation
  vs Δ maxDD — is the extra set additive edge or just leverage of the same bet>.
- **Capital utilisation reality:** the ramp+ base sits idle (rf only) when vol is cheap,
  so mean utilisation is <UTIL_MEAN> — the $50k is <interpretation>. Skip-rate <SKIP>
  flags how often $50k was too small for the desired size.

## Caveats

- Flat-vol BS ignores skew → the put-spread credit is a conservative floor (real fills ≥
  modeled). No real-fill NBBO yet.
- Two return views: arithmetic `ann_return_*` (mean monthly × 12, constant non-compounding
  base) and geometric `cagr_*` (in the CSV). Quote both; they differ.
- Same-date entries rotate priority by date (no alphabetical bias); when $50k binds, the
  skip lands unbiased-on-average across names, not pro-rata — per-name attribution is
  therefore noisy by design (see `skip_rate`).
- Capital frees at expiry (same-day reuse); T+1 settlement not modeled → slightly
  optimistic on expiry-day entries.
- `skip_rate` = fully-skipped rungs (couldn't afford 1 contract) ÷ desired rungs;
  `fill_rate` = contracts filled ÷ desired (captures partial fills). At low
  `base_risk_pct` a name whose one-contract margin exceeds the per-rung budget never
  trades at all (e.g. SPY ~$1.6k margin > 3%×$50k=$1500) — read the per-name rung
  counts; a name's absence is data, not a bug.
- SPX is reference-only (one contract ≈ $16k margin, too lumpy for $50k); the tradeable
  S&P vehicle here is SPY (same VIX-driven signal).
- Window: VXN/RVX begin 2009-09 + 252-day vrp-z warmup → the 3-name book reaches full
  breadth ~Sep 2010; SPY alone trades from ~2007. Includes 2011/2015/2018/2020/2022
  stress; **excludes 2008** (the worst tail) — a real limit on the drawdown read.
```

- [ ] **Step 4: Verify no placeholders remain**

Run: `grep -nE "<[A-Z_]+>|TBD|TODO|FIXME" docs/research/vrp/macro-capital-utilisation-verdict.md || echo "clean"`
Expected: `clean` (every angle-bracket value replaced with a real number from the CSV).

- [ ] **Step 5: Commit**

```bash
git add scripts/_build_vrp_capital_notebook.py docs/research/vrp/macro-capital-utilisation-findings.ipynb docs/research/vrp/macro-capital-utilisation-verdict.md
git commit -m "docs(vrp): \$50k capital-utilisation findings notebook + verdict"
```

---

## Self-Review

**1. Spec coverage** — every design element maps to a task:
- Two-layer strategy (ramp+ base + binary overlay) → Task 2 (`desired_contracts`) + Task 3 (`simulate_account`).
- Shared $50k, integer contracts, capital cap + logged skips → Task 3.
- SPY as the tradeable S&P vehicle → Task 1.
- Metrics (ann return gross/excess, Sharpe, maxDD $/%, utilisation mean/peak, skip-rate, fill-rate, win/breach, per-name implicit via `Rung.name`) → Task 4.
- Sweep axes (base_risk_pct × overlay_mult × rich_threshold) + base-only baselines → Task 5.
- Reuse-not-modify the validated engine; only additive INDEX_SPECS edit → Tasks 1–5 (imports), reconciliation in Task 5.
- Persist full trace → Task 5 CSV; notebook + verdict → Task 6.

**2. Placeholder scan** — the only intentional placeholders are the `<…>` tokens in the Task 6 verdict template, which Step 3 fills from the real CSV and Step 4 asserts are gone. No "TBD"/"handle edge cases" in code steps.

**3. Type consistency** — `desired_contracts(w, z, max_loss_per_contract, capcfg) -> (int,int)`, `simulate_account(loadeds, settings, capcfg) -> AccountResult`, `account_metrics(res, capcfg, rf) -> dict` are used identically in Tasks 2–6. `Rung`/`AccountResult` field names match between definition (Task 3) and use (Tasks 4–5). `CapitalConfig` field names (`base_risk_pct`, `overlay_mult`, `rich_threshold`, `min_date`, `base_cfg`) are stable across all tasks.

**Reconciliation soundness (resolved in review Pass 2):** the original config (`base_risk_pct=0.20`, capital `$50M`) was NOT uncapped — ~6 overlapping rungs × 20% = ~120% > 100%, so capital would bind and break both the `n_skipped==0` assert and the constant-multiple proof. Fixed: `base_risk_pct=0.05` × ~6 rungs = ~30% peak (genuinely uncapped, asserted via `util_peak < 0.90`), capital `$1e9` so `w=1` floors to ~10⁵ contracts (floor noise ≪ 0.15). With no skips/partials the ledger monthly series is `1.2 ×` the engine's `÷max_slots` series — a pure constant → identical Sharpe up to negligible floor noise.
```
