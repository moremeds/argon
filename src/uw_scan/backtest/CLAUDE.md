# src/uw_scan/backtest — unified walk-forward backtest harness

The **single home** for the compute primitives every strategy backtest shares:
the OOS discipline gates, the performance metrics, and the parameter-sweep
runner. Pure logic — **no DB, no network** (the sweep runner
takes an injected `repo`; nothing else touches storage). Design:
`docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md`.

## What lives here

| Module | Responsibility | Public surface |
|---|---|---|
| `gates.py` | OOS discipline. `quarter_gate` = the standing per-window catastrophic-degradation rule (`feedback_per_regime_catastrophic_gate`): fail if any calendar quarter reverses the aggregate sign with larger magnitude. `walkforward_gate` = time-ordered holdout on the mean of a value key. | `quarter_gate`, `walkforward_gate` |
| `splitters.py` | Time-ordered train/test cut. `holdout_cut_index(n, frac) = int(round(n*(1-frac)))` is the **one** legacy rounding boundary; every gate/holdout consumer shares it. | `time_ordered_holdout`, `holdout_cut_index` |
| `metrics.py` | Pure functions over per-period **simple** returns (`0.01 == +1%`). Population std (`ddof=0`) everywhere; drawdown on the **additive** cumulative curve (ROR units, not compounded). | `annualized_sharpe`, `additive_max_drawdown`, `hit_rate`, `zero_filled_monthly`, `monthly_summary` |
| `sweep.py` | Persist-as-you-go grid runner: run every config, insert every result row as it completes, keep going past a failing config (persisted as an `error` row). | `run_sweep`, `json_safe` |

Everything is re-exported from `backtest/__init__.py` — import `from uw_scan.backtest import ...`.

## Invariants — do not break these

- **No look-ahead.** A strategy's entry decision at `t` uses only data dated `<= t`; score it against the forward return keyed at `t`, and count origins with no forward return as skipped, never silently drop them.
- **Reproduction target.** `monthly_summary` is the drop-in replacement for the sweep's former `_sharpe_maxdd` (now deleted — `scripts/_vrp_macro_param_sweep.py` imports `monthly_summary` instead) and reproduces its numbers exactly: population std, additive drawdown, zero-filled contiguous months (a month with no exits is a *flat* month, not a skipped one). Changing the std convention or the month-fill silently moves the saved Sharpe ~1.65 headline. Don't.
- **The cut rounding is frozen.** `holdout_cut_index` is the single source of `int(round(n*(1-frac)))`. Do not re-derive the formula inline in a consumer — call the helper.
- **Persist the full trace.** `run_sweep` writes *every* config + metric + the exact `reproduce_cmd` (per the standing CLAUDE.md rule). `json_safe` maps non-finite floats to `None` because `json.dumps(nan)` emits `NaN`, which Postgres `jsonb` rejects — a zero-dispersion config's `nan` Sharpe must persist as `null`, not kill the run.
- **Degenerate inputs return `nan`/`0.0`, never raise** — sweep summaries stay serializable.

## Compute is unified; storage is not

This is the load-bearing structural fact. The harness unified the **compute
engine** — strategies delegate their gate, holdout, and (for parameter sweeps)
metric math here, with zero private copies. It did **not** unify result
**storage**:

- **Parameter sweeps** → the generic `backtest_sweep_runs` / `backtest_sweep_results`
  (`storage/backtest_repository.py`, migration 095): one run row (provenance:
  strategy, `reproduce_cmd`, `params_grid`, data window, status) + N result rows
  (`config` JSONB, `metrics` JSONB, `gates` JSONB, `n_trades`, per-config
  `status`/`error`). Any "grid of configs → metrics" strategy fits this.
- **Productionized per-strategy decisions** → bespoke verdict tables
  (`skew_directional_verdicts`, `vrp_harvest_verdicts`, `vrp_backtest_results`/`_trades`).
  These are typed domain objects the API/web consume; they share the compute
  engine but keep their own schema **on purpose** — don't force one table shape
  onto both.

## Adding a new strategy backtest

1. **Reuse, don't copy.** Import `quarter_gate` / `walkforward_gate` /
   `holdout_cut_index` / the metric fns. A hand-rolled `int(round(n*(1-frac)))`
   or a private quarter-degradation loop in a `reports/` module is a review
   defect — that duplication is exactly what this package exists to kill.
2. Price your structure (spread/condor/single leg) into per-period returns
   with a look-ahead-free entry decision, then score them with the metric
   functions.
3. If you sweep parameters, drive them through `run_sweep(configs, run_one,
   repo=BacktestRepository(conn), strategy=..., reproduce_cmd=...)` so the full
   trace persists.
4. Tests go under `tests/unit/backtest/` (pure) — no DB fixture needed here.

## Tests

`tests/unit/backtest/test_{gates,metrics,splitters,sweep}.py`. Gate
equivalence is proven as a math identity (not just fixtures); the strategy-side
folds are pinned by the existing `skew_markout` / `vrp_markout` regression suites
passing **unchanged**.
