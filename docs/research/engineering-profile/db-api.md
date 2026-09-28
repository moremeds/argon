# DB/API profiling — scoped evidence

Status: mechanism verified; final sequential timings are owned by the lead. No application refactor or database write was performed. Script: `scripts/profile_review/db_api.py`.

## Reproduce

Run from this worktree, using the shared project environment and this checkout's source:

```sh
UV_PROJECT_ENVIRONMENT="$ARGON_MAIN/.venv" \
PYTHONPATH="$ARGON_MAIN/.worktrees/profile-review/src" \
uv run --no-sync python scripts/profile_review/db_api.py \
  --env-root "$ARGON_MAIN" \
  --db-host "$PROFILE_DB_HOST" --db-name option_wizard \
  --ticker SPY --repeats 5 \
  --output output/profile-review/db-api/final
```

Set `ARGON_MAIN` to the main checkout and `PROFILE_DB_HOST` to the authorized read-only source host using your private environment. Captured source metadata stays in ignored output artifacts.

`.env.local` then `.env` are read only from the supplied main root with existing `_load_dotenv`; secrets are never printed or serialized. Command-line DB overrides are explicit. Every connection starts with `default_transaction_read_only=on`, 8-second statement timeout and repeatable-read/read-only transaction; the setting is asserted. SQL captures existing data only, then rolls back. Output includes captured inputs, source metadata, input hashes, raw timing arrays, and cProfile artifacts. No HTTP endpoint, external vendor client, schema operation, test fixture, job or deployment is invoked.

## Mechanism result (not acceptance timings)

`output/profile-review/db-api/mechanism/results.json` and `captured-inputs.json` record real mini Postgres input. The one-repeat smoke run coincided with another worker's build; its timings must not become final performance claims.

- SPY volatility assembled successfully using captured source inputs: 250 RV rows, 365 daily OHLC rows, 882 SPY reference rows, 6,721 smile rows. Captured run ID was 674999.
- One assembly attempted 250 `vrp_daily` upserts and 344 `stock_analytics_daily` upserts, plus one commit. **All intercepted at the Repository persistence boundary. Zero writes were sent to PostgreSQL.** This validates 594 intended row upserts per invocation on this input, not actual rows changed, query execution time, disk I/O, WAL bytes or endpoint latency.
- Replaying the captured data preserved response hash, intended write hashes/counts and commit count.
- Full SPX/VIX loader had 5,212 aligned actual observations, 2006-01-03 through 2026-09-22 (SPX 5,212 rows, VIX 5,245 from the queried start).
- A suffix of 272 aligned observations (20-return RV warm-up + 252 VRP observations) produced the exact same last RV/VRP/z row and the same trailing 252 RV/VRP values. This is one real dataset equivalence check, not proof for arbitrary as-of, missing-data, correction or strike-grid behavior.
- Stock duplicate-read evidence remains **static**, explicitly labeled in JSON. The script records actual AST call sites for the four repeated primitive methods. It does not claim to have measured total stock SQL statements.

## Scope of timing

Volatility timing replays data in memory and includes copying captured inputs, intent hashing, pandas transformations and response-model assembly. Output-equality verification occurs before the timed loop. It excludes capture/database time and does not represent actual request latency or write time. `capture_seconds` is a separate one-shot measure including real reads plus assembly; it is not a stable DB benchmark.

VRP full/bounded timings exercise `_build_loaded` only with the same captured SPX/VIX dictionaries. They exclude DB reads, live quote retrieval, spread selection, network/HTTP, serialization transport and pool contention. Full and suffix cProfile files are separately stored. A `.prof` run is additional to raw timing samples and is not included in their medians.

## Corrections and limits from the review

- The stock cache default is **20 seconds**, not 60. Existing API pool, health snapshots and batching remain present.
- Current `single_stock.py` calls dealer `gather_inputs` at line **431**; old review artifact's 466 was incorrect. Whole historical reports intentionally mix explicit-run sections and latest overlays; no claim that the entire response promised PIT.
- PostgreSQL estimated table row counts understated vol-index coverage. Captured actual SPX/VIX data supports the full-since-2006 rebuild finding.
- Bounded suffix equivalence is a profiling experiment, not a code change or production recommendation accepted for all edge cases. History for backtests remains full by design.
- No live endpoint load test, WAL measurement, production write benchmark, pool saturation test or all-ticker extrapolation was performed.
- No tests or fixtures with fabricated market data were created. No third-party dependencies were added.

Task 2 changes are confined to the script, this evidence document and `output/profile-review/db-api/`. One preliminary stdlib editing command caused uv to create an ignored worktree `.venv`; it installed no packages, and subsequent actual profiling explicitly used the shared main environment. No unrelated tracked files were edited. Commit: none. Await lead acceptance before further work.

## Final verification (supersedes mechanism/static-only stock limitations)

Final artifacts: `output/profile-review/db-api/final-pinned/{results.json,captured-inputs.json,volatility.prof,vrp-full.prof,vrp-bounded.prof}`. Source capture is `capture-final/`; earlier captures are diagnostic attempts, not accepted result sets.

Seven sequential offline timing samples after other workers released CPU:

| Scope | Median wall time | Interpretation |
|---|---:|---|
| Volatility assembly replay | 69.912 ms | Captured reads, no database writes; includes input copies/intent hashing |
| Full 5,212-row VRP feature build | 492.075 ms | Pure historical computation |
| Bounded 272-row VRP feature build | 6.253 ms | Same final row and trailing 252 RV/VRP values |

One real source capture ran `latest_run_id` + `assemble_single_stock_report` with a psycopg Cursor recorder under read-only transaction. It completed **33 SELECT statements and two `SET search_path` statements**. The 33 includes the initial latest-run lookup; the assembler itself issued 32 SELECTs. This excludes HTTP cache/spot-overlay queries and is not a total endpoint query count. Exactly five SQL+parameter pairs executed twice: latest run lookup, exposure aggregate, realized-vol latest, strike-GEX curve and exposure summary. The latter four are the repeated report/dealer reads identified statically. JSON preserves normalized query text, hashes of SQL and parameters, returned row counts, `execute()` elapsed seconds and caller stack; this is a one-shot observation, not a latency distribution.

Initial stock guards rejected harmless session `SET search_path`; the final harness permits that exact fixed shape, records it separately and retains server read-only enforcement. Both direct SELECT and read-only WITH queries are supported. Any PostgreSQL data write remains rejected; acquisition uses no provider network clients. `build_short_vol` was inspected: only stored-series/chain/earnings reads.

### Fully offline replay

Typed capture now preserves date/datetime/Decimal/DailyOhlcRow. Replay enters before dotenv/settings/connection loading and never contacts PostgreSQL. `calendar_date` is recorded and the volatility module's `_date.today()` is pinned inside the isolated profiler process, keeping DTE/filter output reproducible on later dates. Old same-session captures recover calendar date from their recorded timestamp; newly created captures store it explicitly.

```sh
UV_PROJECT_ENVIRONMENT="$ARGON_MAIN/.venv" \
PYTHONPATH="$ARGON_MAIN/.worktrees/profile-review/src" \
uv run --no-sync python scripts/profile_review/db_api.py \
  --env-root "$ARGON_MAIN" --ticker SPY \
  --replay-from output/profile-review/db-api/final-pinned \
  --repeats 7 --output output/profile-review/db-api/lead-replay
```

For capture without profiling, append `--capture-only` to the source command. Captured-input SHA256 for final run: `eca006799f1b8c36d09dc9272f0f13ef17c4e37c5f364e8c3aa8ee6a8057bd92`.

Validation: runnable capture, offline replay response/write-intent parity assertions, bounded-window parity assertions and `uv run --no-sync ruff check scripts/profile_review/db_api.py` passed. This remains profiling only; no application behavior changed, no commit.
