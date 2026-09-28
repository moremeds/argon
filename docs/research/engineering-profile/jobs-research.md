# Worker/research executable diagnostic — 2026-09-27

Baseline `9f094d0c`; worktree `chore/profile-review`. This is a diagnostic harness, not an application refactor. No production source or schema changed. Commit: none.

## Validated mechanisms

`technical_daily_refresh` executed with captured real NVDA/SPY OHLCV and mocked source/persistence boundaries. Both tickers completed; four actual `build_technical_series` calls occurred: **two per ticker**. Each mocked series write received 1300 rows. This proves duplicated compute in the actual job, not merely a static call graph.

The unchanged actual snapshot and series functions produced exactly equal DataFrames and equivalent snapshot JSON for baseline versus a reuse-series counterfactual. Counterfactual computes the series once and substitutes that DataFrame for the snapshot's internal repeated call using `unittest.mock.patch`; no copied indicator formula or application modification. The tiny patch overhead is included in counterfactual timing.

Actual `option_surface_backfill` ran with explicitly mocked repository/provider boundaries and symbolic `MOCK_*` membership identifiers, no invented prices. Existing captured membership `{MOCK_PRESENT, MOCK_REMOVED}` and desired watchlist `{MOCK_PRESENT, MOCK_MISSING}` have equal counts. Baseline returned zero rows and made zero fetch calls despite `MOCK_MISSING` being absent. The deterministic mocked market date was 2026-09-24. This is a reproduced logic defect, not observed production missing data.

## Data and evidence

Capture: Mini PostgreSQL `option_wizard`, `uw_scan.technical_daily`, 1300 complete OHLCV rows each for NVDA and SPY. These are persisted technical input bars, **not a fresh Apex provider fetch**. The query selects latest rows ordered by session date and then reverses to ascending order. Stored dates are mapped to ISO UTC midnight for the function's daily-bar input contract; no intraday observation time is inferred. Original capture query, capture time, source inserted-at ranges, input date range, exact row counts, SHA-256, code revision and imported module paths are in:

- `output/profile-review/jobs-research/captured-bars.json`
- `output/profile-review/jobs-research/validation.json`

Capture used connection-level `default_transaction_read_only=on` and `statement_timeout=8000`, verified transaction read-only before SELECTs. No DDL/DML, DB fixtures, local data copy or paid/provider calls.

The harness asserts actual imports resolve inside this worktree. No mocked market prices were used for the technical calculation. Recent OHLC overlay is explicitly mocked absent so this isolates the stored daily indicator computation; this does not validate split-reconciliation I/O behavior.

## Reproduction

From this worktree, use the shared existing environment and worktree imports:

```sh
export UV_PROJECT_ENVIRONMENT=/Users/chenxi/projects/argon/.venv
export PYTHONPATH="$PWD/src"
# Already executed once: readonly source capture + validation.
rtk proxy uv run --no-sync python scripts/profile_review/jobs_research.py \
  --capture-bars --bars output/profile-review/jobs-research/captured-bars.json
# Offline repeat validation, no DB/source calls.
rtk proxy uv run --no-sync python scripts/profile_review/jobs_research.py \
  --bars output/profile-review/jobs-research/captured-bars.json
# Final timings: run only in the lead's sequential CPU slot.
rtk proxy uv run --no-sync python scripts/profile_review/jobs_research.py \
  --bars output/profile-review/jobs-research/captured-bars.json --repeats 7
rtk proxy uv run --no-sync ruff check scripts/profile_review/jobs_research.py
```

Lint passed. Initial bounded validation and final timing parity assertions passed. In the lead's sequential CPU slot, seven alternating-order repeats measured median baseline **58.073 ms** versus reuse **37.158 ms**, a **36.0%** decrease for this pure calculation workload. All 14 raw timings are in `output/profile-review/jobs-research/timing.json`; separate `baseline.prof` and `reuse.prof` retain cProfile results. Timings exclude source/DB I/O, row serialization and actual job orchestration; no end-to-end or fleet-level speedup claim is justified. Actual job call count is separate from the pure calculation timer. Every alternating-order repetition is retained; cProfile artifacts are separate runs, not included in median timings. No code change has been authorized from this evidence alone.

Captured input: 2021-07-23 to 2026-09-25; SHA-256 `b3b7e2a4ed2d893b585a0dd04a691f48a1c09e6f783ffda2b205a5d7e861a867`. Data capture timestamp: `2026-09-26T16:41:04.339447+00:00`. Source revision: `9f094d0cb5b8d20f6103bae1bab2cea25c69c358`.
