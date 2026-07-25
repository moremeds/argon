# UW Historical Alpha — Recurring Capture + Self-Healing Design

- **Date:** 2026-07-24
- **Status:** Approved (design); implementation plan pending
- **Owner:** chenxi
- **Supersedes/relates:** WIP branch `misc/uw-historical-alpha-scan` (commit `cda8717`, 2026-07-03) and its one-time-backfill plan `docs/plans/2026-07-02-uw-historical-alpha-backfill.md`

## 1. Goal

Wire five UW-derived alpha datasets into Argon as **durable, recurring, self-healed** warm-store tables:

- `uw_gex_levels_daily`
- `uw_volatility_signal_daily`
- `uw_short_pressure_daily`
- `uw_intraday_option_flow_bars`
- `uw_dark_lit_flow_prints`

Today these tables exist only on the mini (populated once by an abandoned bare-`httpx` backfill script through 2026-07-01, then left to rot). Nothing on main creates them, captures into them daily, or monitors them. This design gives each one the standard Argon lifecycle: migration → typed fetcher → normalizer → storage → recurring worker job → `data_gap_healer` registration.

**Non-goals (explicitly out of scope):** the strategy-assembler layer that would consume this data for the "five 1–3 week swing strategies" (deferred — plumbing only), the branch's `oi_change` historical-keying rider (superseded, see §3), and the long-weekend option-chain backfill (unrelated effort, see §3).

## 2. Scope decision: the branch is mostly dead weight

"Finish and merge the branch" is a misnomer. Auditing `cda8717` diff-by-**concern** (not by file) against current main:

| Branch artifact | Verdict | Why |
|---|---|---|
| `095_uw_historical_alpha_tables.sql` (5 tables) | **TAKE**, renumber → `108` | Net-new. Already live on the mini (migration is a no-op there; creates the tables on local/CI/fresh). |
| `096_oi_change_historical_key.sql` | **DROP** | Just an index on `oi_change_events`; belongs to the superseded oi_change effort, not these 5 tables. |
| `storage/options.py` `replace_oi_change_rows_for_date` | **DROP** | oi_change historical upsert; separate concern. |
| `sources/uw.py` diff (`market_date` on `fetch_oi_change`/`fetch_oi_per_strike` via `_fetch_json`) | **DROP — actively harmful** | Main #225 (`2102d66`) already added `market_date` to `fetch_oi_change` *and* shipped the `uw_fetch_memo` dedupe. The branch routes through the **non-memoized** `_fetch_json`, so taking it would regress #225's memo. |
| `test_oi_change_historical_upsert.py`, `test_uw_sources_oi_change_date.py`, `test_uw_long_weekend_history_backfill.py` | **DROP** | Test the dropped riders. |
| `uw_long_weekend_history_backfill.py` + `.sh` + its plan | **DEFER/DROP** | Separate long-weekend option-chain backfill; unrelated to these 5 tables. |
| `uw_historical_alpha_backfill.py` (850 lines, bare `httpx`) | **REUSE AS REFERENCE ONLY** | Its endpoint map + request math are correct; its client bypasses memo/audit/budget. Catch-up (§7) is rebuilt on the standard fetchers. |
| `docs/plans/2026-07-02-…md`, `docs/research/uw-historical-alpha-scan/README.md` | **KEEP** | Reference docs. |

**Net effect:** cherry-pick the 5-table migration, drop the oi_change + long-weekend riders, build the production plumbing fresh, wire the healer. The branch "resume" is really the migration + docs; the code is new.

## 3. The five tables (shapes, verbatim from migration)

Two shapes, mapping onto the two healer modes that already exist.

### 3a. Daily snapshots — PK `(ticker, market_date)`

- **`uw_gex_levels_daily`** — `call_wall, put_wall, gamma_flip, gamma_magnet, spot`. Source: `gex-levels?date=`.
- **`uw_volatility_signal_daily`** — `anomaly_direction, anomaly_score, vol_character, half_life_days, hurst_rv, vrp_rank, risk_premium, source_mask[]`. Sources: `volatility/anomaly` + `volatility/character` + `volatility/variance-risk-premium`.
- **`uw_short_pressure_daily`** — `short_interest, si_float, days_to_cover, fee_rate, rebate_rate, short_shares_available, total_float, ftd_quantity, short_volume, total_volume, short_volume_ratio`. Sources: `shorts/{t}/interest-float/v2` + `ftds` + `volumes-by-exchange`.

All three carry `raw_jsonb` + `fetched_at`.

### 3b. Event logs — append-only

- **`uw_dark_lit_flow_prints`** — PK `(source, tracking_id)`, `source ∈ {darkpool, lit_flow}`. Trade-print grain (`executed_at, price, size, premium, market_center, nbbo_*, sale_cond_codes[], trade_code`). Sources: `darkpool/{t}` + `{t}/lit-flow`.
- **`uw_intraday_option_flow_bars`** — PK `(ticker, market_date, ts, source, expiry)`, `source ∈ {net_prem_ticks, greek_flow}`. Intraday bar grain (`net_call_premium, net_put_premium, net_delta, call_volume, put_volume, dir_delta_flow, dir_vega_flow, otm_*, transactions, volume`). Sources: `net-prem-ticks` + `greek-flow`.

Both carry `raw_jsonb` + `fetched_at`.

## 4. Healer mapping

The registry (`reports/data_gap_healer.py`) already has both modes. `strict_ticker_date` auto-detects `market_date` + `ticker`, so the daily tables drop in with no scanner changes.

### 4a. Daily snapshots → `strict_ticker_date` (real per-session gap-heal)

Same shape as the existing `greek_exposure_daily` entry (`provider="uw"`, `granularity="per_ticker_date"`).

| Table | `retention_days` (descriptive only) | Rationale |
|---|---|---|
| `uw_gex_levels_daily` | `None` | `gex-levels?date=` serves multi-year history (verified: mini rows back to 2023-08-03). |
| `uw_short_pressure_daily` | `None` | interest-float is a current-snapshot; ftds/volumes carry history. Heal attempts the date and records `no_data` where the source returns nothing. |
| `uw_volatility_signal_daily` | `None` | VRP serves full YTD; anomaly/character only ~16 recent sessions. A heal of an old date fills VRP columns only — accepted (partial-fill beats a null row), which is why this stays `strict_ticker_date`, not `freshness_only`. |

**⚠️ `retention_days` is NOT enforced at scan time** (corrected 2026-07-24 during review). It is descriptive metadata only — persisted to the registry DB + shown in the policy runbook; `_scan_strict_ticker_date` never reads it (verified: the only usages are the dataclass field, the registry values, and the DB upsert). An earlier draft claimed `retention_days≈anomaly-window` "stops the phantom-gap storm" — that was false. The real reasons a storm does **not** occur:

1. The strict scanner keys on **row existence** (`LEFT JOIN … WHERE a.ticker IS NULL`), NOT column-nullness — so a `uw_volatility_signal_daily` row that exists with only VRP populated counts as **covered**; backfilled-but-sparse dates never manufacture a gap.
2. The audit window is bounded by `data_gap_healer_start` (default `2026-01-01`, i.e. YTD).
3. Post-catch-up (§7) the mini is densely populated → ~no missing rows.
4. Any residual heal spend is bounded by `DATA_GAP_HEALER_MAX_UW_CALLS`.

Caveat (existing-system behavior, not introduced here): a genuinely-missing, permanently-unhealable `(ticker, date)` is re-detected and re-attempted every nightly run (the audit builds fresh gap items each run; there is no cross-run `no_data` memory). This is bounded by the UW cap and already true for `greek_exposure_daily`. If a specific pre-history range ever proves noisy, the **enforced** exclusion tool is a `Caveat` (scan-time, like the SPCX pre-listing seed), not `retention_days`.

Each gets a **heal adapter** in `worker/jobs/data_gap_adapters.py` that calls the *same* per-ticker-date capture function the daily job uses (one code path, two callers: daily job = all watchlist tickers for today; heal = one ticker, one date).

### 4b. Event logs → `freshness_only` (monitor age, no per-date heal)

Join the existing block verbatim:

```python
_entries([... , "uw_dark_lit_flow_prints", "uw_intraday_option_flow_bars"],
         "options_chain", "freshness_only",
         reason="UW-retention/event-log shaped; freshness-monitored, no auto-backfill")
```

Rationale: an append-only event stream has no clean "this row should exist" key to audit against, so there is nothing to gap-heal — only staleness to alert on. Identical treatment to the already-registered `dark_pool_events` / `flow_events` / `oi_change_events`. A recurring daily capture job (§5) still writes forward; the healer only flags if the newest write goes stale.

## 5. Production plumbing (per `src/uw_scan/CLAUDE.md` "adding a new endpoint")

For each dataset:

1. **`api/endpoints.py`** — add `EndpointSlug` entries. Existing: `DARKPOOL_TICKER`, `SHORT_INTEREST_FLOAT`. Net-new: gex-levels, volatility anomaly/character/vrp, ftds, volumes-by-exchange, net-prem-ticks, greek-flow, lit-flow.
2. **`sources/uw.py`** — memoized fetchers (daily datasets); audit + raw-payload write; `market_date` param on the daily fetchers.
3. **`normalize.py`** — `normalize_*` → typed rows (raise `NormalizationError` on malformed payloads, per repo rule).
4. **`storage/uw_historical_alpha.py`** (new focused module — **never** `repository.py`):
   - `upsert_gex_levels_for_ticker_date`, `upsert_volatility_signal_for_ticker_date`, `upsert_short_pressure_for_ticker_date` (ON CONFLICT `(ticker, market_date)` DO UPDATE).
   - `insert_dark_lit_prints`, `insert_intraday_flow_bars` (ON CONFLICT DO NOTHING — append-only).
   - Re-export for assembly compatibility only.
5. **`worker/jobs/`** + **`scheduler.py`** — one recurring capture job per table (or grouped by shape), uw-budgeted, ET-timed after close, modeled on `greek_exposure_daily_refresh`. The daily job iterates the watchlist; the shared capture fn does the per-ticker fetch → normalize → upsert.
6. **`worker/jobs/data_gap_adapters.py`** — heal adapters for the 3 daily tables (dispatch → shared per-ticker-date capture fn).
7. **`reports/data_gap_healer.py`** — 5 new `DatasetRegistryEntry` rows (3 strict, 2 freshness); regenerate `docs/runbooks/data-gap-dataset-policy.md` via `render_dataset_policy_markdown` (new-temporal-table CI gate requires the registry entry + regenerated policy in the same PR).

### Budget

Added daily UW cost ≈ **1,133 calls** (gex 103 + vol 309 + short 309 + intraday 206 + dark/lit 206), against the 120k/day governor — negligible. Healer heals also draw from the capped `uw` budget (`DATA_GAP_HEALER_MAX_UW_CALLS`, default 20,000).

## 6. Config / kill switches

Each recurring capture job gets an enable flag defaulting **off** until the catch-up lands and the mini is verified, following the repo's promotable-off convention (e.g. `UW_SCAN_UW_HISTORICAL_ALPHA_CAPTURE_ENABLED` or per-dataset flags — decided in the plan). Worker env freezes at fork, so flipping a flag needs a worker restart (kickstart).

## 7. One-time catch-up

The mini's tables hold data through 2026-07-01, abandoned since. After the recurring path is verified on local/CI:

- Run catch-up **2026-07-02 → go-live** via the new fetchers (not the branch's bare-`httpx` script), budget-capped, resumable.
- Reuse the branch's `uw_historical_alpha_backfill.py` CLI *surface* (`audit`/`plan`/`execute`/`resume`/`verify`) but back it with the standard fetchers so every call hits the memo/audit/budget plumbing.
- Persist the full coverage trace (per-dataset expected/covered/missing) to a durable artifact and record the exact reproduce command (standing research-persistence rule).

## 8. Rebase / migration mechanics

- Resume branch `misc/uw-historical-alpha-scan` in `.worktrees/uw-historical-alpha-scan/` (real `npm ci` not needed — no web changes here).
- Rebase onto main. Expected conflict: the branch's `sources/uw.py` diff vs main's #225 memo — resolved by **discarding the branch's `uw.py` change entirely** (§2).
- Renumber `095_uw_historical_alpha_tables.sql` → `108_uw_historical_alpha_tables.sql`; delete branch `096`.
- Delete the oi_change + long-weekend files and their tests (§2).
- Migrations stay idempotent (`IF NOT EXISTS`), no tracking table — re-running on the mini is a no-op.

## 9. Testing

- **Unit:** normalizers (real frozen UW payloads from `docs/uw-samples/` where available, else a captured fixture with as-of date — no synthetic values); storage upsert idempotency (daily) + insert-ignore (event logs); registry entries present + policy doc regenerated (`test_models_exports`-style + a registry assertion).
- **Integration (`pytest-postgresql`):** capture job writes expected rows; heal adapter fills a synthetically-deleted ticker-date; freshness registration surfaces staleness. No mocked DB.
- **Smoke (real worker path):** API/scheduler enqueue → DB row → worker claims → DB result, validated on the running stack (restart first — APScheduler doesn't hot-reload).

## 10. Deliverables / PR

Single PR on the resumed branch, milestone commits by dataset shape:

1. Migration `108` + storage module + normalizers.
2. Fetchers + EndpointSlugs.
3. Recurring capture jobs + scheduler wiring + config flags.
4. Healer registrations (5) + heal adapters + regenerated policy doc.
5. Catch-up CLI (on standard fetchers) + reproduce trace.
6. `[Unreleased]` CHANGELOG entry + tests.

PR before merge to main; CI green before merge; no `Co-Authored-By` trailer.

## 11. Open items resolved at implementation time

- Exact `retention_days` for `uw_short_pressure_daily` and `uw_volatility_signal_daily` — probe the live UW windows during implementation.
- Whether the 5 capture jobs are 5 separate scheduler entries or grouped by shape (2–3 jobs) — cosmetic; decide in the plan.
- Config-flag granularity (one master flag vs per-dataset) — decide in the plan.

## 12. Endpoint reality — verified 2026-07-24

Four of the eleven source endpoints (`gex-levels`, `volatility/anomaly`, `volatility/character`, `volatility/variance-risk-premium`) are **absent from argon's curated UW reference** (`docs/uw-samples/`, a documented subset of "140 accessible / 30 integrated") and from the UW MCP tool subset. A doc-grep therefore reports them as non-existent — a **false negative**. They are real: a live query of the mini's already-populated tables (populated by the branch's backfill hitting these exact paths) is dispositive:

| Table (source paths) | Rows | Non-null signal | Date range | Tickers |
|---|---|---|---|---|
| `uw_gex_levels_daily` (`/api/stock/{t}/gex-levels`) | 75,293 | 72,657 | **2023-08-03 → 2026-07-01** | 103 |
| `uw_volatility_signal_daily` (`.../volatility/{anomaly,character,variance-risk-premium}`) | 11,942 | 11,942 | 2026-01-02 → 2026-07-01 | 103 |
| `uw_short_pressure_daily` (`/api/shorts/{t}/{interest-float/v2,ftds,volumes-by-exchange}`) | 12,623 | 12,623 | 2026-01-02 → 2026-07-01 | 103 |

**Consequences for the plan:**
- Authoritative endpoint paths + response shapes come from the **proven backfill script** (`scripts/backfill/uw_historical_alpha_backfill.py` on the branch) + live re-probe, **not** the curated docs.
- The four undocumented endpoints return **non-standard payload shapes** (`gex-levels` → single `data` object with `call_wall/put_wall/gamma_flip/gamma_magnet`; `anomaly`/`character` → `data:{history:[...], latest:{...}}`; `variance-risk-premium` → trailing series), so `normalize._data_list` (which assumes `data` is a list) does **not** apply — each gets a custom normalizer modeled on the backfill parse code, with a **frozen real live response** as its test fixture (no synthetic values).
- `gex-levels` serves history back to 2023 → `retention_days=None` (full history) is confirmed correct.
- `lit-flow`'s path is top-level `/api/lit-flow/{ticker}`, not under `/api/stock/`.

## 13. Full source-endpoint table (verified)

| EndpointSlug (proposed) | Path | `?date=` | In enum today? |
|---|---|---|---|
| `GEX_LEVELS` | `/api/stock/{ticker}/gex-levels` | yes (deep history) | no — add |
| `VOLATILITY_ANOMALY` | `/api/stock/{ticker}/volatility/anomaly` | yes (~16-session window) | no — add |
| `VOLATILITY_CHARACTER` | `/api/stock/{ticker}/volatility/character` | yes (~16-session window) | no — add |
| `VOLATILITY_VRP` | `/api/stock/{ticker}/volatility/variance-risk-premium` | yes (full YTD series) | no — add |
| `NET_PREM_TICKS` | `/api/stock/{ticker}/net-prem-ticks` | yes | no — add |
| `GREEK_FLOW` | `/api/stock/{ticker}/greek-flow` | yes | no — add |
| `LIT_FLOW` | `/api/lit-flow/{ticker}` (top-level) | yes (+`limit`) | no — add |
| `FTDS` | `/api/shorts/{ticker}/ftds` | no (full history/call) | no — add |
| `VOLUMES_BY_EXCHANGE` | `/api/shorts/{ticker}/volumes-by-exchange` | probe at impl | no — add |
| `DARKPOOL_TICKER` | `/api/darkpool/{ticker}` | — | **yes** (reuse) |
| `SHORT_INTEREST_FLOAT` | `/api/shorts/{ticker}/interest-float/v2` | — | **yes** (reuse) |
