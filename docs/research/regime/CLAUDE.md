# docs/research/regime — CRI + VCG methodology research

## Files

- `cri-methodology.md` — **source of truth** for CRI math, calibration, and design decisions. Read this before changing any threshold in `src/uw_scan/cards/cri_scorers.py`.
- `vcg-methodology.md` — **source of truth** for VCG math, calibration, and design decisions. Read this before changing any threshold in `src/uw_scan/cards/vcg_scoring.py`.
- `canary-methodology.md` — **source of truth** for 5% Canary math, calibration, and design decisions. Read this before changing any threshold in `canary-calibration-v1.json` or `src/uw_scan/cards/canary_scoring.py`. Anchored on Thrasher (2023, NAAIM) plus five literature-backed vol-complex signals.
- `cri-validation.ipynb` — out-of-sample walk-forward validation against 20 years of CBOE vol-complex data. Section 9 is the honest accuracy breakdown.
- `closure-2026-05-24.md` — closure memo for the regime-research workspace with SQL cookbook for the DB-backed backtest tables.

## Backtest results live in Postgres (2026-05 closure)

- The CRI + VCG backtests persist to `uw_scan.regime_backtest_runs` + `uw_scan.regime_backtest_daily` (migration 057). The DB is the sole source of truth — `/api/regime/vcg-validation` returns 503 if no completed VCG run exists at the current COMPOSITE_VERSION.
- Inspect via `SELECT * FROM uw_scan.regime_backtest_runs ORDER BY created_at DESC LIMIT 10;` — see `closure-2026-05-24.md` for the full SQL cookbook.
- Do NOT commit any CSV/MD/JSON output files from backtest runs — the renderer in `src/uw_scan/reports/regime_backtest_report.py` produces markdown on demand from the DB row.
- `composite_version` provenance is derived from code constants (`cri_scorers.COMPOSITE_VERSION`, `vcg_scoring.COMPOSITE_VERSION`). Never override on the CLI — the value persisted in the DB always matches the code that produced the daily rows.

## When to update

- After changing any constant in `cri_scorers.py`: update §3 of `cri-methodology.md` with the new threshold and rationale, AND update `LAST_KNOWN_AUC_DD5` / `LAST_KNOWN_AUC_DD10` (which the OOS gate's seed fixture reads) in the same diff. PR review enforces this contract.
- After changing any constant in `vcg_scoring.py` (VCG_TRIGGER, VCG_RO_TRIGGER, BOUNCE_TRIGGER, VIX_FLOOR, VIX_EDR, VIX_PANIC_LOW, VIX_PANIC_HIGH, VVIX_ELEVATED, VVIX_EXTREME, VIX_PCT_PANIC, VVIX_PCT_PANIC, VOL_PERCENTILE_WINDOW, VOL_PERCENTILE_TIE_RULE): update §3 of `vcg-methodology.md` with the new threshold and rationale.
- After changing any threshold in `canary-calibration-v1.json` (the persisted
  Class B floor/ceiling values produced by `scripts/backtest_canary.py
  --calibrate`): update §3 of `canary-methodology.md` with the new values
  and the train-window calibration command used, AND update the
  `LAST_KNOWN_AUC_*` constants in `tests/integration/regime/test_canary_oos_gate.py`
  if the recalibration moves AUCs by more than 0.02. Bumping
  `canary_calibration.COMPOSITE_VERSION` is required when the change is
  not backward-compatible with persisted snapshots.
- After running a backtest (either indicator): inspect the persisted run via the SQL cookbook in `closure-2026-05-24.md`. Do not commit regenerated CSV/MD files.

## VCG rules

- VCG's v1 calibration is as-ported from xenon (commit `d3cbc08`). Recalibration to v2 requires a separate spec under `docs/superpowers/specs/` — do not roll calibration changes into routine PRs.
- VCG is **descriptive**, not predictive. The named-crash ±5d window in `vcg-methodology.md` §6.3 shows VCG was late on Lehman (SUPPRESSED days −5 through −1, BOUNCE day 0, RISK_OFF day +3). Pair VCG with CRI or a leading vol signal for early-warning use.
