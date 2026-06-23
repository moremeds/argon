# VRP Backtest Iteration 4 — Robustness Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stress-test the deployed macro short-vol WINNER along five new axes — rich-vol extra position (contract-overlay vs staggered second tranche, each compounding + non-compounding), entry weekday, bear-market start date, and a seeded Monte-Carlo robustness suite — every result benchmarked against the iteration-3 SPX base case and SPY buy-and-hold.

**Architecture:** Extend the one validated `$50k` ledger (`reports/vrp_capital_account.py`) with six backward-compatible flags (compounding, entry-weekday, entry-jitter, staggered extra tranche) so all variants flow through one tested engine and reconcile to the current path when every flag is off. A new research-orchestration module (`reports/vrp_robustness.py`) holds the capital-sizing finder, the SPY buy-and-hold benchmark, the geometric compounding-metric helper, the weekday + bear-start studies, and the four Monte-Carlo drivers (all seeded with stdlib `random.Random`, no new deps). A seeded runner loads SPX/SPY from the mini DB, writes full-trace `iter4-*.csv`, and feeds a findings notebook + an Iteration-4 section of the master report.

**Tech Stack:** Python 3.13 via `uv`; stdlib `statistics`/`random`/`math` (no numpy/scipy in the new modules); pytest; matplotlib/nbconvert (existing `research` dependency group) for the notebook.

## Global Constraints

- **`uv` only** — every test/command is `uv run …`; never bare `python`/`pytest`.
- **SPX-only** experiments. SPY is used solely for the buy-and-hold benchmark line.
- **Defined-risk only** — bull put spreads (sell 0.25Δ / buy 0.125Δ wing). No naked shorts, no CSP in this iteration.
- **Two baselines on every experiment** — `baseline_iter3_spx` (SPX WINNER base case: weekly, ramp+, no extra position, non-compounding, at the floor capital, same span) and `baseline_spy_buyhold` (SPY buy-and-hold over the same span). Both appear as a reserved CSV row and a chart reference line.
- **Persist every trace** — each experiment writes its *full* result set (every config × every metric) to a committed `iter4-*.csv` under `docs/research/vrp/`, plus the exact reproduce command in the runner docstring. stdout-only is data loss.
- **Determinism** — every Monte-Carlo driver takes an explicit integer `seed`; same seed → identical output (asserted by a test).
- **Module size budget** — `vrp_capital_account.py` stays < 500 lines; if `vrp_robustness.py` approaches 500, split the MC drivers into `vrp_robustness_mc.py` (noted in Task 6).
- **Backward compatibility / reconciliation** — with all new `CapitalConfig` flags at their defaults, `simulate_account` must produce byte-identical `AccountResult` to today. A reconciliation test guards this.
- **Look-ahead discipline** — the signal is already leak-free (`vrp_z` trailing-252, `rv` trailing-20, IV contemporaneous). No new code may read a row dated after the entry day to make an entry/sizing decision. Compounding sizes off realised equity = `capital + Σ net of rungs whose exit_date ≤ entry_date` only.
- **Branch** — append all commits to the existing un-merged PR #162 branch `feat/vrp-capital-backtest` (per the standing "extend the pending branch, don't spawn a sibling" rule). No new PR off main.
- **Mini DB creds in-process only** — the runner reads env (`Settings.from_env()`); when run against the mini, env is sourced from `.env.local` in the shell; never print the password.
- **No `Co-Authored-By` / AI trailers** on commits.
- **All imports at the top of every file** (production and test). A later task that needs a new import **edits the top import block** (never places an `import` after code — ruff E402 blocks it). Each task imports only what it uses so its milestone commit is F401-clean. In the TDD test files, the failing-test step adds its symbol to the top import block; the import fails (RED) until that task's function is implemented.

## Design recap (what `/review-cycle` checks consistency against)

| # | Experiment | Mechanism | Basis | Output CSV |
|---|---|---|---|---|
| 0 | Min starting capital | `min_viable_capital` — SPX max-loss/contract → smallest `C0` that affords ≥1 spread, per start × risk-% | dollar | `iter4-min-capital.csv` |
| 1 | Extra position | base · +contract-overlay (`overlay_mult`) · +staggered-tranche (`extra_tranche`), × {non-comp, comp} | dollar @ floor `C0` | `iter4-extra-position.csv` |
| 2 | Entry weekday | `entry_weekday` ∈ {0..4} + default stride | uncapped (clean signal) + floor `C0` | `iter4-weekday.csv` |
| 3 | Bear start | `min_date` ∈ {2015-08-01, 2018-09-20, 2020-02-19, 2022-01-03}; full-path metrics + 6m/12m/36m forward return & maxDD + long-form equity path | dollar @ floor `C0` | `iter4-bear-start.csv` + `iter4-bear-start-path.csv` |
| 4 | Monte Carlo | entry-jitter · block-bootstrap (zero-filled series) · randomised-start (full **and** GFC-windowed = the #5 bear extension) · config-perturbation (all seeded) | uncapped | `iter4-mc.csv` (summary) + `iter4-mc-trials.csv` (per-trial) |

Key design decisions encoded below:
- **Staggered tranche ≠ contract overlay.** A same-day, same-strike second spread is arithmetically `+1` contract; to make "Both, side by side" a real comparison, the **extra tranche enters `extra_tranche_stagger` (=2) trading days after the base entry** on rich weeks (`z_base ≥ rich_threshold`), and is then sized by *its own* entry-day signal. The contract overlay (`overlay_mult`) remains the same-day leverage stack.
- **Two metric paths.** Non-compounding uses the validated `account_metrics` (linear, net ÷ initial capital). Compounding uses `equity_curve_metrics` on equity-relative returns (`E_t/E_{t-1}−1`). `account_metrics` is **not** modified.
- **Uncapped = clean-signal basis.** Running `simulate_account` with `capital=1e9` produces zero skips, so its Sharpe ≈ the capital-blind `backtest_laddered` (parent reconciliation Δ 0.000). The weekday sweep and MC drivers use the uncapped basis to isolate signal robustness from affordability; experiment 1 and 3 use the floor `C0` for the real-account read.

---

### Task 1: Compounding flag + `sizing_capital` threading on the ledger

**Files:**
- Modify: `src/uw_scan/reports/vrp_capital_account.py` (`CapitalConfig`, `desired_contracts`, `simulate_account`)
- Test: `tests/unit/reports/test_vrp_capital_account.py` (append)

**Interfaces:**
- Consumes: `_Loaded` (`adj: list[(date,float)]`, `rows: list[dict]` with `market_date`/`iv`/`vrp_z_20`), `_settle(st, pi, hold, adj, iv_map, r, *, cost, contracts) -> (net, ror, breached, exit_date, exit_spot)`, `build_bull_put_spread`, `size_weight`.
- Produces: `CapitalConfig` gains `compounding: bool = False`, `entry_weekday: int | None = None`, `entry_jitter: int = 0`, `jitter_seed: int = 0`, `extra_tranche: bool = False`, `extra_tranche_stagger: int = 2` (the last four are wired in Tasks 2–3, but ALL six are added to the dataclass now so the frozen contract is stable). `desired_contracts(w, z, max_loss_per_contract, capcfg, *, sizing_capital: float | None = None) -> tuple[int,int]`.

- [ ] **Step 1: Write the failing test — compounding sizes off realised equity**

Append to `tests/unit/reports/test_vrp_capital_account.py`:

```python
# --- Task 1 (iter4): compounding ------------------------------------------
def test_desired_contracts_sizing_capital_overrides_capital():
    # base sized off sizing_capital, not capcfg.capital: 5% of $100k / $1000 = floor(5)=5
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0)
    base, _ = desired_contracts(1.0, 0.4, 1000.0, cfg, sizing_capital=100_000.0)
    assert base == 5


def test_compounding_grows_position_after_wins(monkeypatch):
    # A flat, always-winning synthetic SPX: equity rises → compounding sizes bigger
    # later rungs than the fixed-capital book. Same data, two configs, compare contracts.
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=300)
    # 5% risk × ~6 concurrent weekly rungs = ~30% peak util → no capital cap, so the
    # only thing that grows later rungs is compounding off rising equity (clean signal).
    base = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                         rich_threshold=99.0, names=("SPX",), compounding=False)
    comp = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                         rich_threshold=99.0, names=("SPX",), compounding=True)
    rb = simulate_account({"SPX": ld}, _settings(), base)
    rc = simulate_account({"SPX": ld}, _settings(), comp)
    # if every rung is a net winner, compounding's last rung holds >= the fixed book's
    assert rc.rungs[-1].contracts >= rb.rungs[-1].contracts
    # and strictly more somewhere (equity actually compounded)
    assert sum(r.contracts for r in rc.rungs) > sum(r.contracts for r in rb.rungs)
```

(`_synthetic_loaded` and `_settings` already exist in this file. If `_synthetic_loaded` does not guarantee all-winning rungs, the test asserts `>=` on the last rung and `>` on the total — robust to a few losers.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k "sizing_capital or compounding_grows" -v`
Expected: FAIL — `desired_contracts() got an unexpected keyword argument 'sizing_capital'` / `CapitalConfig.__init__() got an unexpected keyword argument 'compounding'`.

- [ ] **Step 3: Add the six flags to `CapitalConfig`**

In `vrp_capital_account.py`, extend the dataclass (keep existing fields; append):

```python
@dataclass(frozen=True)
class CapitalConfig:
    capital: float = 50_000.0
    base_risk_pct: float = 0.05
    overlay_mult: float = 1.0
    rich_threshold: float = 1.0
    names: tuple[str, ...] = ("SPY", "QQQ", "IWM")
    min_date: _date | None = None
    base_cfg: MacroSignalConfig = WINNER
    # iter4 robustness flags — all default to the current (iteration-3) behavior
    compounding: bool = False        # size each entry off realised equity, not fixed capital
    entry_weekday: int | None = None # 0=Mon..4=Fri; None = 5-trading-day stride (Task 2)
    entry_jitter: int = 0            # ± trading-day jitter per entry; 0 = none (Task 2 / MC)
    jitter_seed: int = 0             # seeds the deterministic per-entry jitter
    extra_tranche: bool = False      # staggered second entry on rich weeks (Task 3)
    extra_tranche_stagger: int = 2   # trading days after base entry for the extra tranche

    def __post_init__(self) -> None:
        # loud guards (Codex ISSUE-10): a negative stagger would index backward / wrap,
        # a negative jitter is nonsense. Validation-only — safe on a frozen dataclass.
        if self.extra_tranche and self.extra_tranche_stagger < 1:
            raise ValueError("extra_tranche_stagger must be >= 1 when extra_tranche is on")
        if self.entry_jitter < 0:
            raise ValueError("entry_jitter must be >= 0")
```

- [ ] **Step 4: Thread `sizing_capital` through `desired_contracts`**

Replace the signature and the two `capcfg.capital` references inside:

```python
def desired_contracts(
    w: float, z: float | None, max_loss_per_contract: float, capcfg: CapitalConfig,
    *, sizing_capital: float | None = None,
) -> tuple[int, int]:
    """(base, overlay) integer contract counts before the shared-capital cap.
    `sizing_capital` (default capcfg.capital) is the equity the risk-% is taken
    against — the compounding path passes realised equity here."""
    cap = capcfg.capital if sizing_capital is None else sizing_capital
    if max_loss_per_contract <= 0:
        return 0, 0
    base = 0
    if w > 0:
        base = math.floor(w * capcfg.base_risk_pct * cap / max_loss_per_contract)
    overlay = 0
    if base >= 1 and z is not None and z >= capcfg.rich_threshold and capcfg.overlay_mult > 0:
        overlay = math.floor(
            capcfg.overlay_mult * capcfg.base_risk_pct * cap / max_loss_per_contract
        )
    return base, overlay
```

- [ ] **Step 5: Wire compounding into `simulate_account`**

In the main `for d, nm, pi in candidates:` loop of `simulate_account`, compute the sizing capital and use it for BOTH sizing and affordability. Replace the block from `base_d, overlay_d = desired_contracts(...)` through the `available` computation:

```python
        # compounding sizes off realised equity (capital + net of rungs already exited
        # on/before this entry date — no look-ahead; a rung's P&L is realised at exit).
        if capcfg.compounding:
            realised = capcfg.capital + sum(
                rg.net_pnl for rg in rungs if rg.exit_date <= d
            )
            sizing_cap = max(0.0, realised)
        else:
            sizing_cap = capcfg.capital
        base_d, overlay_d = desired_contracts(w, z, mlpc, capcfg, sizing_capital=sizing_cap)
        total_d = base_d + overlay_d
        if total_d <= 0:
            continue
        n_desired += 1
        desired_tot += total_d
        exit_date = ld.adj[pi + hold][0]
        deployed = sum(m for (_e, xd, m) in opened if xd > d)
        available = sizing_cap - deployed
```

(Everything below — `affordable`, `actual`, `_settle`, `monthly[...] += net / capcfg.capital`, `rungs.append(...)` — is unchanged. `monthly_excess` stays defined as net ÷ *initial* capital; the geometric compounding read is computed later by `equity_curve_metrics`, not here.)

- [ ] **Step 6: Run the new + existing ledger tests**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -v`
Expected: PASS — all prior tests still green (defaults unchanged) + the two new ones.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): add compounding + sizing_capital to the capital ledger (iter4 task1)"
```

---

### Task 2: Entry-weekday filter + per-entry jitter in candidate building

**Files:**
- Modify: `src/uw_scan/reports/vrp_capital_account.py` (`simulate_account` candidate-building block)
- Test: `tests/unit/reports/test_vrp_capital_account.py` (append)

**Interfaces:**
- Consumes: `CapitalConfig.entry_weekday`, `.entry_jitter`, `.jitter_seed` (added in Task 1).
- Produces: candidate entries selected by weekday (when set) instead of the 5-stride, each optionally shifted by a deterministic ± `entry_jitter` trading-day offset.

- [ ] **Step 1: Write the failing test**

```python
# --- Task 2 (iter4): weekday + jitter -------------------------------------
def test_entry_weekday_filters_to_one_weekday():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",), entry_weekday=2)  # Wednesday
    res = simulate_account({"SPX": ld}, _settings(), cfg)
    assert res.rungs
    assert all(r.entry_date.weekday() == 2 for r in res.rungs)


def test_entry_jitter_is_deterministic_for_a_seed():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",), entry_jitter=2, jitter_seed=7)
    a = simulate_account({"SPX": ld}, _settings(), cfg)
    b = simulate_account({"SPX": ld}, _settings(), cfg)
    assert [r.entry_date for r in a.rungs] == [r.entry_date for r in b.rungs]


def test_entry_jitter_zero_matches_plain_stride():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    plain = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                          rich_threshold=99.0, names=("SPX",))
    jit0 = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                         rich_threshold=99.0, names=("SPX",), entry_jitter=0, jitter_seed=7)
    assert [r.entry_date for r in simulate_account({"SPX": ld}, _settings(), plain).rungs] \
        == [r.entry_date for r in simulate_account({"SPX": ld}, _settings(), jit0).rungs]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k "weekday or jitter" -v`
Expected: FAIL — `entry_weekday=2` currently has no effect, so `test_entry_weekday_filters_to_one_weekday` fails (rungs land on the stride's weekday, not necessarily Wednesday).

- [ ] **Step 3: Add the module-level jitter helper**

Near the top of `vrp_capital_account.py` (after imports), add:

```python
import random as _random


def _entry_indices(ld, hold: int, capcfg: CapitalConfig, nm: str) -> list[int]:
    """Trading-day entry indices for one name. entry_weekday set → every day of that
    weekday (≈weekly spacing); else the cfg.cadence stride. entry_jitter>0 shifts each
    index by a deterministic per-(seed,name,index) offset in [-jitter, +jitter], clamped."""
    n = len(ld.adj)
    hi = max(0, n - hold)
    if capcfg.entry_weekday is not None:
        idxs = [pi for pi in range(hi) if ld.adj[pi][0].weekday() == capcfg.entry_weekday]
    else:
        idxs = list(range(0, hi, capcfg.base_cfg.cadence))
    if capcfg.entry_jitter > 0 and hi > 0:
        # random.Random accepts only None/int/float/str/bytes/bytearray — a tuple seed
        # raises TypeError, so build a stable STRING key per (seed, name, index).
        seen: set[int] = set()
        out: list[int] = []
        for pi in idxs:
            off = _random.Random(f"{capcfg.jitter_seed}:{nm}:{pi}").randint(
                -capcfg.entry_jitter, capcfg.entry_jitter
            )
            j = min(hi - 1, max(0, pi + off))
            if j not in seen:  # de-dup: colliding shifts would double-open one day (Codex-9)
                seen.add(j)
                out.append(j)
        idxs = sorted(out)
    return idxs
```

- [ ] **Step 4: Use the helper in candidate building**

In `simulate_account`, replace the inner candidate loop:

```python
    candidates: list[tuple[_date, str, int]] = []
    for nm in capcfg.names:
        ld = loadeds[nm]
        for pi in _entry_indices(ld, hold, capcfg, nm):
            d = ld.adj[pi][0]
            if capcfg.min_date and d < capcfg.min_date:
                continue
            candidates.append((d, nm, pi))
    candidates.sort(key=lambda c: (c[0], (name_pos[c[1]] + c[0].toordinal()) % k_names))
```

(`name_pos`/`k_names` are already computed just above. The previous `n = len(ld.adj)` / `for pi in range(...)` lines are removed.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -v`
Expected: PASS — weekday/jitter tests green, all prior tests still green (`entry_weekday=None`, `entry_jitter=0` ⇒ identical stride).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): entry-weekday filter + seeded entry jitter on the ledger (iter4 task2)"
```

---

### Task 3: Staggered extra tranche on rich weeks

**Files:**
- Modify: `src/uw_scan/reports/vrp_capital_account.py` (`simulate_account` candidate building)
- Test: `tests/unit/reports/test_vrp_capital_account.py` (append)

**Interfaces:**
- Consumes: `CapitalConfig.extra_tranche`, `.extra_tranche_stagger`, `.rich_threshold`; `z_maps` (already built in `simulate_account`).
- Produces: on each base entry whose entry-day `vrp_z ≥ rich_threshold`, an additional candidate at `pi + extra_tranche_stagger` (same name), sized by its own entry-day signal in the main loop.

- [ ] **Step 1: Write the failing test**

```python
# --- Task 3 (iter4): staggered extra tranche ------------------------------
def test_extra_tranche_adds_staggered_rungs_when_rich():
    # z=1.0 everywhere >= rich_threshold 1.0 → every base week spawns a +2-day extra
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    plain = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                          rich_threshold=1.0, names=("SPX",))
    extra = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                          rich_threshold=1.0, names=("SPX",),
                          extra_tranche=True, extra_tranche_stagger=2)
    rp = simulate_account({"SPX": ld}, _settings(), plain)
    re = simulate_account({"SPX": ld}, _settings(), extra)
    assert len(re.rungs) > len(rp.rungs)
    # extra entries are exactly 2 trading days after a base entry → some land off the
    # weekly stride (stride entries are multiples of cadence apart)
    base_dates = {r.entry_date for r in rp.rungs}
    assert any(r.entry_date not in base_dates for r in re.rungs)


def test_extra_tranche_silent_when_never_rich():
    # z=0.2 < rich_threshold 1.0 → no extra fires; identical to plain
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=0.2, n=200)
    plain = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                          rich_threshold=1.0, names=("SPX",))
    extra = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                          rich_threshold=1.0, names=("SPX",), extra_tranche=True)
    rp = simulate_account({"SPX": ld}, _settings(), plain)
    re = simulate_account({"SPX": ld}, _settings(), extra)
    assert [r.entry_date for r in rp.rungs] == [r.entry_date for r in re.rungs]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -k "extra_tranche" -v`
Expected: FAIL — extra tranche not implemented, so `len(re.rungs) == len(rp.rungs)`.

- [ ] **Step 3: Add the staggered candidate in candidate building**

In `simulate_account`, extend the candidate loop body (inside `for pi in _entry_indices(...)`, after appending the base candidate):

```python
    candidates: list[tuple[_date, str, int]] = []
    for nm in capcfg.names:
        ld = loadeds[nm]
        hi = max(0, len(ld.adj) - hold)
        for pi in _entry_indices(ld, hold, capcfg, nm):
            d = ld.adj[pi][0]
            if capcfg.min_date and d < capcfg.min_date:
                continue
            candidates.append((d, nm, pi))
            # staggered extra tranche: rich base week → a second entry `stagger` days
            # later, sized by its OWN entry-day signal in the main loop (not double-counted
            # with the same-day contract overlay, which acts via overlay_mult instead).
            if capcfg.extra_tranche:
                zb = z_maps[nm].get(d)
                pe = pi + capcfg.extra_tranche_stagger
                if zb is not None and zb >= capcfg.rich_threshold and pe < hi:
                    de = ld.adj[pe][0]
                    if not (capcfg.min_date and de < capcfg.min_date):
                        candidates.append((de, nm, pe))
    candidates.sort(key=lambda c: (c[0], (name_pos[c[1]] + c[0].toordinal()) % k_names))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -v`
Expected: PASS — extra-tranche tests green; `extra_tranche=False` default leaves all prior tests green.

- [ ] **Step 5: Reconciliation guard — all flags off ≡ current path**

Append a reconciliation test that locks the backward-compatible contract:

```python
def test_all_iter4_flags_off_matches_legacy_defaults():
    # Golden reconciliation: the six new flags at their DEFAULTS must be a pure no-op.
    # Same fixture as test_simulate_single_name_opens_weekly_rungs (which pins len==10).
    ld = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    default = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0,
                            names=("SPY",))
    explicit = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0,
                             names=("SPY",), compounding=False, entry_weekday=None,
                             entry_jitter=0, extra_tranche=False, extra_tranche_stagger=2)
    a = simulate_account({"SPY": ld}, _settings(), default)
    b = simulate_account({"SPY": ld}, _settings(), explicit)
    assert a.rungs == b.rungs  # Rung is a frozen dataclass → value equality
    assert a.monthly_excess == b.monthly_excess
    assert a.util_by_date == b.util_by_date
    assert (a.n_desired_rungs, a.n_skipped_rungs, a.contracts_desired_total,
            a.contracts_filled_total, a.span) == (
            b.n_desired_rungs, b.n_skipped_rungs, b.contracts_desired_total,
            b.contracts_filled_total, b.span)
    assert len(a.rungs) == 10  # legacy invariant still holds
```

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/vrp_capital_account.py tests/unit/reports/test_vrp_capital_account.py
git commit -m "feat(vrp): staggered extra tranche on rich weeks + reconciliation guard (iter4 task3)"
```

---

### Task 4: `vrp_robustness.py` — min capital, buy-and-hold, compounding metrics

**Files:**
- Create: `src/uw_scan/reports/vrp_robustness.py`
- Test: `tests/unit/reports/test_vrp_robustness.py`

**Interfaces:**
- Consumes: `_Loaded`, `build_bull_put_spread`, `size_weight`, `WINNER`, `simulate_account`, `account_metrics`, `AccountResult`, `_contiguous_monthly`.
- Produces:
  - `min_viable_capital(loaded, settings, *, short_delta=0.25, wing_frac=0.5, hold=30, min_date=None, base_risk_pcts=(0.10,0.20,0.50,1.0)) -> dict` — `{first_entry_date, first_mlpc, max_mlpc, c0_floor: {brp: dollars}}`.
  - `buy_and_hold(adj, capital, rf, *, min_date=None) -> dict` — `{ann_return, cagr, sharpe, maxdd_dollars, maxdd_pct, years, start, end}`.
  - `monthly_equity(res, capital) -> list[tuple[tuple[int,int], float]]` — month-end `$` equity path.
  - `equity_curve_metrics(equity_points, capital, rf) -> dict` — geometric `{ann_return, cagr, sharpe, maxdd_dollars, maxdd_pct, years}` for the compounding read.
  - `_pct(values, q) -> float` — percentile helper (q in [0,1]).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/reports/test_vrp_robustness.py`:

```python
import math
from datetime import date, timedelta
from types import SimpleNamespace

from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_robustness import (
    buy_and_hold,
    equity_curve_metrics,
    min_viable_capital,
    monthly_equity,
    _pct,
)


def _settings():
    return SimpleNamespace(
        vrp_risk_free_rate=0.04, vrp_cost_per_contract=0.65,
        vrp_slippage_frac=0.01, vrp_slippage_min=0.05, vrp_cost_round_trip=True,
    )


def _spx_loaded(*, spot=5000.0, iv=0.20, z=1.0, n=120, start=date(2020, 1, 1)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    adj = [(dd, spot) for dd in dates]
    rows = [{"market_date": dd, "iv": iv, "rv": iv - 0.05, "vrp": 0.05, "vrp_z_20": z}
            for dd in dates]
    return _Loaded(adj=adj, pidx={dd: i for i, dd in enumerate(dates)}, rows=rows, events=[])


def test_min_viable_capital_floor_scales_inverse_to_risk_pct():
    ld = _spx_loaded(spot=5000.0, iv=0.20)
    out = min_viable_capital(ld, _settings(), hold=30)
    assert out["first_mlpc"] > 0
    # floor at 100% risk == one spread's max loss; at 50% risk it doubles
    assert out["c0_floor"][1.0] <= out["c0_floor"][0.5]
    assert out["c0_floor"][1.0] >= out["first_mlpc"]


def test_buy_and_hold_doubling_is_100pct_return():
    adj = [(date(2020, 1, 1), 100.0), (date(2021, 1, 1), 200.0)]
    out = buy_and_hold(adj, 50_000.0, 0.04)
    assert math.isclose(out["maxdd_dollars"], 0.0, abs_tol=1.0)  # monotonic up
    assert out["cagr"] > 0.0


def test_monthly_equity_starts_above_capital_on_gains():
    res = SimpleNamespace(monthly_excess={(2020, 1): 0.10, (2020, 2): 0.05})
    eq = monthly_equity(res, 50_000.0)
    assert eq[0] == ((2020, 1), 55_000.0)
    assert eq[-1] == ((2020, 2), 57_500.0)


def test_equity_curve_metrics_geometric_return():
    pts = [((2020, 1), 55_000.0), ((2020, 2), 60_500.0)]  # +10% then +10%
    m = equity_curve_metrics(pts, 50_000.0, 0.04)
    assert m["maxdd_dollars"] == 0.0
    assert m["cagr"] > 0.0


def test_pct_basic():
    assert _pct([1, 2, 3, 4, 5], 0.5) == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.vrp_robustness'`.

- [ ] **Step 3: Implement the module**

Create `src/uw_scan/reports/vrp_robustness.py`:

```python
"""Iteration-4 robustness studies on the macro short-vol WINNER.

Pure orchestration over the validated ledger (reports/vrp_capital_account.simulate_account)
and pricing (reports/vrp_structure.build_bull_put_spread). Adds the analysis the ledger
deliberately omits: smallest viable starting capital, the SPY buy-and-hold benchmark, a
geometric compounding-metric path, and the weekday / bear-start / Monte-Carlo experiments.
No new deps — stdlib statistics + random only. Every result returns a dict the runner
(scripts/research/vrp_robustness_run.py) persists to a CSV. Reproduce: see that runner.
"""

from __future__ import annotations

import math
from datetime import date as _date
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_structure import build_bull_put_spread

CONTRACT_MULTIPLIER = 100

# NOTE: Tasks 5 and 6 EXTEND this import block (via Edit, never inline) to add
# `import dataclasses`, the vrp_capital_account symbols, `import random`, and
# MacroSignalConfig. Keeping every import at the top avoids ruff E402; importing
# only what each task uses avoids F401 at that task's milestone commit.


def _pct(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]); empty → nan, single → that value."""
    xs = sorted(v for v in values if v is not None and not math.isnan(v))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def min_viable_capital(
    loaded,
    settings,
    *,
    short_delta: float = 0.25,
    wing_frac: float = 0.5,
    hold: int = 30,
    min_date: _date | None = None,
    base_risk_pcts: tuple[float, ...] = (0.10, 0.20, 0.50, 1.0),
) -> dict[str, Any]:
    """Smallest C0 that affords >=1 SPX bull-put spread. Returns the first tradeable
    entry's max-loss/contract, the max over the post-start period (what's needed to
    never skip as spot rises), and the floor C0 per risk-%: ceil(mlpc / brp) to $1k."""
    r = settings.vrp_risk_free_rate
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    first_mlpc: float | None = None
    first_date: _date | None = None
    max_mlpc = 0.0
    for pi in range(0, max(0, len(loaded.adj) - hold)):
        d, s0 = loaded.adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        try:
            st = build_bull_put_spread(
                s0, float(iv), hold / 252.0, r,
                short_delta=short_delta, wing_delta=short_delta * wing_frac,
            )
        except ValueError:
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        if first_mlpc is None:
            first_mlpc, first_date = mlpc, d
        max_mlpc = max(max_mlpc, mlpc)
    if first_mlpc is None:
        return {"first_entry_date": None, "first_mlpc": 0.0, "max_mlpc": 0.0, "c0_floor": {}}

    def _ceil1k(x: float) -> float:
        return math.ceil(x / 1000.0) * 1000.0

    return {
        "first_entry_date": first_date,
        "first_mlpc": first_mlpc,
        "max_mlpc": max_mlpc,
        "c0_floor": {brp: _ceil1k(first_mlpc / brp) for brp in base_risk_pcts},
    }


def buy_and_hold(adj, capital: float, rf: float, *, min_date: _date | None = None) -> dict:
    """SPY buy-and-hold benchmark: invest `capital` at the first spot on/after min_date,
    mark to each close. Sharpe on monthly equity-relative returns (annualised)."""
    pts = [(d, s) for d, s in adj if s and s > 0 and (min_date is None or d >= min_date)]
    if len(pts) < 2:
        return {"ann_return": float("nan"), "cagr": float("nan"), "sharpe": float("nan"),
                "maxdd_dollars": 0.0, "maxdd_pct": 0.0, "years": 0.0,
                "start": None, "end": None}
    s0 = pts[0][1]
    equity = [(d, capital * s / s0) for d, s in pts]
    # month-end marks
    by_month: dict[tuple[int, int], float] = {}
    for d, e in equity:
        by_month[(d.year, d.month)] = e  # last write per month wins (month-end)
    months = [by_month[k] for k in sorted(by_month)]
    rets = [months[i] / months[i - 1] - 1.0 for i in range(1, len(months))]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = mdd = 0.0
    for _d, e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    cagr = (equity[-1][1] / capital) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
        "start": pts[0][0],
        "end": pts[-1][0],
    }


def _contiguous_months(monthly: dict[tuple[int, int], float]) -> list[tuple[tuple[int, int], float]]:
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    out: list[tuple[tuple[int, int], float]] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(((y, m), monthly.get((y, m), 0.0)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def monthly_equity(res, capital: float) -> list[tuple[tuple[int, int], float]]:
    """Month-end $ equity path = capital + running sum of monthly $P&L
    (monthly_excess is net ÷ initial capital, so $P&L_month = excess × capital)."""
    eq = capital
    out: list[tuple[tuple[int, int], float]] = []
    for ym, exc in _contiguous_months(res.monthly_excess):
        eq += exc * capital
        out.append((ym, eq))
    return out


def equity_curve_metrics(equity_points, capital: float, rf: float) -> dict:
    """Geometric metrics for the compounding read: simple monthly returns
    r_t = E_t / E_{t-1} - 1 with E_0 = capital. Sharpe/CAGR/maxDD on that path."""
    if not equity_points:
        return {"ann_return": float("nan"), "cagr": float("nan"), "sharpe": float("nan"),
                "maxdd_dollars": 0.0, "maxdd_pct": 0.0, "years": 0.0}
    levels = [capital] + [e for _ym, e in equity_points]
    rets = [levels[i] / levels[i - 1] - 1.0 for i in range(1, len(levels)) if levels[i - 1] > 0]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = capital
    mdd = 0.0
    for e in levels:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = len(equity_points) / 12.0
    cagr = (levels[-1] / capital) ** (1.0 / years) - 1.0 if (years > 0 and levels[-1] > 0) else float("nan")
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_robustness.py tests/unit/reports/test_vrp_robustness.py
git commit -m "feat(vrp): robustness helpers — min capital, buy-hold, compounding metrics (iter4 task4)"
```

---

### Task 5: Weekday sweep + bear-start study

**Files:**
- Modify: `src/uw_scan/reports/vrp_robustness.py` (append functions)
- Test: `tests/unit/reports/test_vrp_robustness.py` (append)

**Interfaces:**
- Produces:
  - `weekday_sweep(loaded, settings, capcfg, rf) -> list[dict]` — one row per weekday 0..4 plus `"stride"` (entry_weekday=None); each row = `{"entry_weekday": <int|"stride">, **account_metrics}`.
  - `bear_start_study(loaded, settings, capcfg, rf, *, starts, windows_months=(6,12,36)) -> list[dict]` — one row per start: full-path `account_metrics` (compounding-aware) + `{f"ret_{w}m", f"maxdd_{w}m_pct"}` per window from the month-end equity path.

- [ ] **Step 1: Write the failing tests**

First **edit the top import block** of `tests/unit/reports/test_vrp_robustness.py`: add `CapitalConfig` to a new `from uw_scan.reports.vrp_capital_account import CapitalConfig` line, and extend the `from uw_scan.reports.vrp_robustness import (...)` block with `bear_start_study` and `weekday_sweep`. (`date` is already imported at the top.) Then append these test functions (no inline imports):

```python
def test_weekday_sweep_has_six_rows():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=300)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    rows = weekday_sweep(ld, _settings(), cfg, 0.04)
    labels = {r["entry_weekday"] for r in rows}
    assert labels == {0, 1, 2, 3, 4, "stride"}


def test_bear_start_study_returns_summary_and_path():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400, start=date(2015, 1, 1))
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    summary, path = bear_start_study(ld, _settings(), cfg, 0.04,
                                     starts=(date(2015, 6, 1),), windows_months=(6, 12))
    assert len(summary) == 1
    r = summary[0]
    assert "ret_6m" in r and "maxdd_6m_pct" in r and "ret_12m" in r
    assert r["start"] == date(2015, 6, 1)
    # long-form path drives the full-lived-experience chart
    assert path and path[0]["start"] == date(2015, 6, 1)
    assert {"start", "year", "month", "equity", "drawdown_pct"} <= set(path[0])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -k "weekday_sweep or bear_start" -v`
Expected: FAIL — `cannot import name 'weekday_sweep'`.

- [ ] **Step 3: Implement (append to `vrp_robustness.py`)**

First **edit the top import block** of `src/uw_scan/reports/vrp_robustness.py` to add `import dataclasses` (stdlib group) and `from uw_scan.reports.vrp_capital_account import CapitalConfig, account_metrics, simulate_account` (first-party group). Then append these functions (no inline imports):

```python
def weekday_sweep(loaded, settings, capcfg: CapitalConfig, rf: float) -> list[dict]:
    """Run the ledger with entries forced to each weekday (Mon..Fri) and to the default
    stride. SPX-only: loadeds = {capcfg.names[0]: loaded}. Returns account_metrics per."""
    name = capcfg.names[0]
    rows: list[dict] = []
    for label in (0, 1, 2, 3, 4, "stride"):
        wd = None if label == "stride" else label
        cfg = dataclasses.replace(capcfg, entry_weekday=wd)
        res = simulate_account({name: loaded}, settings, cfg)
        m = account_metrics(res, cfg, rf)
        rows.append({"entry_weekday": label, **m})
    return rows


def _window_metrics(equity_points, capital: float, n_months: int) -> dict:
    pts = equity_points[:n_months]
    if not pts:
        return {"ret": float("nan"), "maxdd_pct": float("nan")}
    peak = capital
    mdd = 0.0
    for _ym, e in pts:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    return {"ret": pts[-1][1] / capital - 1.0, "maxdd_pct": mdd / capital if capital else 0.0}


def bear_start_study(
    loaded, settings, capcfg: CapitalConfig, rf: float, *,
    starts, windows_months: tuple[int, ...] = (6, 12, 36),
) -> tuple[list[dict], list[dict]]:
    """For each bear start: (summary_rows, path_rows). summary = full-path metrics
    (geometric if capcfg.compounding else linear) + fixed forward-window return & maxDD;
    path = long-form month-end equity + drawdown for charting the full lived experience."""
    name = capcfg.names[0]
    summary: list[dict] = []
    path_rows: list[dict] = []
    for start in starts:
        cfg = dataclasses.replace(capcfg, min_date=start)
        res = simulate_account({name: loaded}, settings, cfg)
        eqpts = monthly_equity(res, cfg.capital)
        full = (equity_curve_metrics(eqpts, cfg.capital, rf)
                if cfg.compounding else account_metrics(res, cfg, rf))
        row: dict[str, Any] = {"start": start, "n_rungs": len(res.rungs),
                               "sharpe": full.get("sharpe"),
                               # account_metrics emits cagr_excess; equity_curve_metrics emits cagr
                               "cagr": full.get("cagr", full.get("cagr_excess")),
                               "maxdd_pct": full.get("maxdd_pct")}
        for w in windows_months:
            wm = _window_metrics(eqpts, cfg.capital, w)
            row[f"ret_{w}m"] = wm["ret"]
            row[f"maxdd_{w}m_pct"] = wm["maxdd_pct"]
        summary.append(row)
        peak = cfg.capital
        for (yy, mm), e in eqpts:
            peak = max(peak, e)
            path_rows.append({"start": start, "year": yy, "month": mm, "equity": e,
                              "drawdown_pct": (e - peak) / cfg.capital if cfg.capital else 0.0})
    return summary, path_rows
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_robustness.py tests/unit/reports/test_vrp_robustness.py
git commit -m "feat(vrp): weekday sweep + bear-start study (iter4 task5)"
```

---

### Task 6: Monte-Carlo suite

**Files:**
- Modify: `src/uw_scan/reports/vrp_robustness.py` (append; if the file passes ~480 lines, split these four functions into `src/uw_scan/reports/vrp_robustness_mc.py` importing the helpers — note it in the commit)
- Test: `tests/unit/reports/test_vrp_robustness.py` (append)

**Interfaces:**
- Produces (all seeded, all returning a distribution dict `{mean, median, p5, p95, n_trials, seed}` over the chosen metric):
  - `mc_entry_jitter(loaded, settings, capcfg, rf, *, n_trials=200, jitter=2, seed=0, metric="sharpe") -> dict`
  - `mc_block_bootstrap(monthly_values, *, n_trials=1000, mean_block=6.0, seed=0, rf=0.04) -> dict` (stationary bootstrap of a monthly return list → Sharpe distribution)
  - `mc_random_start(loaded, settings, capcfg, rf, *, n_trials=200, min_tail_months=24, seed=0, metric="sharpe") -> dict`
  - `mc_config_perturb(loaded, settings, capcfg, rf, *, n_trials=200, seed=0, metric="sharpe") -> dict`

- [ ] **Step 1: Write the failing tests (determinism + shape)**

First **extend the top `from uw_scan.reports.vrp_robustness import (...)` block** with `mc_block_bootstrap, mc_config_perturb, mc_entry_jitter, mc_random_start`. Then append these test functions (no inline imports):

```python
def test_mc_entry_jitter_deterministic_and_shaped():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    a = mc_entry_jitter(ld, _settings(), cfg, 0.04, n_trials=20, jitter=2, seed=11)
    b = mc_entry_jitter(ld, _settings(), cfg, 0.04, n_trials=20, jitter=2, seed=11)
    assert a == b
    assert a["n_trials"] == 20 and "p5" in a and "p95" in a and a["seed"] == 11


def test_mc_block_bootstrap_ci_ordered():
    vals = [0.02, -0.01, 0.03, 0.00, 0.015, -0.02, 0.025, 0.01] * 12
    out = mc_block_bootstrap(vals, n_trials=500, mean_block=6.0, seed=3)
    assert out["p5"] <= out["median"] <= out["p95"]


def test_mc_random_start_deterministic():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=600)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    a = mc_random_start(ld, _settings(), cfg, 0.04, n_trials=15, seed=5)
    b = mc_random_start(ld, _settings(), cfg, 0.04, n_trials=15, seed=5)
    assert a == b


def test_mc_random_start_window_bounds_sampled_starts():
    # the bear-extension (#5): every sampled start must fall inside [min_start, max_start]
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=600)  # 2020-01 .. ~2022-04
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    lo, hi = date(2020, 6, 1), date(2021, 1, 1)
    w = mc_random_start(ld, _settings(), cfg, 0.04, n_trials=10, seed=5,
                        min_start=lo, max_start=hi, min_tail_months=6)
    assert w == mc_random_start(ld, _settings(), cfg, 0.04, n_trials=10, seed=5,
                                min_start=lo, max_start=hi, min_tail_months=6)
    assert w["trials"]
    assert all(lo <= date.fromisoformat(t["param"].split("=", 1)[1]) <= hi for t in w["trials"])


def test_mc_config_perturb_deterministic():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400)
    cfg = CapitalConfig(capital=1_000_000_000.0, base_risk_pct=0.05, overlay_mult=0.0,
                        rich_threshold=99.0, names=("SPX",))
    a = mc_config_perturb(ld, _settings(), cfg, 0.04, n_trials=15, seed=9)
    b = mc_config_perturb(ld, _settings(), cfg, 0.04, n_trials=15, seed=9)
    assert a == b
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -k "mc_" -v`
Expected: FAIL — `cannot import name 'mc_entry_jitter'`.

- [ ] **Step 3: Implement (append to `vrp_robustness.py`)**

First **edit the top import block** to add `import random` (stdlib group) and `from uw_scan.reports.vrp_macro_signal import MacroSignalConfig` (first-party group). Then append these functions (no inline imports):

```python
def _dist(values: list[float], n_trials: int, seed: int, *, metric: str = "sharpe") -> dict:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return {
        "metric": metric,
        "n_trials": n_trials,
        "seed": seed,
        "n_valid": len(clean),
        "mean": fmean(clean) if clean else float("nan"),
        "median": _pct(clean, 0.5),
        "p5": _pct(clean, 0.05),
        "p95": _pct(clean, 0.95),
    }


def _project(m: dict, metric: str) -> float:
    """Bridge the *_excess key names: account_metrics emits cagr_excess/ann_return_excess;
    the geometric path emits plain cagr/ann_return. sharpe/maxdd_pct exist in both."""
    if metric in m:
        return m[metric]
    return m.get(f"{metric}_excess", float("nan"))


def _metric_of(res, cfg, rf: float, *, metric: str) -> float:
    m = (equity_curve_metrics(monthly_equity(res, cfg.capital), cfg.capital, rf)
         if cfg.compounding else account_metrics(res, cfg, rf))
    return _project(m, metric)


def mc_entry_jitter(loaded, settings, capcfg: CapitalConfig, rf: float, *,
                    n_trials: int = 200, jitter: int = 2, seed: int = 0,
                    metric: str = "sharpe") -> dict:
    """Distribution of `metric` over n_trials, each a different jitter_seed so every entry
    day wiggles ± jitter trading days. Per-trial records returned under 'trials' (full trace)."""
    name = capcfg.names[0]
    trials: list[dict] = []
    for t in range(n_trials):
        js = seed * 100003 + t
        cfg = dataclasses.replace(capcfg, entry_jitter=jitter, jitter_seed=js)
        v = _metric_of(simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric)
        trials.append({"trial": t, "value": v, "param": f"jitter_seed={js}"})
    return {**_dist([x["value"] for x in trials], n_trials, seed, metric=metric), "trials": trials}


def mc_block_bootstrap(monthly_values, *, n_trials: int = 1000, mean_block: float = 6.0,
                       seed: int = 0, rf: float = 0.04) -> dict:
    """Stationary (Politis-Romano) bootstrap of a monthly return series → annualised Sharpe
    distribution. Block length ~ Geometric(1/mean_block); wraps circularly. Feed the
    ZERO-FILLED contiguous series so the distribution centres on the reported base Sharpe."""
    if mean_block <= 0:
        raise ValueError("mean_block must be > 0")
    series = [v for v in monthly_values if v is not None and not math.isnan(v)]
    n = len(series)
    rng = random.Random(seed)
    p = 1.0 / mean_block
    trials: list[dict] = []
    if n >= 2:
        for t in range(n_trials):
            sample: list[float] = []
            while len(sample) < n:
                i = rng.randrange(n)
                while len(sample) < n:
                    sample.append(series[i % n])
                    i += 1
                    if rng.random() < p:
                        break
            sd = pstdev(sample) if len(sample) > 1 else 0.0
            sh = fmean(sample) / sd * math.sqrt(12) if sd > 0 else float("nan")
            trials.append({"trial": t, "value": sh, "param": f"mean_block={mean_block}"})
    return {**_dist([x["value"] for x in trials], n_trials, seed, metric="sharpe_bootstrap"),
            "trials": trials}


def mc_random_start(loaded, settings, capcfg: CapitalConfig, rf: float, *,
                    n_trials: int = 200, min_tail_months: int = 24, seed: int = 0,
                    metric: str = "sharpe", min_start: _date | None = None,
                    max_start: _date | None = None) -> dict:
    """Distribution of `metric` over n_trials random start dates (each leaving >= min_tail_months
    of data). Pass min_start/max_start to restrict sampling to a window — e.g. a bear regime,
    which is the design's #5 ('randomised entry points, extension of the bear-market case')."""
    name = capcfg.names[0]
    lo_d = min_start or _date.min
    hi_d = max_start or _date.max
    all_dates = [d for d, _ in loaded.adj]
    tail = min_tail_months * 21
    # eligible starts: inside [min_start, max_start] AND leaving >= tail trading days of
    # FORWARD data in the full series. Measuring the tail against the data end (not the
    # window) keeps GFC-windowed starts near the 2009 bottom eligible — the whole point of #5.
    eligible = [d for i, d in enumerate(all_dates)
                if lo_d <= d <= hi_d and i < len(all_dates) - tail]
    rng = random.Random(seed)
    trials: list[dict] = []
    if eligible:
        for t in range(n_trials):
            start = eligible[rng.randrange(len(eligible))]
            cfg = dataclasses.replace(capcfg, min_date=start)
            v = _metric_of(simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric)
            trials.append({"trial": t, "value": v, "param": f"start={start}"})
    return {**_dist([x["value"] for x in trials], n_trials, seed, metric=metric), "trials": trials}


def mc_config_perturb(loaded, settings, capcfg: CapitalConfig, rf: float, *,
                      n_trials: int = 200, seed: int = 0, metric: str = "sharpe") -> dict:
    """Distribution of `metric` over random perturbations of the tuned knobs
    (short_delta∈[0.20,0.30], hold∈[20,40], ramp_full_z∈[0.3,0.7]). Attacks overfit."""
    name = capcfg.names[0]
    rng = random.Random(seed)
    trials: list[dict] = []
    for t in range(n_trials):
        sd_ = round(rng.uniform(0.20, 0.30), 4)
        hd = rng.randint(20, 40)
        rz = round(rng.uniform(0.30, 0.70), 4)
        cfg = dataclasses.replace(capcfg,
                                  base_cfg=MacroSignalConfig(short_delta=sd_, hold_days=hd, ramp_full_z=rz))
        v = _metric_of(simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric)
        trials.append({"trial": t, "value": v,
                       "param": f"short_delta={sd_};hold={hd};ramp_full_z={rz}"})
    return {**_dist([x["value"] for x in trials], n_trials, seed, metric=metric), "trials": trials}
```

(Note: `MacroSignalConfig.wing_delta` is a derived property of `short_delta`, so perturbing `short_delta` keeps `0 < wing < short < 0.5` automatically.)

- [ ] **Step 4: Run the tests + the full robustness suite**

Run: `uv run pytest tests/unit/reports/test_vrp_robustness.py -v`
Expected: PASS (all MC + earlier tests).

Run: `uv run python -c "import uw_scan.reports.vrp_robustness as m; print(sum(1 for _ in open(m.__file__)))"`
Expected: a line count < 500 (budget check). If ≥ 480, split the MC functions into `vrp_robustness_mc.py` and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_robustness.py tests/unit/reports/test_vrp_robustness.py
git commit -m "feat(vrp): seeded Monte-Carlo robustness suite (iter4 task6)"
```

---

### Task 7: Runner — `scripts/research/vrp_robustness_run.py`

**Files:**
- Create: `scripts/research/vrp_robustness_run.py`
- Evidence: the five `docs/research/vrp/iter4-*.csv` files it writes

**Interfaces:**
- Consumes: `Settings.from_env`, `Repository`, `load_index_vol`, all `vrp_robustness` functions, `simulate_account`/`account_metrics`, `WINNER`.
- Produces 7 CSVs: `iter4-min-capital.csv`, `iter4-extra-position.csv`, `iter4-weekday.csv`, `iter4-bear-start.csv`, `iter4-bear-start-path.csv`, `iter4-mc.csv`, `iter4-mc-trials.csv`. Both baselines (`baseline_iter3_spx`, `baseline_spy_buyhold`) appear in every metric-bearing experiment.

- [ ] **Step 1: Write the runner**

Create `scripts/research/vrp_robustness_run.py` (mirrors `vrp_capital_sweep.py`'s connect/teardown):

```python
"""VRP backtest ITERATION 4 — robustness experiments on the SPX macro short-vol WINNER.

Experiments (each vs two baselines: iteration-3 SPX base case + SPY buy-and-hold):
  0 min viable starting capital   -> iter4-min-capital.csv
  1 extra position (overlay vs staggered tranche, comp + non-comp; floor C0) -> iter4-extra-position.csv
  2 entry weekday (uncapped + floor C0)  -> iter4-weekday.csv
  3 bear-market start (summary + full equity path) -> iter4-bear-start.csv + iter4-bear-start-path.csv
  4 Monte-Carlo (jitter/bootstrap/random-start/random-start-bear/config; UNCAPPED basis)
        -> iter4-mc.csv (summary) + iter4-mc-trials.csv (every trial — full trace)

SPX-only; SPY is the buy-and-hold benchmark. Deterministic given SEED below (set
VRP_MC_TRIALS=50 for a fast pass). Reuses pricing/loaders unchanged. Persists every
config × every metric; DictWriter uses extrasaction='raise' so nothing is silently dropped.

Run (MacBook local — option_wizard_local + the lake):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_robustness_run.py

Run (against the mini for most-recent data — source creds from .env.local first):
  set -a; source .env.local; set +a; UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_robustness_run.py
"""

from __future__ import annotations

import csv
import dataclasses
import os
import pathlib
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    _contiguous_monthly,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_robustness import (
    bear_start_study, buy_and_hold, equity_curve_metrics, mc_block_bootstrap,
    mc_config_perturb, mc_entry_jitter, mc_random_start, min_viable_capital,
    monthly_equity, weekday_sweep,
)
from uw_scan.storage.repository import Repository

OUT = pathlib.Path("docs/research/vrp/")
SEED = 20260623
BEAR_STARTS = (date(2015, 8, 1), date(2018, 9, 20), date(2020, 2, 19), date(2022, 1, 3))
FLOOR_RISK_PCT = 0.20               # one SPX spread ~ this fraction of the floor account
UNCAPPED_CAPITAL = 1_000_000_000.0  # clean-signal basis: no skips, Sharpe ~ backtest_laddered
N_TRIALS = int(os.environ.get("VRP_MC_TRIALS", "200"))  # MC trials/driver (env-tunable for a quick pass)
# full metric surface persisted for the deterministic experiments — superset of all three
# metric sources (account_metrics *_excess, geometric plain, buy-and-hold). extrasaction='raise'
# then guarantees no metric key is ever silently dropped (persist-every-trace).
WIDE_FIELDS = [
    "variant", "basis", "sharpe", "ann_return", "ann_return_excess", "ann_return_gross",
    "cagr", "cagr_excess", "cagr_gross", "maxdd_pct", "maxdd_dollars", "util_mean",
    "util_peak", "skip_rate", "fill_rate", "win_rate", "breach_rate", "n_rungs",
    "n_skipped_rungs", "contracts_desired_total", "contracts_filled_total",
    "total_return_excess", "years",
]


def _write(name: str, fields: list[str], rows: list[dict]) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        # extrasaction='raise': a row with a key absent from `fields` is a bug, not something
        # to silently drop (persist-every-trace). Missing keys are written as "".
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")


def _metrics(res, cfg, rf, *, compounding: bool) -> dict:
    """Full metric dict for one book. Non-comp → account_metrics (linear, net÷initial cap).
    Comp → equity_curve_metrics (geometric on E_t/E_{t-1}-1) patched with the activity stats
    from account_metrics (util/skip/contracts — those are basis-independent)."""
    if compounding:
        m = dict(equity_curve_metrics(monthly_equity(res, cfg.capital), cfg.capital, rf))
        am = account_metrics(res, cfg, rf)
        for k in ("util_mean", "util_peak", "skip_rate", "fill_rate", "win_rate",
                  "breach_rate", "n_rungs", "n_skipped_rungs", "contracts_desired_total",
                  "contracts_filled_total"):
            m[k] = am[k]
        return m
    return dict(account_metrics(res, cfg, rf))


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    rf = settings.vrp_risk_free_rate
    try:
        spx = load_index_vol(repo, "SPX")
        spy = load_index_vol(repo, "SPY")

        # --- 0: min viable capital -> pick the floor C0 (FAIL LOUD if untradeable) ---
        mv = min_viable_capital(spx, settings, hold=30)
        if mv["first_entry_date"] is None or FLOOR_RISK_PCT not in mv["c0_floor"]:
            raise RuntimeError(
                f"no tradeable SPX entry / no floor at {FLOOR_RISK_PCT:.0%} — is SPX+VIX "
                f"history loaded? got {mv}"
            )
        c0 = mv["c0_floor"][FLOOR_RISK_PCT]
        print(f"min capital: first_mlpc=${mv['first_mlpc']:,.0f} "
              f"max_mlpc=${mv['max_mlpc']:,.0f} floor C0 @ {FLOOR_RISK_PCT:.0%}=${c0:,.0f}")
        _write("iter4-min-capital.csv",
               ["risk_pct", "first_entry_date", "first_mlpc", "max_mlpc", "c0_floor"],
               [{"risk_pct": k, "first_entry_date": mv["first_entry_date"],
                 "first_mlpc": mv["first_mlpc"], "max_mlpc": mv["max_mlpc"], "c0_floor": v}
                for k, v in mv["c0_floor"].items()])

        # two bases: floor C0 (real-account affordability) + uncapped (clean signal, no skips).
        floor_cfg = CapitalConfig(capital=c0, base_risk_pct=FLOOR_RISK_PCT, overlay_mult=0.0,
                                  rich_threshold=99.0, names=("SPX",))
        unc_cfg = CapitalConfig(capital=UNCAPPED_CAPITAL, base_risk_pct=0.05, overlay_mult=0.0,
                                rich_threshold=99.0, names=("SPX",))
        base_res = simulate_account({"SPX": spx}, settings, floor_cfg)
        base_metrics = account_metrics(base_res, floor_cfg, rf)
        unc_res = simulate_account({"SPX": spx}, settings, unc_cfg)
        bh = buy_and_hold(spy.adj, c0, rf, min_date=base_res.span[0])  # same window as the book
        bh_m = {k: v for k, v in bh.items() if k not in ("start", "end")}  # metrics only

        def _baseline_rows(extra: dict) -> list[dict]:
            # both baselines on EVERY experiment (global constraint)
            return [
                {"variant": "baseline_iter3_spx", **extra, **base_metrics},
                {"variant": "baseline_spy_buyhold", **extra, **bh_m},
            ]

        # --- 1: extra position (floor C0; base vs overlay vs staggered; comp + non-comp) ---
        print("exp1 extra-position ...")
        ep_rows: list[dict] = []
        for compounding in (False, True):
            for arm, mut in (
                ("base", {}),
                ("contract_overlay", {"overlay_mult": 1.0, "rich_threshold": 1.0}),
                ("staggered_tranche", {"extra_tranche": True, "rich_threshold": 1.0}),
            ):
                cfg = dataclasses.replace(floor_cfg, compounding=compounding, **mut)
                res = simulate_account({"SPX": spx}, settings, cfg)
                tag = "comp" if compounding else "noncomp"
                ep_rows.append({"variant": f"{arm}_{tag}", "basis": "floor",
                                **_metrics(res, cfg, rf, compounding=compounding)})
        ep_rows += _baseline_rows({"basis": "floor"})
        _write("iter4-extra-position.csv", WIDE_FIELDS, ep_rows)

        # --- 2: weekday (BOTH bases — uncapped clean signal + floor C0) ---
        print("exp2 weekday ...")
        wd_rows: list[dict] = []
        for basis, cfg0 in (("uncapped", unc_cfg), ("floor", floor_cfg)):
            for r in weekday_sweep(spx, settings, cfg0, rf):
                wd = r.pop("entry_weekday")
                wd_rows.append({"variant": f"weekday_{wd}_{basis}", "basis": basis, **r})
        wd_rows += _baseline_rows({"basis": "floor"})
        _write("iter4-weekday.csv", WIDE_FIELDS, wd_rows)

        # --- 3: bear start (summary + full equity path; baselines on the summary) ---
        print("exp3 bear-start ...")
        bs_summary, bs_path = bear_start_study(spx, settings, floor_cfg, rf, starts=BEAR_STARTS)
        for r in bs_summary:
            r["variant"] = f"bear_{r['start']}"
        bs_fields = ["variant", "start", "n_rungs", "sharpe", "cagr", "maxdd_pct",
                     "ret_6m", "maxdd_6m_pct", "ret_12m", "maxdd_12m_pct",
                     "ret_36m", "maxdd_36m_pct"]
        for b in _baseline_rows({}):  # pad to bs_fields; bridge cagr_excess→cagr
            pad = {k: b.get(k) for k in bs_fields}
            pad["cagr"] = b.get("cagr", b.get("cagr_excess"))
            bs_summary.append(pad)
        _write("iter4-bear-start.csv", bs_fields, bs_summary)
        _write("iter4-bear-start-path.csv",
               ["start", "year", "month", "equity", "drawdown_pct"], bs_path)

        # --- 4: Monte Carlo (UNCAPPED clean-signal basis; summary + per-trial full trace) ---
        print(f"exp4 monte-carlo ({N_TRIALS} trials/driver) ...")
        boot_src = _contiguous_monthly(unc_res.monthly_excess)  # zero-filled → centres on base
        bear_lo, bear_hi = date(2007, 1, 1), date(2009, 6, 30)  # GFC window for #5 (bear-conditioned)
        mc = {
            "entry_jitter": mc_entry_jitter(spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED),
            "block_bootstrap": mc_block_bootstrap(boot_src, n_trials=max(N_TRIALS, 500), seed=SEED, rf=rf),
            "random_start": mc_random_start(spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED),
            "random_start_bear": mc_random_start(spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED,
                                                 min_start=bear_lo, max_start=bear_hi, min_tail_months=12),
            "config_perturb": mc_config_perturb(spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED),
        }
        sk = ("metric", "n_trials", "n_valid", "seed", "mean", "median", "p5", "p95")
        mc_summary = [{"test": k, **{kk: v[kk] for kk in sk}} for k, v in mc.items()]
        for name_, sharpe in (("baseline_iter3_spx", base_metrics["sharpe"]),
                              ("baseline_spy_buyhold", bh_m["sharpe"])):
            mc_summary.append({"test": name_, "metric": "sharpe", "n_trials": 1, "n_valid": 1,
                               "seed": SEED, "mean": sharpe, "median": sharpe,
                               "p5": sharpe, "p95": sharpe})
        _write("iter4-mc.csv", ["test", *sk], mc_summary)
        mc_trials = [{"test": k, **t} for k, v in mc.items() for t in v["trials"]]
        _write("iter4-mc-trials.csv", ["test", "trial", "value", "param"], mc_trials)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the runner against the local DB (evidence)**

Run (use `VRP_MC_TRIALS=50` first for a fast smoke pass — the full 200-trial run does ~800 SPX sims and can take many minutes):
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x VRP_MC_TRIALS=50 \
uv run python scripts/research/vrp_robustness_run.py
```
Expected: prints the min-capital line, the `exp1..exp4` progress lines, and seven `wrote N rows -> docs/research/vrp/iter4-*.csv`. If the local DB lacks SPX/VIX history the runner raises `RuntimeError: no tradeable SPX entry` (fail-loud) — run the mini variant from the docstring instead (source `.env.local`). Inspect each CSV is non-empty, the two baseline rows are present in the metric CSVs, and `iter4-mc-trials.csv` has `N_TRIALS × 5` drivers' rows. The `random_start_bear` driver needs pre-2009 SPX history (the 2007–2009 GFC window); on a local DB that starts later those trials are empty/`nan` — run the **mini** variant for the real figure. Re-run the full pass (drop `VRP_MC_TRIALS`) before the final commit.

- [ ] **Step 3: Commit (runner + generated CSVs)**

```bash
git add scripts/research/vrp_robustness_run.py docs/research/vrp/iter4-*.csv
git commit -m "feat(vrp): iteration-4 robustness runner + full-trace CSVs (iter4 task7)"
```

---

### Task 8: Findings notebook + master-report Iteration-4 section + CHANGELOG

**Files:**
- Create: `scripts/_build_vrp_iter4_notebook.py` (builder, mirrors `scripts/_build_vrp_capital_notebook.py`)
- Create: `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` (built + executed)
- Modify: `docs/research/vrp/MASTER-macro-short-vol-capital-utilisation-2026-06-23.md` (append "## Iteration 4 — Robustness")
- Modify: `CHANGELOG.md` ([Unreleased])

**Interfaces:**
- Consumes: the seven `iter4-*.csv` from Task 7 (incl. `iter4-bear-start-path.csv` for the equity paths and `iter4-mc-trials.csv` for the MC distributions).
- Produces: a clean matplotlib notebook (7 sections: min-capital, extra-position equity curves w/ both baselines, weekday bars on both bases, bear-start equity paths + window table, MC trial-distribution histograms with the two baseline lines, look-ahead audit text) + the report section + the changelog entry.

- [ ] **Step 1: Write the notebook builder**

Create `scripts/_build_vrp_iter4_notebook.py` using `nbformat` to assemble cells that read the `iter4-*.csv` with stdlib `csv`, plot with matplotlib, and draw the two baseline reference lines on the extra-position and bear-start charts. (Follow the structure of `scripts/_build_vrp_capital_notebook.py`: a list of `(markdown|code)` cells, `nbformat.v4.new_notebook`, write to the `.ipynb` path.) Each chart's title names the experiment; every equity/return chart adds `axhline`/reference series for `baseline_iter3_spx` and `baseline_spy_buyhold`. Specifically: the bear-start equity paths come from `iter4-bear-start-path.csv` (one line per start, x=year-month, y=equity); the MC section histograms `value` from `iter4-mc-trials.csv` grouped by `test`, with vertical lines at the two baseline Sharpes; the weekday section bars sharpe by weekday faceted on `basis` (uncapped vs floor).

- [ ] **Step 2: Build and execute the notebook**

Run:
```bash
uv run --group research python scripts/_build_vrp_iter4_notebook.py
uv run --group research jupyter nbconvert --to notebook --execute --inplace \
  docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb
```
Expected: builder prints the written path; nbconvert exits 0 with no errors. Open/inspect that every cell produced output and the baseline lines render.

- [ ] **Step 3: Append the Iteration-4 section to the master report**

Add `## Iteration 4 — Robustness (2026-06-23)` to `MASTER-macro-short-vol-capital-utilisation-2026-06-23.md` with: the experiment tables (pasted from the CSVs), the **two baselines** stated once up front, a **Look-ahead audit** subsection enumerating each entry input and why it is trailing/contemporaneous (vrp_z trailing-252, rv trailing-20, IV contemporaneous, settlement = realised outcome not input; the only forward-looking risk is in-sample config selection, which the MC config-perturbation quantifies), the headline findings per experiment, and the exact reproduce command (`scripts/research/vrp_robustness_run.py` + the notebook build/execute commands + `SEED=20260623`). Note explicitly in the section: (a) the MC and weekday experiments run on the **uncapped** basis (capital=1e9, zero skips) to isolate signal robustness from affordability, while extra-position and bear-start use the **floor C0**; (b) the `random_start_bear` driver (GFC-windowed) is the #5 "randomised entry, extension of the bear-market case"; (c) for the **compounding** rows `util_peak` is deployed margin ÷ *initial* capital, so it exceeds 1.0 as equity grows — read it as leverage-vs-start, not a cap breach.

- [ ] **Step 4: Add the CHANGELOG entry**

In `CHANGELOG.md` under `## [Unreleased]` → `### Added`, append:

```markdown
- VRP backtest iteration 4 (research): robustness suite on the SPX macro short-vol
  WINNER — `reports/vrp_robustness.py` (min viable capital, SPY buy-and-hold benchmark,
  geometric compounding metrics, weekday sweep, bear-start study, and a seeded
  Monte-Carlo suite: entry-timing jitter, stationary block bootstrap, randomized
  start, config perturbation) plus six backward-compatible flags on the
  `vrp_capital_account` ledger (compounding, entry-weekday, entry-jitter, staggered
  extra tranche) that reconcile byte-for-byte to the iteration-3 path when off. Runner
  `scripts/research/vrp_robustness_run.py` writes seven `iter4-*.csv` full traces (incl.
  a per-trial Monte-Carlo trace and a long-form bear-start equity path); findings
  in `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` + an Iteration-4
  section of the master report. Every experiment benchmarked against the iteration-3
  SPX base case and SPY buy-and-hold.
```

- [ ] **Step 5: Final full test run + commit**

Run: `uv run pytest tests/unit/reports/test_vrp_capital_account.py tests/unit/reports/test_vrp_robustness.py -v`
Expected: PASS (all unit tests).

Run: `uv run ruff check src/uw_scan/reports/vrp_robustness.py src/uw_scan/reports/vrp_capital_account.py scripts/research/vrp_robustness_run.py`
Expected: no errors (imports at top — no E402).

```bash
git add scripts/_build_vrp_iter4_notebook.py docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb \
  docs/research/vrp/MASTER-macro-short-vol-capital-utilisation-2026-06-23.md CHANGELOG.md
git commit -m "docs(vrp): iteration-4 findings notebook + master report + changelog (iter4 task8)"
```

---

## Self-Review

**1. Spec coverage:**
- (0) min capital → Task 4 (`min_viable_capital`) + Task 7 (run/CSV). ✅
- (1) extra position, overlay vs staggered, comp + non-comp → Tasks 1 (compounding), 3 (staggered), 7 (3 arms × 2). ✅
- (2) weekday → Task 2 (filter) + Task 5 (`weekday_sweep`). ✅
- (3) bear start, path + windows → Task 5 (`bear_start_study` returns summary + long-form path) + Task 7 (`iter4-bear-start{,-path}.csv`). ✅
- (4) MC (jitter/bootstrap/random-start/random-start-bear/config) + look-ahead audit → Task 6 (uncapped basis, per-trial trace) + Task 8 audit subsection. ✅
- Two baselines on EVERY metric experiment (incl. bear-start + MC) → Task 7 `_baseline_rows` + Task 8 chart reference lines. ✅
- SPX-only, defined-risk, persist-every-trace (per-trial MC + bear path, `extrasaction='raise'`), determinism, branch, module budget → Global Constraints + per-task. ✅

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". Every code step shows complete code. The only intentionally-prose step is Task 8 Step 1/3 (notebook builder + report prose), which references the concrete sibling builder to mirror and lists the exact cells/lines — acceptable for a docs artifact, not a logic placeholder.

**3. Type consistency:** `desired_contracts(..., *, sizing_capital=None)`, `CapitalConfig` six new fields, `simulate_account` signature unchanged, `account_metrics(res, capcfg, rf)`, `equity_curve_metrics(points, capital, rf)`, `monthly_equity(res, capital)`, `_dist(...)` keys (`mean/median/p5/p95/n_trials/seed/n_valid/metric`) match across Tasks 6–8. `weekday_sweep`/`bear_start_study`/`mc_*` signatures match their runner call sites in Task 7. ✅

**Resolved by `/review-cycle` (Pass 1–3 + tribunal):**
- ✅ Tuple `random.Random` seed → `TypeError` (Codex caught by executing) — now a string key.
- ✅ MC + weekday now run the **uncapped** basis (design said so; runner had used floor capital).
- ✅ Both baselines now reach bear-start + MC (were extra-position/weekday only).
- ✅ Full-trace persistence: per-trial MC CSV, long-form bear path, broadened metric fields, `extrasaction='raise'` (was `'ignore'` — silent drop).
- ✅ Metric-key bridge (`cagr` vs `cagr_excess`) in `_project`/`_metrics`/`bear_start_study`.
- ✅ Jitter de-dup, negative-stagger + negative-jitter guards, `mean_block<=0` guard, no-tradeable hard-fail.
- ✅ `mc_random_start` window tail measured against the data end (GFC-bottom starts stay eligible).
- ✅ Reconciliation strengthened to a golden default==explicit-defaults equality.

**Remaining judgment calls (intentional, disclosed):**
- `FLOOR_RISK_PCT=0.20` — one SPX spread at ~20% of `C0`. The CSV reports all risk-% floors, so the headline pick is cosmetic; revisit after seeing the real `first_mlpc`.
- Compounding `util_peak` is deployed ÷ *initial* capital, so it exceeds 1.0 as equity grows (labeled in the report as leverage-vs-start, not a cap breach).
- Task 8 notebook body is prose-specified (mirrors the sibling builder); its correctness is gated at execute time by `nbconvert --execute` exiting 0, not statically here.
