# docs/research/regime — CRI + VCG methodology research

## Files

- `cri-methodology.md` — **source of truth** for CRI math, calibration, and design decisions. Read this before changing any threshold in `src/uw_scan/cards/cri_scorers.py`.
- `vcg-methodology.md` — **source of truth** for VCG math, calibration, and design decisions. Read this before changing any threshold in `src/uw_scan/cards/vcg_scoring.py`.
- `cri-validation.ipynb` — out-of-sample walk-forward validation against 20 years of CBOE vol-complex data. Section 9 is the honest accuracy breakdown.
- `closure-2026-05-24.md` — closure memo for the regime-research workspace with SQL cookbook for the DB-backed backtest tables.
- `cri-backtest.{md,csv}`, `oos-summary.json` — **legacy on-disk artifacts** retained for the router file-fallback during the deploy transition. Removed in a follow-up PR after the prod gate (≥1 completed CRI run in prod) is satisfied. Do not regenerate them.

## Backtest results live in Postgres (2026-05 closure)

- The CRI + VCG backtests persist to `uw_scan.regime_backtest_runs` + `uw_scan.regime_backtest_daily` (migration 057). The DB is the source of truth.
- Inspect via `SELECT * FROM uw_scan.regime_backtest_runs ORDER BY created_at DESC LIMIT 10;` — see `closure-2026-05-24.md` for the full SQL cookbook.
- Do NOT commit any CSV/MD/JSON output files from new backtest runs. The legacy `cri-backtest.{md,csv}` and `oos-summary.json` stay in place only until the file-removal follow-up PR ships.
- `composite_version` provenance is derived from code constants (`cri_scorers.COMPOSITE_VERSION`, `vcg_scoring.COMPOSITE_VERSION`). Never override on the CLI — the value persisted in the DB always matches the code that produced the daily rows.

## When to update

- After changing any constant in `cri_scorers.py`: update §3 of `cri-methodology.md` with the new threshold and rationale, AND update `LAST_KNOWN_AUC_DD5` / `LAST_KNOWN_AUC_DD10` (which the OOS gate's seed fixture reads) in the same diff. PR review enforces this contract.
- After changing any constant in `vcg_scoring.py` (VCG_TRIGGER, VCG_RO_TRIGGER, BOUNCE_TRIGGER, VIX_FLOOR, VIX_EDR, VIX_PANIC_LOW, VIX_PANIC_HIGH, VVIX_ELEVATED, VVIX_EXTREME): update §3 of `vcg-methodology.md` with the new threshold and rationale.
- After running a backtest (either indicator): inspect the persisted run via the SQL cookbook in `closure-2026-05-24.md`. Do not commit regenerated CSV/MD files.

## VCG rules

- VCG's v1 calibration is as-ported from xenon (commit `d3cbc08`). Recalibration to v2 requires a separate spec under `docs/superpowers/specs/` — do not roll calibration changes into routine PRs.
- VCG is **descriptive**, not predictive. The named-crash ±5d window in `vcg-methodology.md` §6.3 shows VCG was late on Lehman (SUPPRESSED days −5 through −1, BOUNCE day 0, RISK_OFF day +3). Pair VCG with CRI or a leading vol signal for early-warning use.
