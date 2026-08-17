# Data Gap Healer — Coverage Hardening (Round 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the gap healer and the freshness monitor able to *see*, *heal*, and *finish healing* every registered dataset — closing the measurement blind spots that let a 4-day outage audit as `total_gaps = 0`, and the scheduling blind spot that lets one backlog starve every other dataset for a week.

**Architecture:** Four defects, fixed in dependency order. (1) *Measurement*: the audit's trading-day spine is a captured table, and the monitor's coverage window is anchored to each table's own newest row — both go blind exactly when capture stops. (2) *Dispatch*: heal adapters that call the wrong production writer, so the heal silently no-ops. (3) *Policy*: 45 daily tables are registered `freshness_only` with `provider="none"` on one copy-pasted assumption that is measurably false for at least 13 of them. (4) *Scheduling*: one shared UW budget with no per-dataset fairness, and an audit that re-attempts provider-refused dates forever. No new subsystem is introduced — the registry, the adapter dispatch table, `RequestBudget`, and `compute_freshness` are the only surfaces touched.

**Tech Stack:** Python 3.13 / `uv`, psycopg 3, pytest + pytest-postgresql, one idempotent SQL migration.

**Spec:** none — this plan argues from measured production state (see *Measured Evidence*), not a design doc. Round 1 (`docs/superpowers/plans/2026-08-16-historical-replay-backfill.md`) is a **sibling, not a prerequisite**, except where Task 7 says so explicitly.

## Global Constraints

- `uv run pytest` only — never bare `pytest`.
- Every registry change **must** regenerate `docs/runbooks/data-gap-dataset-policy.md` in the *same* commit (CI gate — see `tests/unit/reports/test_data_gap_dataset_policy.py`).
- Migrations are idempotent (`IF NOT EXISTS`); no tracking table. **Next free prefix is `120`** — `119` is reserved by the unmerged macro-MC1 branch, and a duplicate prefix is a CI gate.
- CI Guardrail 2: every `except` block must reference `repr(exc)`, `.exception(...)`, `traceback`, or `raise`.
- No mocked DB / fake cursors. Integration tests use the `seeded_db_empty_cards` fixture (real Postgres via pytest-postgresql).
- Never fabricate a data value under a historical stamp. A heal that cannot reconstruct a past date must verify false and record honest `no_data` — never write today's payload under yesterday's key.
- CHANGELOG `[Unreleased]` entry rides this branch before merge. Branch prefix `fix/`.
- Do not commit until the user asks.

---

## Measured Evidence

Everything below was measured against the Mac mini `option_wizard` on 2026-08-16, after the Aug 11–14 outage was backfilled. These are the facts the plan is built on; re-measure before disputing one.

**E1 — The audit only audits 9% of the desk.**
`REGISTRY` holds 143 datasets. `scan_dataset` emits gap items for `strict_ticker_date` (10) and `strict_session` (3) **only**; every other mode returns `CoverageSummary(…, 0, 0, 0, ())` and no items. So `total_gaps = 0` is a statement about **13 of 143** datasets.

```
Counter({'freshness_only': 70, 'research_artifact': 31, 'provenance': 18,
         'strict_ticker_date': 10, 'excluded': 10, 'strict_session': 3,
         'operational_state': 1})
```

**E2 — The freshness monitor scores a 4-day hole as perfect health.**
`compute_freshness` computes `covered` as *distinct tickers with a row in `[max_data_date - grace_days, max_data_date]`*, where `grace_days = 4` for `equity_session`. `frozen` is the only alarm bit and is derived from `max_data_date` alone. Latest snapshot row:

| table | expected | covered | coverage_pct | max_data_date | days_stale | frozen |
|---|---|---|---|---|---|---|
| `risk_reversal_skew_history` | 170 | 170 | **1.0000** | 2026-08-14 | 2 | **False** |

Actual per-day content of that table:

```
2026-08-06 | 174 tickers      2026-08-11 | 2 tickers
2026-08-07 | 174 tickers      2026-08-12 | 2 tickers
2026-08-10 | 173 tickers      2026-08-13 | 2 tickers
                              2026-08-14 | 2 tickers
```

Two tickers of real data on the newest date pull `max_data_date` forward, and the 4-day grace window then reaches back to Aug 10's 173 tickers to score `covered = 170`. **A partial heal makes the monitor blinder, not sharper.**

**E3 — The trading-day spine is self-blinding.**
`_REFERENCE_CALENDAR = ("market_tide_sentiment_daily", "data_date")`, and `_calendar_dates` reads that table alone. It is itself a captured dataset, so an outage deletes the evidence of its own outage. Measured during round 1: audit with the truncated spine reported **1,276** gaps; after rebuilding the spine, **8,080** — a 6.3× under-report.

**E4 — The `greek_exposure_daily` heal adapter cannot heal 11 tickers, and its docstring is wrong.**
`_run_greek_exposure` delegates to `greek_exposure_daily_refresh(..., ticker_filter=…)`. That job builds `index_set = {t.upper() for t in settings.gex_scan_tickers}` and `continue`s on a match. So healing **AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA, SPY, QQQ, IWM, TLT** — the highest-value names on the desk — selects the ticker and then skips it, returns 0, verifies false, and is recorded as `no_data`. The adapter's comment also claims *"UW aggregate is current-snapshot only → heals a same-day gap; a past date verifies false"*. Measured in round 1: `/greek-exposure/{ticker}` returns the **full ~250-row date series**; 12 calls restored 3,000 rows across all four outage dates and took the table back to 170/170.

**E5 — The registry refuses work it can already do.**
28 `options_chain` tables carry the identical reason string `"UW-retention/event-log shaped; freshness-monitored, no auto-backfill"`. It is measurably false for at least:

- `index_ohlc_daily`, `vol_index_daily` — healed in round 1 by `run_vol_index_lake_sync` / `run_credit_etf_lake_sync`.
- `uw_dark_lit_flow_prints`, `uw_intraday_option_flow_bars` — healed by `scripts/backfill/uw_alpha_catchup.py backfill-eventlog`.
- `oi_by_strike`, `max_pain_by_expiry`, `exposures_summary`, `iv_term_snapshots`, `interpolated_iv_snapshots`, `risk_reversal_skew_history`, `greeks_by_expiry_strike`, `exposures_by_expiry_strike`, `oi_by_expiry` — UW was probed directly in round 1 and returned HTTP 200 with rows for past dates. These are blocked only by missing date plumbing (round 1's job), not by the provider.

Separately, `cri_snapshots` / `vcg_snapshots` / `canary_snapshots` / `grg_snapshots` / `matrix_state_snapshots` carry `"regime scanner output; re-derive needs historical inputs (audit-only)"`, but `recover_recent_gaps(conn, schema, *, lookback_days)` exists in `scanners/cri.py`, `scanners/vcg.py` and `scanners/canary.py` and was used to heal all three this week.

**E6 — Round 1's contamination near-miss.**
`vrp_macro_signal_daily` accepts a `snapshot_date` it does not honour: `current_macro_signal(repo, settings, name, cfg)` takes no date and reads the newest data. Backfilling four dates produced four byte-identical rows (SPX spot 7785.76, `vrp_z` −1.308, `as_of` 2026-08-14 on all four); 9 rows were deleted. **Any date-looped heal over a non-date-aware writer produces lookahead-contaminated history that looks like a successful backfill.**

---

## The two heal channels (read this before wiring any adapter)

Verified by reading `worker/jobs/data_gap_healer.py:290-297` and `data_gap_adapters.py:381-417` on 2026-08-16. The healer has **exactly two** ways to run an adapter, and the registry's `granularity` field — not `audit_mode` — selects which:

| `granularity` | channel | fires when |
|---|---|---|
| `run_once`, `run_once_lookback` | `_refresh_targets()` → `run_refresh_adapters()` | **always**, independent of `audit_mode` — `_refresh_targets` filters the REGISTRY on granularity + a resolvable adapter, so wiring one auto-enrols the dataset in the nightly refresh |
| `per_ticker_date`, `per_ticker_range` | `execute_run()` over **gap items** | only when the audit produced items — and `scan_dataset` produces items for `strict_ticker_date` / `strict_session` **only** |

**Therefore: a `per_ticker_*` adapter on a `freshness_only` dataset is dead code.** It is never dispatched, no error is raised, and the dataset reads as "has an adapter" in the policy doc. This is the same silent-no-op family as Task 1's `gex_scan_tickers` skip, and the plan tripped over it twice during review (`grg_snapshots`, and the two UW event logs). Task 4 Step 9 adds the test that makes it impossible to reintroduce.

Second consequence: `strict_session` gap items carry **`ticker=None`** (`data_gap_healer.py:1191` — `GapItem(table, d.isoformat(), d, None, …)`). `_dispatch_per_ticker_date` passes that `None` straight through as the adapter's `ticker` argument, and `_verify_covered` correctly drops the ticker predicate when it is falsy. So a sessionwide adapter's `ticker` parameter is genuinely `None` in production — **not** a synthetic `"MARKET"`/`"GRG"` string. Write the adapters and their tests against `None`.

---

## Module size budget — cited, deferred deliberately

`src/uw_scan/reports/data_gap_healer.py` is **1,296 lines today**, and this plan grows it further (`SpineHealth` + `spine_health` in Task 2, `reason_verified_on` in Task 4, and ~25 registry entries edited across Tasks 4–7). CLAUDE.md: *"at 1000+ lines stop adding methods and propose a split first. Cite this rule in any PR that grows a file past 1000 lines without a split plan."* Citing it here so this is a decision, not an oversight.

**The seam, if/when it is taken:** the module is data-heavy, not method-heavy — 15 functions against ~900 lines of `DatasetRegistryEntry` literals, their bulk builders, and `SEED_CAVEATS`. Move the data (`DatasetRegistryEntry`, `Caveat`, `REGISTRY`, `SEED_CAVEATS`, `render_dataset_policy_markdown`) into `reports/data_gap_registry.py`, leaving `data_gap_healer.py` with the scan/audit logic. Re-export from the old path so `data_freshness.py`'s `_GAP_HEALER_REGISTRY` import and `data_gap_adapters.py`'s four-name import keep working.

**Deferred, on purpose.** Every edit this plan makes to that file is a *data* edit to an existing literal or one small dataclass — not the accretion of query methods that took `repository.py` to 5,000 lines, which is what the rule exists to prevent. Splitting first would put an import-churn commit in front of eight behavioural tasks and make every later diff harder to review against the pre-split file. Take the split as a standalone mechanical PR after this plan lands, when the registry has stopped moving.

## Coverage Ledger — every one of the 143 registered datasets

The plan's completeness claim, stated so it can be falsified — and asserted as a test in Task 10, so it cannot rot.

**All 143 registered datasets:**

| bucket | count | disposition |
|---|---|---|
| `research_artifact` / `provenance` / `excluded` / `operational_state` | 60 | existence-only by design — nothing to heal |
| `equity_session` / `daily` | 58 | Tasks 1–8 (detailed below) |
| weekly / monthly / event / liveness | 25 | Task 10 — 6 already wired, 3 fundamentals wired for free, 13 liveness + 3 external given **dated** refusals |

Tasks 1–8 originally scoped only the 58. That was a stated boundary, not full coverage: of the other 25, **19 had no adapter and 13 had a completely empty `reason`** — undocumented refusals of exactly the kind that proved false eight times in Tasks 4–6. Task 10 closes that, and widens the `test_every_refusal_is_dated` gate to every cadence so it cannot reopen.

**The 58-dataset daily scope in detail.** (An earlier draft said 47; that was wrong, and independent review caught it. Reproduce the count:)

```bash
uv run python -c "
from uw_scan.reports.data_gap_healer import REGISTRY
skip = ('excluded','provenance','operational_state','research_artifact')
scoped = [e for e in REGISTRY if e.audit_mode not in skip
          and e.expected_frequency in ('equity_session','daily')]
print(len(scoped), 'scoped;', sum(1 for e in scoped if e.healer_adapter), 'already wired')
"
```

| disposition | count |
|---|---|
| adapter already wired before this plan | 18 |
| adapter wired **by** this plan | 30 |
| measured refusal (provider genuinely cannot) | 5 |
| external-provider failure | 3 |
| dead table → `excluded` (`oi_by_expiry`) | 1 |
| **still uncovered** | **1** (`gex_snapshots`) |
| **total** | **58** |

**As-built, 2026-08-16 (Tasks 1–6, 9, 10 merged; Task 7 blocked on round 1):**
31 wired + 27 dated refusals = 58. The count is unchanged but its *membership*
moved twice, in offsetting directions, and both were discovered during
execution rather than planned:

- `oi_by_expiry` left the scope (Task 6 Step 6b → `excluded`; 0 rows, no writer).
- `scanner_candidate_snapshots` **entered** it. The plan filed it under the 13
  liveness entries and flagged it for a second look; the check found a
  surrogate-`id` PK, a `(ticker, scored_at DESC)` index, an explicit
  *"Append-only (no upsert) — every run accrues a new batch"* docstring, and
  7,389 production rows across 23 dates. It is a time series, not live state,
  and now carries an `equity_session` cadence with a dated refusal.

The 27 dated refusals include the 15 options-chain tables Task 7 would wire;
until round 1 ships they are honestly refused rather than silently uncovered.

| task | datasets it makes healable |
|---|---|
| already wired | `option_surface_grid_daily`, `greek_exposure_daily`, `uw_gex_levels_daily`, `uw_volatility_signal_daily`, `uw_short_pressure_daily`, `daily_ohlc`, `vrp_daily`, `stock_analytics_daily`, `realized_volatility_history`, `volatility_stats_history`, `market_tide_sentiment_daily`, `macro_series_daily`, `rates_*`, `gold_posture_daily`, `uw_gold_options_daily` |
| **1** | `greek_exposure_daily` — already registered, but the adapter silently no-ops on 11 tickers |
| **4** | `market_tide_snapshots`, `top_net_impact_snapshots`, `cri_snapshots`, `vcg_snapshots`, `canary_snapshots`, `technical_daily`, `corporate_actions`, `massive_fundamentals` |
| **5** | `grg_snapshots` |
| **6** | `vol_index_daily`, `index_ohlc_daily`, `uw_dark_lit_flow_prints`, `uw_intraday_option_flow_bars`; `oi_by_expiry` → `excluded` |
| **7** (gated) | `oi_by_strike`, `oi_change_events`, `greeks_by_expiry_strike`, `exposures_by_expiry_strike`, `exposures_summary`, `iv_term_snapshots`, `interpolated_iv_snapshots`, `risk_reversal_skew_history`, `max_pain_by_expiry`, `pcr_history`, `dark_pool_events`, `option_contract_snapshots` (via `replay`); `iv_rank_history`, `option_chain_per_strike`, `matrix_state_snapshots` (via `cockpit_replay`); `option_intraday_buckets` and `iv_smile_snapshots` (cascades) |

**Audit-mode promotions this plan requires** — wiring an adapter is only half the job; a `per_ticker_*` adapter needs a `strict_*` audit mode or it is never dispatched (see the two-channel section above). Three entries change mode:

| dataset | from | to | why |
|---|---|---|---|
| `grg_snapshots` | `freshness_only` | `strict_session` | one marketwide row/day, keyed `data_date`; Task 5's `grg_as_of` is `per_ticker_date` |
| `uw_dark_lit_flow_prints` | `freshness_only` | `strict_ticker_date` | keyed `(ticker, market_date)`; Task 6's `uw_alpha_dark_lit` is `per_ticker_date` |
| `uw_intraday_option_flow_bars` | `freshness_only` | `strict_ticker_date` | same |

Task 7 promotes a further 16. Everything else keeps its mode: the Task 4 adapters are all `run_once*`, which the refresh channel dispatches regardless of audit mode.

**Measured refusals (5)** — kept refused, now with `reason_verified_on`: `flow_events`, `flow_alerts_daily_rollup`, `short_interest_snapshots`, `uw_positioning`, `options_volume_daily`. UW returns byte-identical bodies across `date` values; replaying them would be fabrication.

**External-provider failures (3 in scope)** — outside the healer's reach: `etf_holdings_daily`, `etf_flows_daily`, `etf_aum_cache` (the source needs an auth cookie and has no historical API). `exchange_inventory_daily` (CME 403 since 2026-06-01) and the monthly `wgc_etf_monthly` / `cb_gold_reserves_monthly` are equally broken but fall outside the daily/equity_session scope counted above.

**Still uncovered (1) — `gex_snapshots`.** `scanners/gex.py::run(client, repo, ticker="SPX")` takes no date, and unlike GRG it is not a truncate-the-series fix: `run` fetches IV-rank rows *and* resolves a live spot it raises without. Giving it an `as_of` means finding a historical spot for every scan ticker, which is a different piece of work from this plan. Two honest options, and **the executor must pick one and record it rather than leaving the entry as-is**:

1. Register a dated refusal — `reason="scanners.gex.run resolves a live spot and raises without one; historical replay needs a spot source per (ticker, date)"`, `reason_verified_on=date(2026, 8, 16)`. Costs nothing, tells the truth, and the `test_every_refusal_is_dated` gate in Task 6 accepts it.
2. Extend Task 5's `as_of` pattern to `gex.run`, sourcing spot from `daily_ohlc`/`index_ohlc_daily` at `as_of`. Real work, real payoff — `gex_snapshots` currently sits in the frozen list.

Default to (1) unless the reviewer says otherwise: the plan's job is to stop the healer *lying* about coverage, and a dated refusal is an honest answer. (2) is a follow-up, not a prerequisite.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/uw_scan/worker/jobs/data_gap_adapters.py` | heal dispatch; fix `_run_greek_exposure`, add regime/lake/event-log adapters, add the identical-payload guard | 1, 4, 5, 6, 7 |
| `src/uw_scan/reports/data_gap_healer.py` | spine union + `spine_health`; `reason_verified_on` field (T4); adapter/audit-mode entries | 2, 4, 5, 6, 7 |
| `src/uw_scan/worker/jobs/data_gap_healer.py` | `_heal_datasets` gate so a disabled replay heal skips instead of failing | 7 |
| `tests/unit/reports/test_no_dead_adapters.py` | the granularity/audit-mode coherence gate | 4 |
| `src/uw_scan/reports/data_freshness.py` | coverage measured per expected session; `sessions_missing` | 3 |
| `src/uw_scan/worker/jobs/data_freshness_monitor.py` | alarm on `sessions_missing` | 3 |
| `src/uw_scan/storage/data_freshness_repository.py` | persist `sessions_missing` | 3 |
| `src/uw_scan/storage/migrations/120_freshness_sessions_missing.sql` | new column | 3 |
| `src/uw_scan/scanners/grg.py` | `as_of` truncation | 5 |
| `scripts/backfill/data_gap_healer.py` | spine-degraded banner (no new flag — Task 4's `market_tide` adapter repairs the reference automatically) | 2 |
| `docs/runbooks/data-gap-dataset-policy.md` | regenerated after every registry change | 4, 5, 6, 7 |
| `src/uw_scan/storage/data_gap_healer_repository.py` | `count_recent_no_data` for the auto-caveat | 9 |
| `src/uw_scan/config.py` | replay gate (T7), dataset share + no-data caveat threshold (T9) | 7, 9 |
| `tests/unit/reports/test_full_coverage.py` | the 143-dataset disposition claim, as a test | 10 |
| `docs/research/2026-08-16-healer-coverage-before-after.md` | measured before/after artifact | 8 |

Tasks 1–6 are independent of round 1 and of each other except where noted; Task 7 is explicitly gated on round 1 shipping.

---

### Task 1: `greek_exposure_daily` heal stops skipping the 11 highest-value tickers

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py:148-163`
- Test: `tests/integration/worker/test_data_gap_adapters_gex.py` (create)

**Interfaces:**
- Consumes: `uw_scan.scanners.gex.fetch_aggregate_gex(client, repo, run_id, ticker) -> list[dict]` — rows keyed **`date`**; `GreekExposureDailyRepository(conn, schema=…).upsert_rows(ticker, rows) -> int` — requires **`trade_date`**. The adapter must map between them (see Step 3).
- Produces: `_run_greek_exposure(ctx, ticker, lo, hi) -> int` — granularity moves from `per_ticker_date` to **`per_ticker_range`** in both `HEAL_SPECS` and the registry entry.

**Why the granularity changes too.** UW's aggregate returns the whole ~250-row series in one call, so the per-*date* contract re-fetches it once per missing day: 11 tickers × 4 outage dates = 44 identical calls where 11 suffice. `_dispatch_per_ticker_range` already groups items by ticker, invokes the adapter once with `(min(dates), max(dates))`, then verifies each item separately — exactly the right shape for a full-series fetch. `lo`/`hi` are accepted and unused (the upsert writes the whole series regardless); that is deliberate, not an oversight.

**Not a concern:** minting a `scan_runs` row per heal cannot shadow a ticker's real full-scan. `latest_run_id` selects on `aggregates IS NOT NULL` rather than a `notes` denylist (`storage/scan_runs.py:19-39`), and only `pipeline.run_single_stock` writes `aggregates`, so side-channel runs are ignored automatically.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_data_gap_adapters_gex.py`:

```python
"""_run_greek_exposure must heal gex_scan_tickers (E4)."""

from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    RequestBudget,
    _run_greek_exposure,
)


class _StubUw:
    """Returns UW's real aggregate shape: a full date series, not one row."""

    def __init__(self) -> None:
        self.calls: list[str] = []


def test_heals_a_gex_scan_ticker(seeded_db_empty_cards, monkeypatch) -> None:
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    # AAPL is in settings.gex_scan_tickers -> the old adapter skipped it.
    assert "AAPL" in {t.upper() for t in settings.gex_scan_tickers}

    # The parser's REAL key is `date`, not `trade_date`. Stubbing `trade_date`
    # here would make the test pass while production raises KeyError — the exact
    # way a test masks a contract error.
    series = [
        {"date": date(2026, 8, 11), "call_gex": 1.0, "put_gex": -2.0},
        {"date": date(2026, 8, 12), "call_gex": 3.0, "put_gex": -4.0},
    ]
    monkeypatch.setattr(
        "uw_scan.scanners.gex.fetch_aggregate_gex",
        lambda client, r, run_id, ticker: series,
    )

    ctx = HealContext(
        repo=repo,
        gap=None,
        schema=settings.db_schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )
    ctx._uw = _StubUw()  # uw_client() returns it without building a real client

    written = _run_greek_exposure(ctx, "AAPL", date(2026, 8, 11), date(2026, 8, 12))

    assert written == 2
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.greek_exposure_daily "
            "WHERE UPPER(ticker) = 'AAPL' AND trade_date IN (%s, %s)",
            (date(2026, 8, 11), date(2026, 8, 12)),
        )
        assert cur.fetchone()[0] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_data_gap_adapters_gex.py -v`
Expected: FAIL — `written == 0` (the nightly job's `index_set` guard skips AAPL and returns nothing).

- [ ] **Step 3: Replace the adapter body**

In `src/uw_scan/worker/jobs/data_gap_adapters.py`, replace the whole `_run_greek_exposure` function:

```python
def _run_greek_exposure(ctx: HealContext, ticker: str, lo: date, hi: date) -> int:
    """Heal a ticker's whole range from UW's aggregate greek-exposure series.

    `lo`/`hi` are accepted for the per_ticker_range contract and intentionally
    unused: one call returns the full series, so the upsert covers every
    missing date at once.

    Measured 2026-08-16: `/greek-exposure/{ticker}` returns the FULL ~250-row
    date series, so PAST dates heal from the same single call — the previous
    "current-snapshot only" comment here was wrong.

    The nightly `greek_exposure_daily_refresh` job is deliberately NOT reused:
    it skips `settings.gex_scan_tickers` (11 mega-caps + ETFs) to avoid
    double-fetching with the regime GEX scan, which made exactly those names
    unhealable while `skipped_index` made the skip look intentional.
    """
    from uw_scan.scanners.gex import fetch_aggregate_gex
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository

    client = ctx.uw_client()
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer_gex")
    try:
        rows = fetch_aggregate_gex(client, ctx.repo, run_id, ticker)
        # KEY MISMATCH, verified 2026-08-16: parse_greek_exposure_history emits
        # `date` (cards/greek_exposure_history.py:27-29) but upsert_rows does a
        # bare r["trade_date"] (storage/greek_exposure_repository.py:25). Passing
        # the parser's rows straight through raises KeyError on the first real
        # call. Map it here — do NOT "fix" the parser, the chart read-path reads
        # `date`.
        rows = [{**r, "trade_date": r["date"]} for r in rows if r.get("date")]
        written = GreekExposureDailyRepository(
            ctx.repo.conn, schema=ctx.schema
        ).upsert_rows(ticker, rows)
        ctx.repo.finish_scan_run(run_id, status="ok")
        return written
    except Exception as exc:  # noqa: BLE001
        ctx.repo.finish_scan_run(run_id, status="error")
        logger.warning("gex heal failed for %s: %s", ticker, repr(exc))
        raise
```

- [ ] **Step 4: Flip the granularity in BOTH places**

`HEAL_SPECS["greek_exposure_daily"]` currently declares `"per_ticker_date"`; change it to `"per_ticker_range"`. Then change the same field on the `greek_exposure_daily` REGISTRY entry in `src/uw_scan/reports/data_gap_healer.py`. They must agree — `_refresh_targets` reads the registry's copy while `_DISPATCH` reads the spec's, so a mismatch routes the dataset through the wrong channel. Task 4 Step 8's `test_registry_granularity_matches_its_adapter` enforces this.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_data_gap_adapters_gex.py -v`
Expected: PASS

- [ ] **Step 6: Confirm nothing else depended on the old delegation**

Run: `uv run pytest tests/unit/reports/test_data_gap_healer_specs.py tests/integration/scripts/ -v`
Expected: PASS. The nightly `greek_exposure_daily_refresh` job is untouched — its index guard is correct *there* (the regime scan does fetch those names live); only the heal path needed its own writer.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py src/uw_scan/reports/data_gap_healer.py \
        tests/integration/worker/test_data_gap_adapters_gex.py
git commit -m "fix(healer): gex heal writes its own rows instead of no-opping on gex_scan_tickers"
```

---

### Task 2: The spine gains a second, independently-sourced witness

**Files:**
- Modify: `src/uw_scan/reports/data_gap_healer.py:1038-1085`
- Modify: `scripts/backfill/data_gap_healer.py:86-114` (`cmd_audit`)
- Test: `tests/integration/reports/test_data_gap_spine.py` (create)

**Interfaces:**
- Produces: `spine_health(conn, schema, start, end) -> SpineHealth`, a frozen dataclass with fields `ref_sessions: int`, `witness_sessions: int`, `missing_from_ref: tuple[date, ...]`. Task 8 reads it; the CLI prints it.

**Why a witness and not a holiday table.** The spine's failure mode is that it is *captured*, so it dies with the desk. `daily_ohlc` for SPY comes from **massive** — a different provider from UW — and is already `strict_ticker_date` with a working `daily_ohlc` heal adapter. So the witness is both independent of the outage's usual cause *and* repairable by one free call. A hardcoded NYSE holiday list was considered and rejected: it is standing data to maintain, and neither `pandas_market_calendars` nor `exchange_calendars` is installed (pandas' `USFederalHolidayCalendar` is wrong for NYSE — it misses Good Friday and adds Columbus/Veterans Day). Massive only publishes bars on real sessions, so unioning it cannot manufacture the phantom weekend/holiday entries the original "no self-union" docstring was guarding against. This is not a novel choice: `scanners/cri.py::_spy_dates` already reads `daily_ohlc WHERE ticker = 'SPY'` as CRI's own trading-day anchor.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/reports/test_data_gap_spine.py`:

```python
"""The spine must survive a truncated reference table (E3)."""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_healer import _calendar_dates, spine_health

SESSIONS = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]


def _seed(repo, *, ref_dates, spy_dates) -> None:
    with repo.conn.cursor() as cur:
        for d in ref_dates:
            # state/magnitude/driver/momentum/bars are NOT NULL with no default.
            cur.execute(
                "INSERT INTO uw_scan.market_tide_sentiment_daily "
                "(data_date, state, magnitude, driver, momentum, bars) "
                "VALUES (%s, 'BALANCED', 'FLAT', 'seed', 'seed', 1) "
                "ON CONFLICT DO NOTHING",
                (d,),
            )
        for d in spy_dates:
            cur.execute(
                "INSERT INTO uw_scan.daily_ohlc "
                "(ticker, date, close, source) VALUES ('SPY', %s, 100, 'massive') "
                "ON CONFLICT DO NOTHING",
                (d,),
            )
        repo.conn.commit()


def test_spine_survives_a_truncated_reference(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    # The outage shape: the reference lost Aug 11-12, massive still has them.
    _seed(repo, ref_dates=SESSIONS[:1], spy_dates=SESSIONS)

    cal = _calendar_dates(repo.conn, "uw_scan", SESSIONS[0], SESSIONS[-1])
    assert cal == SESSIONS, "witness must restore the sessions the reference lost"


def test_spine_health_names_the_missing_reference_days(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo, ref_dates=SESSIONS[:1], spy_dates=SESSIONS)

    health = spine_health(repo.conn, "uw_scan", SESSIONS[0], SESSIONS[-1])
    assert health.ref_sessions == 1
    assert health.witness_sessions == 3
    assert health.missing_from_ref == (SESSIONS[1], SESSIONS[2])


def test_healthy_spine_reports_nothing_missing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo, ref_dates=SESSIONS, spy_dates=SESSIONS)

    health = spine_health(repo.conn, "uw_scan", SESSIONS[0], SESSIONS[-1])
    assert health.missing_from_ref == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/reports/test_data_gap_spine.py -v`
Expected: FAIL — `ImportError: cannot import name 'spine_health'`, and `_calendar_dates` returns only `[2026-08-10]`.

- [ ] **Step 3: Implement the union + health probe**

In `src/uw_scan/reports/data_gap_healer.py`, add next to `_REFERENCE_CALENDAR`:

```python
_REFERENCE_CALENDAR = ("market_tide_sentiment_daily", "data_date")
# Second, independently-sourced witness. massive publishes SPY bars only on
# real sessions, so unioning it cannot manufacture a weekend/holiday entry —
# and because it is a DIFFERENT provider from UW, a UW outage cannot blind it.
_SPINE_WITNESS = ("daily_ohlc", "date", "ticker", "SPY")


@dataclass(frozen=True)
class SpineHealth:
    """How much of the expected-session spine the reference table is missing."""

    ref_sessions: int
    witness_sessions: int
    missing_from_ref: tuple[date, ...]
```

Replace the body of `_calendar_dates` (keep its signature):

```python
def _calendar_dates(
    conn: Connection,
    schema: str,
    start: date,
    end: date,
) -> list[date]:
    """Trading-day calendar in [start, end] from two independent witnesses.

    The reference (market_tide_sentiment_daily) is itself CAPTURED, so an
    outage that stops capture also erases the evidence of the outage and every
    dataset then audits as 100% covered for exactly the days that were lost
    (measured 2026-08-16: 1,276 gaps reported vs 8,080 real). SPY's massive
    OHLC is the second witness: different provider, session-only bars, and
    already healable via the `daily_ohlc` adapter.
    """
    ref_tbl, ref_col = _REFERENCE_CALENDAR
    wit_tbl, wit_col, wit_tcol, wit_ticker = _SPINE_WITNESS
    query = psql.SQL(
        """
        SELECT d FROM (
            SELECT DISTINCT {rcol} AS d FROM {rtbl}
             WHERE {rcol} BETWEEN %s AND %s AND {rcol} IS NOT NULL
            UNION
            SELECT DISTINCT {wcol} AS d FROM {wtbl}
             WHERE {wcol} BETWEEN %s AND %s AND UPPER({wtcol}) = %s
        ) spine ORDER BY d
        """
    ).format(
        rcol=psql.Identifier(ref_col),
        rtbl=psql.Identifier(schema, ref_tbl),
        wcol=psql.Identifier(wit_col),
        wtbl=psql.Identifier(schema, wit_tbl),
        wtcol=psql.Identifier(wit_tcol),
    )
    with conn.cursor() as cur:
        cur.execute(query, (start, end, start, end, wit_ticker))
        return [r[0] for r in cur.fetchall()]


def spine_health(
    conn: Connection, schema: str, start: date, end: date
) -> SpineHealth:
    """Sessions the witness has that the reference lost — the outage signature."""
    ref_tbl, ref_col = _REFERENCE_CALENDAR
    wit_tbl, wit_col, wit_tcol, wit_ticker = _SPINE_WITNESS
    with conn.cursor() as cur:
        cur.execute(
            psql.SQL(
                "SELECT DISTINCT {rcol} FROM {rtbl} "
                "WHERE {rcol} BETWEEN %s AND %s AND {rcol} IS NOT NULL"
            ).format(
                rcol=psql.Identifier(ref_col), rtbl=psql.Identifier(schema, ref_tbl)
            ),
            (start, end),
        )
        ref = {r[0] for r in cur.fetchall()}
        cur.execute(
            psql.SQL(
                "SELECT DISTINCT {wcol} FROM {wtbl} "
                "WHERE {wcol} BETWEEN %s AND %s AND UPPER({wtcol}) = %s"
            ).format(
                wcol=psql.Identifier(wit_col),
                wtbl=psql.Identifier(schema, wit_tbl),
                wtcol=psql.Identifier(wit_tcol),
            ),
            (start, end, wit_ticker),
        )
        wit = {r[0] for r in cur.fetchall()}
    return SpineHealth(len(ref), len(wit), tuple(sorted(wit - ref)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/reports/test_data_gap_spine.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Make `audit` loud about a degraded spine**

In `scripts/backfill/data_gap_healer.py`, inside `cmd_audit`, immediately after the connection is open and before calling `audit(...)`:

```python
    from uw_scan.reports.data_gap_healer import spine_health

    health = spine_health(conn, settings.db_schema, start, end)
    if health.missing_from_ref:
        print(
            f"!! SPINE DEGRADED: {ref_name} is missing "
            f"{len(health.missing_from_ref)} session(s) the SPY witness has: "
            + ", ".join(d.isoformat() for d in health.missing_from_ref)
        )
        print(
            "!! The union keeps this audit correct, but rebuild the reference "
            "before trusting any OTHER report:\n"
            "     uv run python scripts/backfill/market_tide_backfill.py --confirm --sessions 10\n"
            "     uv run python scripts/backfill/market_tide_sentiment_backfill.py"
        )
```

where `ref_name` is `_REFERENCE_CALENDAR[0]`. Import both names at the top of the function.

- [ ] **Step 6: Run the CLI test suite**

Run: `uv run pytest tests/integration/scripts/test_data_gap_healer_cli.py -v`
Expected: PASS

- [ ] **Step 6b: Note the one way the witness can lie**

If massive ever publishes a SPY bar on a non-session, the union manufactures a phantom trading day, and every strict dataset then reports a gap for it — which the healer will spend UW budget trying to fill. This is the exact failure the original "no self-union" docstring guarded against, and the union narrows it (one curated symbol from a daily-bar provider) rather than eliminating it.

Do **not** add code for this. The registry already has the right mechanism: a `Caveat(dataset=…, ticker=None, start_date=d, end_date=d, reason="not a trading session")` suppresses the expected pair. Record that in the `_calendar_dates` docstring so whoever hits it knows the tool exists:

```python
    A phantom session (a witness bar on a non-trading day) is handled by a
    Caveat row, not by code — see SEED_CAVEATS.
```

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/reports/data_gap_healer.py scripts/backfill/data_gap_healer.py tests/integration/reports/test_data_gap_spine.py
git commit -m "fix(healer): spine unions an independent SPY witness so an outage cannot erase its own evidence"
```

---

### Task 3: Freshness measures coverage per expected session, not against the table's own newest row

**Files:**
- Create: `src/uw_scan/storage/migrations/120_freshness_sessions_missing.sql`
- Modify: `src/uw_scan/reports/data_freshness.py:69-79` (`FreshnessRow`), `299-398` (`compute_freshness`)
- Modify: `src/uw_scan/storage/data_freshness_repository.py:31-54`
- Modify: `src/uw_scan/worker/jobs/data_freshness_monitor.py:176-205`
- Test: `tests/integration/reports/test_data_freshness_sessions.py` (create)

**Interfaces:**
- Consumes: `_calendar_dates(conn, schema, start, end)` from Task 2.
- Produces: `FreshnessRow.sessions_missing: int | None` — count of the last `_COVERAGE_SESSIONS` (5) expected sessions whose distinct-ticker coverage is below `LOW_COVERAGE_PCT`. `None` for ticker-less tables. Task 8 reads it.

**Design note — why add a field instead of redefining `coverage_pct`.** `coverage_pct`'s grace window is *deliberate*: a table that legitimately lags one session should not cry wolf. The bug is that the same window also swallows a 4-session hole once any row lands on the newest date (E2). Keeping `coverage_pct` as-is and adding a per-session counter preserves the tolerance, catches the hole, and does not touch the `/api/health` contract or the autoheal circuit breaker.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/reports/test_data_freshness_sessions.py`:

```python
"""A partial heal must not read as full coverage (E2)."""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import MonitoredTable, compute_freshness

SESSIONS = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)]
TICKERS = [f"T{i:03d}" for i in range(20)]


def _seed_spine(repo) -> None:
    with repo.conn.cursor() as cur:
        for d in SESSIONS:
            cur.execute(
                "INSERT INTO uw_scan.daily_ohlc (ticker, date, close, source) "
                "VALUES ('SPY', %s, 100, 'massive') ON CONFLICT DO NOTHING",
                (d,),
            )
        repo.conn.commit()


def _seed_skew(repo, rows: list[tuple[date, str]]) -> None:
    with repo.conn.cursor() as cur:
        for d, t in rows:
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry) VALUES (%s, %s, 25, %s) "
                "ON CONFLICT DO NOTHING",
                (t, d, date(2026, 9, 18)),
            )
        repo.conn.commit()


def test_partial_heal_is_reported_as_missing_sessions(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spine(repo)
    # The production shape: full coverage on the first session, 2 tickers after.
    rows = [(SESSIONS[0], t) for t in TICKERS]
    rows += [(d, t) for d in SESSIONS[1:] for t in TICKERS[:2]]
    _seed_skew(repo, rows)

    out = compute_freshness(
        repo.conn,
        "uw_scan",
        [MonitoredTable("risk_reversal_skew_history", "watchlist", None)],
        TICKERS,
        today=SESSIONS[-1],
    )
    row = out[0]
    assert row.sessions_missing == 3, "Aug 11/12/13 each hold 2 of 20 tickers"


def test_full_coverage_reports_zero_missing_sessions(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spine(repo)
    _seed_skew(repo, [(d, t) for d in SESSIONS for t in TICKERS])

    out = compute_freshness(
        repo.conn,
        "uw_scan",
        [MonitoredTable("risk_reversal_skew_history", "watchlist", None)],
        TICKERS,
        today=SESSIONS[-1],
    )
    assert out[0].sessions_missing == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/reports/test_data_freshness_sessions.py -v`
Expected: FAIL — `AttributeError: 'FreshnessRow' object has no attribute 'sessions_missing'`

- [ ] **Step 3: Write the migration**

Create `src/uw_scan/storage/migrations/120_freshness_sessions_missing.sql`:

```sql
-- 120_freshness_sessions_missing.sql
-- Per-session coverage counter for the freshness monitor. The existing
-- coverage_pct is measured within grace_days of the table's OWN max_data_date,
-- so a single healed ticker on the newest date scores a multi-session hole as
-- 100% covered (measured 2026-08-16 on risk_reversal_skew_history: 170/170
-- reported while Aug 11-14 each held 2 of 170 tickers).
ALTER TABLE uw_scan.data_freshness_snapshots
  ADD COLUMN IF NOT EXISTS sessions_missing INTEGER;
```

- [ ] **Step 4: Add the field and compute it**

In `src/uw_scan/reports/data_freshness.py`, add to `FreshnessRow` (last field, defaulted so existing constructions keep working):

```python
    sessions_missing: int | None = None
```

Add near `_FREQUENCY_GRACE_DAYS`:

```python
# How many recent expected sessions the per-session coverage check looks at.
_COVERAGE_SESSIONS = 5
```

Hoist the spine query **above** the `for mt in monitored:` loop — it is identical for all 54 tables and re-running it per table is 54 redundant scans:

```python
    # Expected sessions, resolved ONCE for the whole run (identical per table).
    calendar_recent = _calendar_dates(
        conn, schema, today - timedelta(days=_COVERAGE_SESSIONS * 3), today
    )[-_COVERAGE_SESSIONS:]
```

Then, after `coverage_pct` is computed and before the final `FreshnessRow(...)` append, insert:

```python
        # Per-session coverage: the grace window above is anchored to the
        # table's OWN newest row, so one healed ticker on the newest date drags
        # max_data_date forward and the window then reaches back over the hole.
        # Count expected sessions that are genuinely under-covered instead.
        sessions_missing: int | None = None
        recent = calendar_recent
        if recent and expected:
            perq = psql.SQL(
                "SELECT s.d, COUNT(DISTINCT UPPER(a.{tcol}))::int "
                "  FROM unnest(%s::date[]) AS s(d) "
                "  LEFT JOIN {tbl} a "
                "         ON a.{dcol} = s.d AND UPPER(a.{tcol}) = ANY(%s) "
                " GROUP BY s.d"
            ).format(
                dcol=psql.Identifier(date_col),
                tcol=psql.Identifier(tcol),
                tbl=psql.Identifier(schema, mt.name),
            )
            with conn.cursor() as cur:
                cur.execute(perq, (recent, list(expected)))
                per_session = cur.fetchall()
            sessions_missing = sum(
                1 for _, n in per_session if n < expected_count * LOW_COVERAGE_PCT
            )
```

Add the imports this needs at the top of the module: `from datetime import timedelta` and `from uw_scan.reports.data_gap_healer import _calendar_dates` (the module already imports `_GAP_HEALER_REGISTRY` from there, so no new dependency edge is created). Import `LOW_COVERAGE_PCT` from `uw_scan.worker.jobs.data_freshness_monitor` would be circular — instead **move** `LOW_COVERAGE_PCT = 0.5` into `data_freshness.py` and re-import it in the monitor:

```python
# data_freshness_monitor.py
from uw_scan.reports.data_freshness import (
    MONITORED_TABLES,
    LOW_COVERAGE_PCT,
    FreshnessRow,
    compute_freshness,
)
```

Then pass `sessions_missing=sessions_missing` in both the ticker-ful `FreshnessRow(...)` construction and leave the two early-return constructions at their `None` default.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/reports/test_data_freshness_sessions.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Persist and alarm on it**

In `src/uw_scan/storage/data_freshness_repository.py`, add `"sessions_missing": r.sessions_missing` to the row dict, `sessions_missing` to the INSERT column list, `%(sessions_missing)s` to the VALUES list, and `sessions_missing = EXCLUDED.sessions_missing` to the ON CONFLICT SET.

In `src/uw_scan/worker/jobs/data_freshness_monitor.py`, add a third branch after the `elif r.coverage_pct ... < LOW_COVERAGE_PCT:` block:

```python
        elif r.sessions_missing:
            logger.warning(
                "data_freshness: %s UNDER-COVERED — %d of the last %d expected "
                "sessions below %.0f%% coverage (newest data %s reads full)",
                r.table_name,
                r.sessions_missing,
                _COVERAGE_SESSIONS,
                LOW_COVERAGE_PCT * 100,
                r.max_data_date,
            )
```

Import `_COVERAGE_SESSIONS` alongside `LOW_COVERAGE_PCT`.

- [ ] **Step 7: Run the full freshness + health suites**

Run: `uv run pytest tests/integration/storage/test_data_freshness_repository.py tests/integration/api/test_health_freshness.py tests/unit/reports/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/storage/migrations/120_freshness_sessions_missing.sql \
        src/uw_scan/reports/data_freshness.py \
        src/uw_scan/storage/data_freshness_repository.py \
        src/uw_scan/worker/jobs/data_freshness_monitor.py \
        tests/integration/reports/test_data_freshness_sessions.py
git commit -m "fix(freshness): count under-covered expected sessions so a partial heal stops reading as 100%"
```

---

### Task 4: Wire every adapter that already has a date-aware entrypoint

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (8 adapters + `HEAL_SPECS` entries)
- Modify: `src/uw_scan/reports/data_gap_healer.py` (`reason_verified_on` field + 9 registry entries)
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerate)
- Test: `tests/integration/worker/test_data_gap_adapters_existing.py` (create)

**Why these are one task.** Every dataset below is blocked by *nothing*: a production writer that already accepts the date (or already recomputes its full history) exists and is being ignored by the registry. There is no new logic in this task — only wiring — so a reviewer either accepts the whole "stop refusing work we can already do" change or rejects it. Verified by reading each signature on 2026-08-16:

| dataset | existing entrypoint | shape | new code |
|---|---|---|---|
| `market_tide_snapshots` | `scanners.market_tide.run(client, repo, *, spot_ticker="SPY", trading_date=None, capture_spot=True)` | per-date | **none** |
| `top_net_impact_snapshots` | `scanners.top_net_impact.run(client, repo, *, trading_date=None, limit=40)` | per-date | **none** |
| `cri_snapshots` | `scanners.cri.recover_recent_gaps(conn, schema, *, lookback_days=7)` | lookback | **none** |
| `vcg_snapshots` | `scanners.vcg.recover_recent_gaps(conn, schema, *, proxy=…, lookback_days=7)` | lookback | **none** |
| `canary_snapshots` | `scanners.canary.recover_recent_gaps(conn, schema, *, lookback_days=7)` | lookback | **none** |
| `technical_daily` | `worker.jobs.technical_daily_refresh.technical_daily_refresh(*, repo, settings, ticker_filter=None)` | run_once | **none** |
| `corporate_actions` | `worker.jobs.corporate_actions_jobs.corporate_actions_refresh_once(repo, provider, *, ticker_filter=None, …)` | run_once | **none** |
| `massive_fundamentals` | `worker.jobs.fundamentals_jobs.fundamentals_refresh_once(repo, provider, *, ticker_filter=None)` | run_once | **none** |

**`market_tide_snapshots` is the important one — it closes the spine loop.** Task 2 gives the audit a second witness so a truncated reference can no longer hide an outage; this entry lets the healer *repair* the reference itself, unattended. `market_tide.run` has taken `trading_date` all along and even documents the backfill mode (`capture_spot=False` — "a current spot is meaningless against a past bar"), while the registry said `"UW market-tide is current-session; historical heal TODO"`. Round 1 measured that false: UW served all four outage dates with full 81–82 bar sessions.

**`iv_smile_snapshots` was in this task and has been moved to Task 7** — review caught a wrong writer binding. It *is* derived rather than UW-retention-shaped (`build_iv_smile_snapshot_rows` over `greeks_by_expiry_strike`; 700,540 rows, newest `market_date` 2026-08-16, so live not legacy), but the enclosing function is `run_volatility_backfill` (`reports/volatility_series.py:487`), **not** `nightly_vol_analytics_rollup` — that rollup imports only `_fill_rv_from_price`, `persist_stock_analytics` and `persist_vrp_daily` (`worker/volatility_jobs.py:45-55`) and never touches the smile. Pointing it at the existing `vol_analytics_rollup` adapter would have been a silent no-op. It also cascades off `greeks_by_expiry_strike`, which Task 7 heals, so that is where it belongs.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_data_gap_adapters_existing.py`:

```python
"""Adapters over entrypoints that were already date-aware (E5)."""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget


def _ctx(repo, settings) -> HealContext:
    return HealContext(
        repo=repo,
        gap=None,
        schema=settings.db_schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )


@pytest.mark.parametrize(
    "adapter,module,provider",
    [
        ("cri_recover", "uw_scan.scanners.cri", "db"),
        ("vcg_recover", "uw_scan.scanners.vcg", "db"),
        ("canary_recover", "uw_scan.scanners.canary", "db"),
    ],
)
def test_recover_adapter_forwards_the_lookback(
    seeded_db_empty_cards, monkeypatch, adapter, module, provider
) -> None:
    seen: dict = {}

    def _fake(conn, schema="uw_scan", **kw):
        seen["schema"] = schema
        seen["lookback_days"] = kw["lookback_days"]
        return {"checked": 3, "filled": 2, "skipped": 1}

    monkeypatch.setattr(f"{module}.recover_recent_gaps", _fake)
    settings = Settings.from_env()
    spec = HEAL_SPECS[adapter]
    assert (spec.granularity, spec.provider) == ("run_once_lookback", provider)

    assert spec.run(_ctx(seeded_db_empty_cards, settings), 9) == 2
    assert seen == {"schema": settings.db_schema, "lookback_days": 9}


@pytest.mark.parametrize(
    "adapter,target",
    [
        ("market_tide", "uw_scan.scanners.market_tide.run"),
        ("top_net_impact", "uw_scan.scanners.top_net_impact.run"),
    ],
)
def test_per_date_adapter_forwards_the_trading_date(
    seeded_db_empty_cards, monkeypatch, adapter, target
) -> None:
    seen: dict = {}

    def _fake(client, repo, **kw):
        seen.update(kw)
        return 81

    monkeypatch.setattr(target, _fake)
    settings = Settings.from_env()
    ctx = _ctx(seeded_db_empty_cards, settings)
    ctx._uw = object()

    # strict_session gap items carry ticker=None — pass what production passes.
    assert HEAL_SPECS[adapter].run(ctx, None, date(2026, 8, 12)) == 81
    assert seen["trading_date"] == date(2026, 8, 12)


def test_market_tide_backfill_does_not_stamp_a_live_spot(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """A current spot against a past bar is fabricated history, not a backfill."""
    seen: dict = {}
    monkeypatch.setattr(
        "uw_scan.scanners.market_tide.run",
        lambda client, repo, **kw: seen.update(kw) or 81,
    )
    settings = Settings.from_env()
    ctx = _ctx(seeded_db_empty_cards, settings)
    ctx._uw = object()

    HEAL_SPECS["market_tide"].run(ctx, None, date(2026, 8, 12))
    assert seen["capture_spot"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_data_gap_adapters_existing.py -v`
Expected: FAIL — `KeyError: 'cri_recover'`

- [ ] **Step 3: Add the adapters**

In `src/uw_scan/worker/jobs/data_gap_adapters.py`, after `_run_gold_uw_options`:

```python
# --- entrypoints that were already date-aware -------------------------------
# Every adapter below wraps a production writer that ALREADY accepts the date
# (or already recomputes its full history). The registry refused all of them on
# an assumption that round 1 measured false on 2026-08-16.


def _run_cri_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import cri

    out = cri.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_vcg_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import vcg

    out = vcg.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_canary_recover(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.scanners import canary

    out = canary.recover_recent_gaps(
        ctx.repo.conn, ctx.schema, lookback_days=max(1, lookback_days)
    )
    return int(out.get("filled", 0))


def _run_market_tide(ctx: HealContext, ticker: str | None, market_date: date) -> int:
    """Sessionwide dataset — `ticker` is None (strict_session items carry no
    ticker); accepted and ignored to satisfy the per_ticker_date contract.

    capture_spot=False is REQUIRED: the live spot stamp is meaningless against a
    past bar, and writing it would be fabricated history, not a backfill.
    """
    from uw_scan.scanners import market_tide

    return market_tide.run(
        ctx.uw_client(), ctx.repo, trading_date=market_date, capture_spot=False
    )


def _run_top_net_impact(
    ctx: HealContext, ticker: str | None, market_date: date
) -> int:
    """Sessionwide — `ticker` is None in production. See _run_market_tide."""
    from uw_scan.scanners import top_net_impact

    return top_net_impact.run(ctx.uw_client(), ctx.repo, trading_date=market_date)


def _run_technical_daily(ctx: HealContext, lookback_days: int) -> int:
    """Recomputes the FULL series per ticker from apex bars, so one run heals
    every historical hole at once — no per-date plumbing needed or wanted."""
    from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

    out = technical_daily_refresh(repo=ctx.repo, settings=ctx.settings)
    return int(out.get("ok", 0))  # {"ok","skipped_thin","failed","tickers"}


def _run_corporate_actions(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once

    return corporate_actions_refresh_once(ctx.repo, ctx.massive_provider())


def _run_massive_fundamentals(ctx: HealContext, lookback_days: int) -> int:
    from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once

    return fundamentals_refresh_once(ctx.repo, ctx.massive_provider())
```

Add to `HEAL_SPECS`:

```python
    "cri_recover": HealSpec(
        "cri_recover", "db", "run_once_lookback", _run_cri_recover, est_per_item=0
    ),
    "vcg_recover": HealSpec(
        "vcg_recover", "db", "run_once_lookback", _run_vcg_recover, est_per_item=0
    ),
    "canary_recover": HealSpec(
        "canary_recover", "db", "run_once_lookback", _run_canary_recover, est_per_item=0
    ),
    "market_tide": HealSpec(
        "market_tide", "uw", "per_ticker_date", _run_market_tide, est_per_item=1
    ),
    "top_net_impact": HealSpec(
        "top_net_impact", "uw", "per_ticker_date", _run_top_net_impact, est_per_item=1
    ),
    "technical_daily": HealSpec(
        "technical_daily", "db", "run_once_lookback", _run_technical_daily,
        est_per_item=0,
    ),
    "corporate_actions": HealSpec(
        "corporate_actions", "massive", "run_once_lookback", _run_corporate_actions,
        est_per_item=0,
    ),
    "massive_fundamentals": HealSpec(
        "massive_fundamentals", "massive", "run_once_lookback",
        _run_massive_fundamentals, est_per_item=0,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_data_gap_adapters_existing.py -v`
Expected: PASS (6 params + 1)

- [ ] **Step 5: Add `reason_verified_on`, then point the registry at them**

This task is the first to write a *measured* reason, so it introduces the field that distinguishes a measurement from an assumption (Task 6 enforces it across the whole registry). In `DatasetRegistryEntry`, as the last field so every existing construction keeps working:

```python
    reason_verified_on: date | None = None  # when the refusal/claim was actually
    # probed; None = untested assumption, not a measurement
```

Add the column to `render_dataset_policy_markdown`'s header (`| … | reason | verified |`) and to each row (`{e.reason_verified_on or ''}`).

Then set `provider` / `granularity` / `healer_adapter` / `reason` / `reason_verified_on` on all nine entries. The two that were refused on a *measured-false* claim get the correction spelled out:

```python
        DatasetRegistryEntry(
            "market_tide_snapshots",
            "regime_marketwide",
            "strict_session",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="market_tide",
            reason="scanners.market_tide.run already takes trading_date (and "
            "capture_spot=False for backfill); UW served all 4 outage dates with "
            "full 81-82 bar sessions. The previous 'current-session only' claim "
            "was never probed. This is the audit's calendar reference — healing "
            "it is what stops the spine going blind.",
            reason_verified_on=date(2026, 8, 16),
        ),
```

```python
        DatasetRegistryEntry(
            "top_net_impact_snapshots",
            "regime_marketwide",
            "strict_session",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="top_net_impact",
            reason="scanners.top_net_impact.run already takes trading_date; UW "
            "served 40 rows/date back to 2026-01-02 (121 sessions backfilled "
            "2026-08-16). The 'may return only current session' claim was untested.",
            reason_verified_on=date(2026, 8, 16),
        ),
```

`iv_smile_snapshots` gets no new adapter — repoint it at the existing one:

```python
            provider="db",
            granularity="run_once",
            healer_adapter="vol_analytics_rollup",
            reason="DERIVED, not UW-retention: reports/volatility_series.py builds "
            "it from greeks_by_expiry_strike via build_iv_smile_snapshot_rows "
            "inside the nightly vol rollup. Heals automatically once greeks are "
            "restored. 700,540 rows, newest 2026-08-16 — live, not legacy.",
            reason_verified_on=date(2026, 8, 16),
```

`cri_snapshots` / `vcg_snapshots` / `canary_snapshots` / `technical_daily` / `corporate_actions` / `massive_fundamentals` take their adapter plus a dated reason naming the function that heals them. Leave every `audit_mode` as it is — promotions are Task 7's job, and mixing them here would make this task un-rejectable in isolation.

- [ ] **Step 6: Regenerate the policy doc and run its gate**

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
uv run pytest tests/unit/reports/test_data_gap_dataset_policy.py tests/unit/reports/test_data_gap_healer_specs.py -v
```
Expected: PASS

- [ ] **Step 7: Prove the spine now self-heals**


This is the point of the task; assert it rather than assuming it. Add to the test file:

```python
def test_the_calendar_reference_is_healable(seeded_db_empty_cards) -> None:
    """The audit's own spine reference must have a heal path, or an outage that
    truncates it can never be repaired unattended."""
    from uw_scan.reports.data_gap_healer import _REFERENCE_CALENDAR, REGISTRY

    ref = _REFERENCE_CALENDAR[0]  # market_tide_sentiment_daily
    by_name = {e.table_name: e for e in REGISTRY}
    assert by_name[ref].healer_adapter, f"{ref} (the spine) has no heal path"
    # ...and so must the dataset IT derives from.
    assert by_name["market_tide_snapshots"].healer_adapter
```

Run: `uv run pytest tests/integration/worker/test_data_gap_adapters_existing.py -v`
Expected: PASS

- [ ] **Step 8: Add the gate that makes dead adapters impossible**

This is the most valuable single test in the plan — it encodes the two-channel rule so no future wiring can silently no-op. Create `tests/unit/reports/test_no_dead_adapters.py`:

```python
"""A per_ticker_* adapter only ever fires on a strict_* dataset."""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import REGISTRY
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS


def test_every_registered_adapter_resolves() -> None:
    unknown = sorted(
        f"{e.table_name} -> {e.healer_adapter}"
        for e in REGISTRY
        if e.healer_adapter and e.healer_adapter not in HEAL_SPECS
    )
    assert not unknown, f"registry names adapters that do not exist: {unknown}"


def test_no_per_ticker_adapter_on_a_non_strict_dataset() -> None:
    """The healer has two channels and `granularity` picks one:

      run_once / run_once_lookback -> _refresh_targets -> run_refresh_adapters
        (fires regardless of audit_mode)
      per_ticker_date / per_ticker_range -> execute_run over GAP ITEMS
        (and only strict_* audit modes produce gap items)

    So a per_ticker_* adapter on a freshness_only dataset is never dispatched —
    silently, with no error, while the policy doc shows it as covered.
    """
    dead = []
    for e in REGISTRY:
        if not e.healer_adapter:
            continue
        spec = HEAL_SPECS.get(e.healer_adapter)
        if spec is None:
            continue  # covered by the test above
        if spec.granularity in ("per_ticker_date", "per_ticker_range"):
            if not e.audit_mode.startswith("strict"):
                dead.append(f"{e.table_name} ({e.audit_mode} + {spec.granularity})")
    assert not dead, (
        "these adapters can never run — promote the dataset to a strict audit "
        f"mode or give it a run_once* adapter: {dead}"
    )


def test_registry_granularity_matches_its_adapter() -> None:
    """The registry's own granularity must agree with the spec's, or
    _refresh_targets enrols (or skips) the wrong datasets."""
    mismatched = sorted(
        f"{e.table_name}: registry={e.granularity} spec={HEAL_SPECS[e.healer_adapter].granularity}"
        for e in REGISTRY
        if e.healer_adapter
        and e.healer_adapter in HEAL_SPECS
        and e.granularity != HEAL_SPECS[e.healer_adapter].granularity
    )
    assert not mismatched, mismatched
```

Run: `uv run pytest tests/unit/reports/test_no_dead_adapters.py -v`
Expected: PASS. **If it fails, the failure is real** — fix the registry entry, do not weaken the test.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py src/uw_scan/reports/data_gap_healer.py \
        docs/runbooks/data-gap-dataset-policy.md \
        tests/integration/worker/test_data_gap_adapters_existing.py \
        tests/unit/reports/test_no_dead_adapters.py
git commit -m "feat(healer): wire the 9 adapters whose entrypoints were already date-aware"
```


---

### Task 5: GRG gets an `as_of`, and the healer proves a date-looped heal actually varies

**Files:**
- Modify: `src/uw_scan/scanners/grg.py:38-70` (`_spot_flip_from_gex`), `:72-90` (`_spy_close_by_date`), `:97-160` (`run`)
- Modify: `src/uw_scan/storage/gex.py:15-40` (`fetch_latest_gex` gains `as_of`)
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (adapter + spec)
- Modify: `src/uw_scan/reports/data_gap_healer.py` (`grg_snapshots` entry)
- Test: `tests/integration/regime/test_grg_as_of.py` (create)

**Interfaces:**
- Produces: `uw_scan.scanners.grg.run(client, repo, schema="uw_scan", *, scan_time=None, as_of=None) -> int | None`. `as_of=None` keeps today's behaviour exactly.
- Produces: `Repository.fetch_latest_gex(*, ticker="SPX", as_of: date | None = None) -> dict | None` — newest snapshot **at or before** `as_of`.
- Produces: `HEAL_SPECS["grg_as_of"]`, `granularity="per_ticker_date"`, `provider="uw"`, `est_per_item=2` (SPY + TLT history calls).

**Why this is the anti-lookahead task.** `grg.run` fetches SPY/TLT `greek_exposure_history` with `timeframe="1Y"` — the *whole* series — then computes one snapshot from its tail. That makes a past date genuinely reconstructible: truncate the series at `as_of` and compute.

**`run` has FOUR inputs, and truncating only the obvious one ships the bug this task exists to prevent.** Verified by reading `scanners/grg.py` on 2026-08-16:

| input | source | date-aware today? | what `as_of` must do |
|---|---|---|---|
| `spy_rows` / `tlt_rows` | `parse_greek_exposure_history(...timeframe="1Y")` | no — always through today | filter `trade_date <= as_of` |
| `spy_spot` / `spy_flip`, `tlt_spot` / `tlt_flip` | `_spot_flip_from_gex` → `repo.fetch_latest_gex(ticker)` | **no — always the newest row** | read the newest snapshot at/before `as_of` |
| `spy_prices` | `_spy_close_by_date` → `repo.list_daily_ohlc("SPY", limit=400)` | no — 400 most recent bars | drop keys after `as_of` |
| `scan_time` | `datetime.now(...)` | n/a — display only | leave alone |

Truncating the gamma series while spot and flip come from today is *precisely* the E6 failure: a row stamped with a past date, computed from future data, that looks like a successful backfill. Step 5's test is the guard — two different `as_of` values must produce two different `grg_z`.

One thing that works in our favour: `data_date` is derived inside `grg_scoring.run_analysis` from the series' own last date and read back as `_date.fromisoformat(payload["data_date"])`. So truncating the series **automatically** stamps the row correctly — no manual date stamping, and a forgotten truncation shows up immediately as the wrong `data_date`. Assert that in the test.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/regime/test_grg_as_of.py`:

```python
"""grg.run(as_of=...) must truncate its inputs, not restamp today's answer (E6)."""

from __future__ import annotations

from datetime import date

from uw_scan.scanners import grg

# Frozen real-shaped series: a monotone ramp so truncation is observable.
# Key is `date` — parse_greek_exposure_history emits `date`, and grg_scoring
# reads r["date"] (cards/grg_scoring.py:332,395). Using `trade_date` here would
# make the test pass while production raises KeyError.
_SERIES = [
    {"date": date(2026, 8, 10), "call_gex": 100.0, "put_gex": -60.0},
    {"date": date(2026, 8, 11), "call_gex": 200.0, "put_gex": -60.0},
    {"date": date(2026, 8, 12), "call_gex": 900.0, "put_gex": -60.0},
]


def test_two_as_of_dates_produce_different_snapshots(
    seeded_db_empty_cards, monkeypatch
) -> None:
    repo = seeded_db_empty_cards
    monkeypatch.setattr(
        "uw_scan.scanners.grg.parse_greek_exposure_history", lambda body: _SERIES
    )
    monkeypatch.setattr(
        "uw_scan.sources.uw.fetch_greek_exposure_history",
        lambda client, r, run_id, t, timeframe="1Y": {},
    )

    grg.run(client=object(), repo=repo, as_of=date(2026, 8, 11))
    grg.run(client=object(), repo=repo, as_of=date(2026, 8, 12))

    with repo.conn.cursor() as cur:
        # grg_z is a STORED generated column off payload->'signal'->>'grg_z';
        # data_date (not snapshot_date) is the date key on this table.
        cur.execute(
            "SELECT data_date, grg_z FROM uw_scan.grg_snapshots ORDER BY data_date"
        )
        rows = cur.fetchall()

    # data_date is derived from the truncated series' tail, so this alone
    # catches a forgotten filter on spy_rows/tlt_rows.
    assert [r[0] for r in rows] == [date(2026, 8, 11), date(2026, 8, 12)]
    assert rows[0][1] != rows[1][1], (
        "identical values across as_of dates means the inputs were NOT truncated — "
        "this is the lookahead contamination that hit vrp_macro_signal_daily"
    )


def test_spot_and_flip_are_read_as_of(seeded_db_empty_cards) -> None:
    """The gamma series is not the only input — spot/flip must be dated too."""
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for d, spot in ((date(2026, 8, 11), 600.0), (date(2026, 8, 12), 700.0)):
            cur.execute(
                "INSERT INTO uw_scan.gex_snapshots (ticker, scanned_at, payload) "
                "VALUES ('SPY', %s, %s::jsonb)",
                (d, '{"spot": %s, "levels": {"gex_flip": {"strike": %s}}}'
                 % (spot, spot)),
            )
        repo.conn.commit()

    early = repo.fetch_latest_gex(ticker="SPY", as_of=date(2026, 8, 11))
    late = repo.fetch_latest_gex(ticker="SPY", as_of=date(2026, 8, 12))
    assert early["spot"] == 600.0, "as_of must not see the next day's snapshot"
    assert late["spot"] == 700.0
```

`grg_snapshots` columns verified 2026-08-16 (migration `071`): `data_date DATE`, `payload JSONB NOT NULL`, `basis TEXT DEFAULT 'eod'`, and generated columns `grg_z`, `interpretation`, `pair_state`, `tier`, `spy_net_gamma`, `tlt_net_gamma`. Assert on `grg_z` — a computed value — never on `scanned_at`, which differs between two runs even when the payload is identical and would make the test pass while the bug survives.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/regime/test_grg_as_of.py -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'as_of'`

- [ ] **Step 3: Add `as_of` to `grg.run`**

In `src/uw_scan/scanners/grg.py`, change the signature to:

```python
def run(
    client: UwClient,
    repo: Repository,
    schema: str = "uw_scan",
    *,
    scan_time: str | None = None,
    as_of: date | None = None,
) -> int | None:
```

First give the two helpers an `as_of`. In `src/uw_scan/storage/gex.py`:

```python
    def fetch_latest_gex(
        self, *, ticker: str = "SPX", as_of: date | None = None
    ) -> dict | None:
        """Most recent GEX snapshot for ``ticker``, or the newest at/before
        ``as_of`` when replaying a historical date.

        ``scan_time`` and ``ticker`` are populated from the row when absent
        from the payload so the API response always carries them.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, scanned_at, ticker "
                f"FROM {self._schema}.gex_snapshots "
                f"WHERE ticker = %s "
                f"  AND (%s::date IS NULL OR scanned_at < %s::date + 1) "
                f"ORDER BY scanned_at DESC LIMIT 1",
                (ticker.upper(), as_of, as_of),
            )
            row = cur.fetchone()
```

(rest of the method unchanged; add `from datetime import date` to the module imports).

In `src/uw_scan/scanners/grg.py`, thread `as_of` through both helpers:

```python
def _spot_flip_from_gex(
    repo: Repository, ticker: str, as_of: _date | None = None
) -> tuple[float | None, float | None]:
    ...
    raw = repo.fetch_latest_gex(ticker=ticker, as_of=as_of)
```

```python
def _spy_close_by_date(
    repo: Repository, as_of: _date | None = None
) -> dict[str, float]:
    ...
    # (at the end, before returning the map)
    if as_of is not None:
        cutoff = as_of.isoformat()
        out = {d: c for d, c in out.items() if d <= cutoff}
    return out
```

Then in `run`, immediately after both series are parsed:

```python
    if as_of is not None:
        # Historical replay: the 1Y fetch always returns the series through
        # today, so a past snapshot MUST drop everything after as_of or the
        # row is stamped with a past date and computed from future data.
        # data_date is derived from the series tail inside run_analysis, so a
        # forgotten filter here shows up as the WRONG data_date, not silently.
        # The row key is `date` (NOT `trade_date`) — parse_greek_exposure_history
        # emits `date` and grg_scoring reads r["date"]. Same key mismatch that
        # bites the greek_exposure_daily heal in Task 1, opposite direction.
        spy_rows = [r for r in spy_rows if r["date"] <= as_of]
        tlt_rows = [r for r in tlt_rows if r["date"] <= as_of]
        if not spy_rows or not tlt_rows:
            repo.finish_scan_run(run_id, status="ok")
            return None
```

**Expect `no_data` for early dates, and do not "fix" it.** `run` already wraps the compute in `except ValueError` → `log.warning("grg_scan_skipped_thin_data")` → `return None`, and the z-window needs 63 warmed sessions. Truncating to an `as_of` near the start of the fetched year legitimately leaves too little history, so the adapter returns 0, `_verify_covered` fails, and the item is recorded `no_data`. That is the honest answer — the series genuinely cannot support a snapshot there — not a bug to work around by widening the window.

and pass `as_of` to the three reads below it:

```python
        spy_spot, spy_flip = _spot_flip_from_gex(repo, "SPY", as_of)
        tlt_spot, tlt_flip = _spot_flip_from_gex(repo, "TLT", as_of)
        spy_prices = _spy_close_by_date(repo, as_of)
```

`grg.py` already imports `date as _date`; add it to `storage/gex.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/regime/test_grg_as_of.py -v`
Expected: PASS

- [ ] **Step 5: Add the adapter and registry entry**

In `data_gap_adapters.py`:

```python
def _run_grg(ctx: HealContext, ticker: str | None, market_date: date) -> int:
    """Marketwide — `ticker` is None (strict_session items carry no ticker)."""
    from uw_scan.scanners import grg

    row_id = grg.run(ctx.uw_client(), ctx.repo, ctx.schema, as_of=market_date)
    return 1 if row_id is not None else 0
```

```python
    "grg_as_of": HealSpec(
        "grg_as_of", "uw", "per_ticker_date", _run_grg, est_per_item=2
    ),
```

In the registry, set `grg_snapshots` to `provider="uw"`, `granularity="per_ticker_date"`, `healer_adapter="grg_as_of"`, **`audit_mode="strict_session"`**, and:

> **The audit-mode change is not cosmetic — without it this adapter is dead code.** `grg_snapshots` is registered `freshness_only`, and `scan_dataset` produces gap items only for `strict_*` modes. A `per_ticker_date` adapter is dispatched exclusively from `execute_run` over those items, so on a `freshness_only` dataset it is never called, no error is raised, and the policy doc still shows the table as covered. `grg_snapshots` is one marketwide row per session (`data_date`, no ticker column) — exactly what `strict_session` measures, the same shape as `market_tide_snapshots` and `top_net_impact_snapshots`. Task 4 Step 8's `test_no_per_ticker_adapter_on_a_non_strict_dataset` fails loudly if this is forgotten.
>
> Per the memory note on strict tables, a new `strict_*` entry also needs its regenerated policy doc in the same commit (Step 6 does that).

And:

```python
            reason="grg.run(as_of=) truncates the 1Y SPY/TLT greek-exposure series; "
            "past dates reconstructible, verified 2026-08-16",
```

- [ ] **Step 6: Regenerate the policy doc and run the gates**

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
uv run pytest tests/unit/reports/ tests/integration/regime/ -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/scanners/grg.py src/uw_scan/storage/gex.py \
        src/uw_scan/worker/jobs/data_gap_adapters.py \
        src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md \
        tests/integration/regime/test_grg_as_of.py
git commit -m "feat(grg): as_of truncates the fetched series so historical snapshots are real"
```

---

### Task 6: Lake + event-log adapters, and the assumption purge

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (3 adapters + specs)
- Modify: `src/uw_scan/worker/volatility_jobs.py` (`daily_spy_ohlc_refresh` gains `lookback_days`)
- Modify: `src/uw_scan/reports/data_gap_healer.py` (every remaining `provider="none"` reason; the field itself lands in Task 4)
- **Not** modified: `scripts/backfill/uw_alpha_catchup.py` — the adapters reuse its capture functions directly, so the CLI needs no extraction
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerate)
- Test: `tests/unit/reports/test_data_gap_reasons.py` (create), `tests/integration/worker/test_data_gap_adapters_lake.py` (create)

**Interfaces:**
- Produces: `daily_spy_ohlc_refresh(..., lookback_days: int = 2)` — the current hardcoded `start = today - timedelta(days=2)` cannot reach an older hole.
- Consumes (all signatures verified 2026-08-16):
  - `vol_index_lake_sync.run_vol_index_lake_sync(conn, *, root: Path | LakeRoot) -> dict` — returns `{"symbols", "rows", "gaps_filled"}`
  - `credit_etf_lake_sync.run_credit_etf_lake_sync(conn, *, root, symbols: Sequence[str]) -> dict` — same keys. **Both write `vol_index_daily`**, and a registry entry names exactly one adapter, so one adapter runs both.
  - `sources.lake_resolver.resolve_lake_root(settings, *, asset_class: str) -> LakeRoot` — `"volatility"` and `"equity"`; this, not `market_warehouse_lake_root`, is what the scheduler passes (`scheduler.py:1068`, `:1077`)
  - `uw_alpha_capture.capture_intraday_flow_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int`
  - `uw_alpha_capture.capture_dark_lit_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int`
  - `worker.volatility_jobs.daily_spy_ohlc_refresh(repo, api_key, tz="America/New_York", telemetry_recorder=None)` — writes `index_ohlc_daily`
  - The lake root setting is `settings.market_warehouse_lake_root` (a `Path`), **not** `lake_root`; symbols are `settings.credit_etf_symbols` (default `["HYG", "JNK", "LQD"]`).

**`index_ohlc_daily` is NOT healed by the lake syncs.** They write `vol_index_daily`. `index_ohlc_daily` is written by `daily_spy_ohlc_refresh`, whose window is hardcoded to `today - 2 days` — so it heals a same-day miss and nothing older. Give it a `lookback_days` parameter (default 2, preserving today's behaviour exactly) and an adapter.
- Consumes: `DatasetRegistryEntry.reason_verified_on` (introduced in Task 4)
- Produces: `HEAL_SPECS` keys `"vol_index_lake"` (runs BOTH lake syncs — see below), `"index_ohlc"`, `"uw_alpha_intraday_flow"`, `"uw_alpha_dark_lit"`.

**The rule this task encodes.** A `provider="none"` entry is a *refusal to try*. Right now 45 daily tables refuse on one copy-pasted sentence that was never measured, and round 1 proved it false for 13 of them. Adding `reason_verified_on` makes the distinction structural: a refusal either carries the date somebody actually probed the provider, or it is an untested assumption and says so.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/reports/test_data_gap_reasons.py`:

```python
"""Refusals must be measured, not assumed (E5)."""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import REGISTRY

# Every table round 1 healed by hand, plus every one whose entrypoint was
# already date-aware. None may still claim "no auto-backfill".
PROVEN_HEALABLE = {
    "index_ohlc_daily",              # -> index_ohlc (Task 6)
    "vol_index_daily",               # -> vol_index_lake
    "uw_dark_lit_flow_prints",       # -> uw_alpha_dark_lit
    "uw_intraday_option_flow_bars",  # -> uw_alpha_intraday_flow
    "cri_snapshots",                 # -> cri_recover      (Task 4)
    "vcg_snapshots",                 # -> vcg_recover      (Task 4)
    "canary_snapshots",              # -> canary_recover   (Task 4)
    "market_tide_snapshots",         # -> market_tide      (Task 4)
    "top_net_impact_snapshots",      # -> top_net_impact   (Task 4)
    "technical_daily",               # -> technical_daily  (Task 4)
    "corporate_actions",             # -> corporate_actions(Task 4)
    "massive_fundamentals",          # -> massive_fundamentals (Task 4)
    "grg_snapshots",                 # -> grg_as_of        (Task 5)
}

STALE_ASSUMPTION = "UW-retention/event-log shaped"


def test_proven_healable_tables_have_an_adapter() -> None:
    by_name = {e.table_name: e for e in REGISTRY}
    missing = sorted(
        t for t in PROVEN_HEALABLE if by_name[t].healer_adapter is None
    )
    assert not missing, f"healed by hand in round 1 but still refused: {missing}"


def test_no_proven_table_still_carries_the_stale_assumption() -> None:
    offenders = sorted(
        e.table_name
        for e in REGISTRY
        if e.table_name in PROVEN_HEALABLE and STALE_ASSUMPTION in (e.reason or "")
    )
    assert not offenders


def test_every_refusal_is_dated() -> None:
    """A provider='none' daily dataset must say WHEN the refusal was measured."""
    undated = sorted(
        e.table_name
        for e in REGISTRY
        if e.provider == "none"
        and e.audit_mode not in ("excluded", "provenance", "operational_state")
        and e.expected_frequency in ("equity_session", "daily")
        and e.reason_verified_on is None
    )
    assert not undated, (
        "undated refusals are assumptions; probe the provider and stamp the "
        f"date, or wire an adapter: {undated}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_data_gap_reasons.py -v`
Expected: FAIL — `AttributeError: 'DatasetRegistryEntry' object has no attribute 'reason_verified_on'`, plus the adapter/offender assertions.

- [ ] **Step 3: (nothing to add — `reason_verified_on` landed in Task 4)**

Task 4 introduced the field because it was the first task to write a measured reason. This task's job is to enforce it across the *whole* registry, not to define it. Confirm it exists before continuing:

```bash
grep -n "reason_verified_on" src/uw_scan/reports/data_gap_healer.py
```
Expected: the field on `DatasetRegistryEntry`, the policy-doc column, and Task 4's nine dated entries. If it is missing, Task 4 has not merged — stop and do it first.

- [ ] **Step 3b: Give `daily_spy_ohlc_refresh` the `lookback_days` it is about to be called with**

Without this the adapter in Step 4 raises `TypeError` on its first invocation. In `src/uw_scan/worker/volatility_jobs.py`, the window is hardcoded:

```python
    today = datetime.now(ZoneInfo(tz)).date()
    start = today - timedelta(days=2)
```

Add the parameter with the current value as its default, so today's callers are unaffected:

```python
def daily_spy_ohlc_refresh(
    repo: Repository,
    api_key: str,
    tz: str = "America/New_York",
    telemetry_recorder: ExternalApiRequestRecorder | None = None,
    lookback_days: int = 2,
) -> None:
    """ET-anchored — host may live in any timezone (e.g. HKT), so date.today()
    would compute the wrong market date around the rollover (review I8).

    `lookback_days` defaults to the original hardcoded 2-day window; the gap
    healer passes a wider one to reach an older hole.
    """
    today = datetime.now(ZoneInfo(tz)).date()
    start = today - timedelta(days=max(2, lookback_days))
```

Confirm the existing call site in `worker/scheduler.py` still type-checks (it passes no `lookback_days`, so it keeps the 2-day behaviour byte-for-byte).

- [ ] **Step 4: Add the four adapters**

In `data_gap_adapters.py`:

```python
def _run_vol_index_lake(ctx: HealContext, lookback_days: int) -> int:
    """BOTH lake syncs write vol_index_daily — a registry entry names exactly one
    adapter, so one adapter must run both. Idempotent and full-range;
    lookback_days is unused.

    Roots come from resolve_lake_root(asset_class=...), NOT
    settings.market_warehouse_lake_root — config.py:364 documents that field as
    the root of the WHOLE lake, "distinct from the two asset-class roots", which
    point at specific bronze partitions. Mirrors scheduler.py:1068 / :1077.
    """
    from uw_scan.sources.lake_resolver import resolve_lake_root
    from uw_scan.worker.jobs.credit_etf_lake_sync import run_credit_etf_lake_sync
    from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

    vol = run_vol_index_lake_sync(
        ctx.repo.conn,
        root=resolve_lake_root(ctx.settings, asset_class="volatility"),
    )
    credit = run_credit_etf_lake_sync(
        ctx.repo.conn,
        root=resolve_lake_root(ctx.settings, asset_class="equity"),
        symbols=ctx.settings.credit_etf_symbols,
    )
    return int(vol.get("rows", 0)) + int(credit.get("rows", 0))


def _run_index_ohlc(ctx: HealContext, lookback_days: int) -> int:
    """index_ohlc_daily comes from daily_spy_ohlc_refresh, NOT the lake syncs."""
    from uw_scan.worker.volatility_jobs import daily_spy_ohlc_refresh

    if ctx.settings.massive_api_key is None:
        raise RuntimeError("MASSIVE_API_KEY not set; index_ohlc heal unavailable")
    daily_spy_ohlc_refresh(
        ctx.repo,
        ctx.settings.massive_api_key.get_secret_value(),
        lookback_days=max(2, lookback_days),
    )
    return 0


def _eventlog_heal(capture_fn):
    """Both UW event logs share one shape: (ticker, date) -> one capture call.

    `scripts/backfill/uw_alpha_catchup.py` already maps dataset -> capture fn in
    `_EVENTLOG`; these adapters call the SAME production functions, so there is
    still exactly one writer and the CLI needs no change.
    """

    def _run(ctx: HealContext, ticker: str, market_date: date) -> int:
        run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer_eventlog")
        try:
            written = capture_fn(
                ctx.uw_client(),
                ctx.repo,
                _uw_alpha_repo(ctx),
                run_id,
                ticker,
                market_date,
            )
            ctx.repo.finish_scan_run(run_id, status="ok")
            return int(written)
        except Exception as exc:  # noqa: BLE001
            ctx.repo.finish_scan_run(run_id, status="error")
            logger.warning(
                "eventlog heal failed %s %s: %s", ticker, market_date, repr(exc)
            )
            raise

    return _run
```

`_uw_alpha_repo(ctx)` already exists in this module (line 165) and returns a `UwHistoricalAlphaRepository`. Import the two capture functions at the top of the adapter block:

```python
from uw_scan.worker.jobs.uw_alpha_capture import (
    capture_dark_lit_for,
    capture_intraday_flow_for,
)
```

Register:

```python
    "vol_index_lake": HealSpec(
        "vol_index_lake", "db", "run_once_lookback", _run_vol_index_lake, est_per_item=0
    ),
    "index_ohlc": HealSpec(
        "index_ohlc", "massive", "run_once_lookback", _run_index_ohlc, est_per_item=1
    ),
    "uw_alpha_intraday_flow": HealSpec(
        "uw_alpha_intraday_flow", "uw", "per_ticker_date",
        _eventlog_heal(capture_intraday_flow_for), est_per_item=2,
    ),
    "uw_alpha_dark_lit": HealSpec(
        "uw_alpha_dark_lit", "uw", "per_ticker_date",
        _eventlog_heal(capture_dark_lit_for), est_per_item=2,
    ),
```

**Both event-log entries must move from `freshness_only` to `audit_mode="strict_ticker_date"` in the same commit.** A `per_ticker_date` adapter is dispatched only from `execute_run` over gap items, and only `strict_*` modes produce them — leave these `freshness_only` and the adapters are dead code that still reads as coverage. Both tables are keyed `(ticker, market_date)`, so the strict denominator is well-defined. Task 4 Step 8's gate test catches this if it is missed.

- [ ] **Step 5: Write the lake adapter test**

Create `tests/integration/worker/test_data_gap_adapters_lake.py`:

```python
"""Lake syncs are heal adapters, not manual scripts (E5)."""

from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget


def test_vol_index_adapter_calls_the_production_sync(
    seeded_db_empty_cards, monkeypatch
) -> None:
    called: dict = {}

    def _fake_vol(conn, *, root):
        called["vol_root"] = str(root)
        return {"symbols": 3, "rows": 7, "gaps_filled": 7}

    def _fake_credit(conn, *, root, symbols):
        called["credit_root"] = str(root)
        called["symbols"] = list(symbols)
        return {"symbols": 3, "rows": 0, "gaps_filled": 0}

    monkeypatch.setattr(
        "uw_scan.worker.jobs.vol_index_lake_sync.run_vol_index_lake_sync", _fake_vol
    )
    monkeypatch.setattr(
        "uw_scan.worker.jobs.credit_etf_lake_sync.run_credit_etf_lake_sync",
        _fake_credit,
    )
    settings = Settings.from_env()
    ctx = HealContext(
        repo=seeded_db_empty_cards,
        gap=None,
        schema=settings.db_schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )
    assert HEAL_SPECS["vol_index_lake"].run(ctx, 7) == 7
    # The two asset-class roots differ; the whole-lake root would be a bug.
    assert called["vol_root"] != called["credit_root"]
    assert called["symbols"] == list(settings.credit_etf_symbols)
```

- [ ] **Step 6: Purge the assumptions**

For every entry in `PROVEN_HEALABLE`, set the adapter/provider/granularity and a dated reason. For every *remaining* `provider="none"` daily entry, either:
- wire an adapter, or
- rewrite the reason to name what was probed and stamp `reason_verified_on=date(2026, 8, 16)`, or
- if it was never probed, say so honestly: `reason="UNVERIFIED: never probed for historical availability"` and leave `reason_verified_on=None` — the test in Step 1 will then fail and force the probe.

Start with the three refusals round 1 *did* measure, which stay refusals:

```python
            reason="UW returns byte-identical bodies for different `date` values "
            "(response-hash differential, 2026-08-16) — historical replay would "
            "be fabrication, not backfill",
            reason_verified_on=date(2026, 8, 16),
```

on `flow_events` / `flow_alerts_daily_rollup`, `short_interest_snapshots` / `uw_positioning`, and `options_volume_daily`.

- [ ] **Step 6b: Exclude the one genuinely dead table**

`oi_by_expiry` is registered `freshness_only`, which implies something monitors it. Measured 2026-08-16: **0 rows**, and the table name appears nowhere in the codebase except `storage/health.py`'s name list — there is no INSERT for it anywhere. A dataset with no writer cannot be stale, so monitoring it is noise. Change it to:

```python
            "excluded",
            reason="no writer anywhere in the codebase and 0 rows as of 2026-08-16; "
            "the table exists but nothing populates it",
            reason_verified_on=date(2026, 8, 16),
```

Do **not** do the same to `iv_smile_snapshots` — a grep for its table name in `worker/` also finds nothing, yet it holds 700,540 rows with `market_date` = 2026-08-16, because it is written indirectly from `greeks_by_expiry_strike` via `build_iv_smile_snapshot_rows`. Task 7 gives it an adapter. This pair is exactly why the rule is "check the row count before calling a table dead", never "grep for a writer".

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reports/test_data_gap_reasons.py tests/integration/worker/test_data_gap_adapters_lake.py -v`
Expected: PASS

- [ ] **Step 8: Regenerate the policy doc and run all healer gates**

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
uv run pytest tests/unit/reports/ tests/integration/scripts/ tests/integration/worker/ -v
```
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/reports/data_gap_healer.py src/uw_scan/worker/jobs/data_gap_adapters.py \
        docs/runbooks/data-gap-dataset-policy.md tests/unit/reports/test_data_gap_reasons.py \
        tests/integration/worker/test_data_gap_adapters_lake.py
git commit -m "feat(healer): lake/event-log adapters; every refusal now carries the date it was measured"
```

---

### Task 7: Strict audit for the replay-backfilled options-chain set — **GATED ON ROUND 1**

**Do not start this task until `docs/superpowers/plans/2026-08-16-historical-replay-backfill.md` Tasks 3–6 have merged** (Task 6 is the cockpit date-parameterization this task's `cockpit_replay` adapter depends on).

**Preflight — verify round 1 actually delivered all four of these before writing a line.** This task consumes a contract owned by a different plan; if any item is missing, add it *there* (or on this branch with a note), do not work around it here.

```bash
# 1. run_single_stock takes a historical market_date
grep -n "def run_single_stock" -A 8 src/uw_scan/pipeline.py
# 2-4. cockpit_daily_snapshot: market_date, ticker_filter, int return
grep -n "def cockpit_daily_snapshot" -A 10 src/uw_scan/worker/jobs/cockpit_daily_snapshot.py
```

| # | requirement | today (2026-08-16) | why this task needs it |
|---|---|---|---|
| 1 | `run_single_stock(..., *, market_date=None)` | absent | the `replay` adapter's whole premise |
| 2 | `cockpit_daily_snapshot(..., market_date=…)` | absent | round 1 Task 6 owns this |
| 3 | `cockpit_daily_snapshot(..., ticker_filter=…)` | absent | without it, healing one ticker-date re-snapshots all 4 cockpit tickers |
| 4 | returns `int`, and **raises** when `COCKPIT_SNAPSHOT_LOCK` (92201) is held | returns `None`, returns silently | a silent lock-skip verifies false and records `no_data` — a false claim that UW has no data |

Items 3 and 4 are this plan's requirements on round 1, not round 1's own. Raise them there before it merges. It consumes the `market_date` plumbing they add. If round 1 has not shipped, stop here and report Tasks 1–6 as the deliverable.

**Files:**
- Modify: `src/uw_scan/reports/data_gap_healer.py` (16 registry entries)
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (`replay` + `cockpit_replay` + `intraday_buckets` adapters + specs)
- **Not** modified: `scripts/backfill/intraday_buckets_backfill.py` — its core is already the reusable `backfill_intraday_history`
- Modify: `src/uw_scan/config.py` (two settings)
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerate)
- Test: `tests/integration/worker/test_data_gap_replay_adapter.py` (create)

**Interfaces:**
- Consumes: round 1 Task 4's `run_single_stock(ticker, client, repo, *, market_date=None)`, and round 1 Task 6's date-parameterized `cockpit_daily_snapshot`.
- Produces: `HEAL_SPECS["replay"]` and `HEAL_SPECS["cockpit_replay"]`, both `per_ticker_date` / `provider="uw"`.

**Two writers, not one — assigning all of these to `replay` would silently heal nothing.** Verified on 2026-08-16 by listing the persister calls in each job:

`run_single_stock` writes: `oi_by_strike`, `oi_change_events`, `greeks_by_expiry_strike`, `exposures_by_expiry_strike`, `exposures_summary`, `iv_term_snapshots`, `interpolated_iv_snapshots`, `risk_reversal_skew_history`, `max_pain_by_expiry`, `pcr_history`, `dark_pool_events`, `option_contract_snapshots`.

`cockpit_daily_snapshot` — and **only** it — writes: `iv_rank_history` (`upsert_iv_rank_rows`), `option_chain_per_strike` (`upsert_option_chain_per_strike`), `matrix_state_snapshots` (`upsert_matrix_state_snapshot`).

Point those three at `replay` and the heal runs a full 17-call deep scan per ticker-date, writes none of the three, verifies false, and records `no_data` — burning ~29k UW calls to conclude the data is unavailable. That is the same class of silent no-op as the `gex_scan_tickers` fall-through in Task 1.

**Budget posture — audit strict, heal off by default.** Promoting 13 tables to `strict_ticker_date` is free: the audit is pure set-difference SQL with zero provider calls, and it is the only way the outage becomes *visible*. Healing them is not free: at ~17 UW calls per ticker-date and 170 tickers, one missing session costs ~29k calls against a 120k/day ceiling. So the promotion ships with healing behind a flag and its own sub-ceiling, defaulted off. The operator turns it on for a known outage window; the nightly job never spends the desk's budget on it by surprise.

- [ ] **Step 1: Add the settings, and gate at ENROLMENT not at dispatch**

In `src/uw_scan/config.py`, alongside the other healer settings:

```python
    data_gap_replay_heal_enabled: bool = False
    data_gap_replay_uw_ceiling: int = 30000
```

**Where the gate lives matters more than the gate.** If the only check is the `RuntimeError` inside the adapter, `_dispatch_per_ticker_date` catches it, calls `mark_item_failed`, increments `outcome["failed"]`, and `logger.exception`s — **per item, every night**. With 16 newly-strict datasets × 170 tickers × N sessions that is thousands of bogus `failed` rows and a log full of stack traces for a feature that is simply switched off. `failed` also means something different from "not attempted", and the health endpoint reads it.

So filter these datasets out of the *heal* list while leaving them in the *audit*:

```python
# worker/jobs/data_gap_healer.py, immediately before execute_run(...)
def _heal_datasets(settings, datasets: list[str] | None) -> list[str] | None:
    """Audit every dataset; heal only what is switched on.

    Replay heals cost ~17 UW calls per ticker-date. Excluding them here (rather
    than letting the adapter raise) keeps the audit's visibility while leaving
    no `failed` items and no stack traces behind for a disabled feature.
    """
    if settings.data_gap_replay_heal_enabled:
        return datasets
    replay = {
        e.table_name
        for e in REGISTRY
        if e.healer_adapter in ("replay", "cockpit_replay")
    }
    pool = [e.table_name for e in REGISTRY] if datasets is None else datasets
    return [d for d in pool if d not in replay]
```

and call `execute_run(ctx, run_id, datasets=_heal_datasets(settings, datasets))`. Keep the `RuntimeError` inside the adapters too — it is the defense-in-depth for a manual `scripts/backfill/data_gap_healer.py execute --datasets …` invocation that bypasses this filter.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/worker/test_data_gap_replay_adapter.py`:

```python
"""The replay adapter is budget-gated and off by default (Task 7)."""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget


def _ctx(repo, settings) -> HealContext:
    return HealContext(
        repo=repo,
        gap=None,
        schema=settings.db_schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )


def test_replay_refuses_when_the_flag_is_off(seeded_db_empty_cards) -> None:
    settings = Settings.from_env().model_copy(
        update={"data_gap_replay_heal_enabled": False}
    )
    with pytest.raises(RuntimeError, match="data_gap_replay_heal_enabled"):
        HEAL_SPECS["replay"].run(
            _ctx(seeded_db_empty_cards, settings), "AAPL", date(2026, 8, 12)
        )


def test_replay_forwards_the_market_date(seeded_db_empty_cards, monkeypatch) -> None:
    seen: dict = {}

    def _fake(ticker, client, repo, *, market_date=None, **kw):
        seen["ticker"] = ticker
        seen["market_date"] = market_date
        return 1

    monkeypatch.setattr("uw_scan.pipeline.run_single_stock", _fake)
    settings = Settings.from_env().model_copy(
        update={"data_gap_replay_heal_enabled": True}
    )
    HEAL_SPECS["replay"].run(
        _ctx(seeded_db_empty_cards, settings), "AAPL", date(2026, 8, 12)
    )
    assert seen == {"ticker": "AAPL", "market_date": date(2026, 8, 12)}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_data_gap_replay_adapter.py -v`
Expected: FAIL — `KeyError: 'replay'`

- [ ] **Step 4: Add the adapter**

```python
def _run_replay(ctx: HealContext, ticker: str, market_date: date) -> int:
    """Replay one deep scan at a historical market_date (round 1 plumbing).

    Off by default: at ~17 UW calls per ticker-date, one missing session across
    the watchlist is ~29k calls against a 120k/day ceiling. The audit side of
    these datasets is free and always on; only the SPEND is gated.
    """
    from uw_scan import pipeline

    if not getattr(ctx.settings, "data_gap_replay_heal_enabled", False):
        raise RuntimeError(
            "replay heal is disabled; set data_gap_replay_heal_enabled=true to "
            "spend UW budget on historical deep scans"
        )
    return pipeline.run_single_stock(
        ticker, ctx.uw_client(), ctx.repo, market_date=market_date
    ) or 0
```

```python
def _run_cockpit_replay(ctx: HealContext, ticker: str, market_date: date) -> int:
    """iv_rank_history / option_chain_per_strike / matrix_state_snapshots come
    from the cockpit job, NOT run_single_stock. Pointing them at `replay` would
    run a 17-call deep scan that writes none of them."""
    from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot

    if not getattr(ctx.settings, "data_gap_replay_heal_enabled", False):
        raise RuntimeError(
            "replay heal is disabled; set data_gap_replay_heal_enabled=true to "
            "spend UW budget on historical deep scans"
        )
    return cockpit_daily_snapshot(
        repo=ctx.repo,
        client=ctx.uw_client(),
        settings=ctx.settings,
        market_date=market_date,
        ticker_filter=[ticker],
    )
```

**Two things round 1 Task 6 must deliver for this adapter to work — check them before writing it.** Today's signature is `cockpit_daily_snapshot(*, repo: Repository, client: UwClient, settings: Settings) -> None` (`worker/jobs/cockpit_daily_snapshot.py:52`):

1. **`ticker_filter` does not exist yet, and neither does `market_date`.** Round 1 owns the date parameter; the per-ticker filter is this plan's requirement — without it, healing one ticker-date re-snapshots all four cockpit tickers. If round 1 shipped only `market_date`, add `ticker_filter` here and say so in the commit.
2. **It returns `None` and it takes an advisory lock.** `if not repo.try_advisory_lock(COCKPIT_SNAPSHOT_LOCK): return` (key 92201) — so if the nightly cockpit job is mid-run, the heal returns immediately having written nothing, `_verify_covered` fails, and the item is recorded `no_data`, i.e. *"the provider has no data for this date"* — a false statement about UW. Make the function return an `int` row count and **raise** (not silently return) when the lock is held, so the healer marks the item `failed` with a real error instead of libelling the provider. That distinction is the whole point of the `no_data` status.

```python
    "replay": HealSpec("replay", "uw", "per_ticker_date", _run_replay, est_per_item=17),
    "cockpit_replay": HealSpec(
        "cockpit_replay", "uw", "per_ticker_date", _run_cockpit_replay, est_per_item=6
    ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_data_gap_replay_adapter.py -v`
Expected: PASS

- [ ] **Step 6: Promote the 13 datasets**

Set `audit_mode="strict_ticker_date"`, `provider="uw"`, `granularity="per_ticker_date"`, `reason_verified_on=date(2026, 8, 16)`, and:

`healer_adapter="replay"` on the twelve `run_single_stock` writes — `oi_by_strike`, `oi_change_events`, `greeks_by_expiry_strike`, `exposures_by_expiry_strike`, `exposures_summary`, `iv_term_snapshots`, `interpolated_iv_snapshots`, `risk_reversal_skew_history`, `max_pain_by_expiry`, `pcr_history`, `dark_pool_events`, `option_contract_snapshots`.

`healer_adapter="cockpit_replay"` on the three cockpit writes — `iv_rank_history`, `option_chain_per_strike`, `matrix_state_snapshots`. The cockpit runs on 4 index tickers, not the 170-name watchlist, so their strict denominator is a `subset`, not the watchlist; mirror that scope rather than forcing a 170-ticker denominator that manufactures 166 phantom gaps per session. Verified: `data_freshness.py:181` pins the cockpit set to `frozenset({"SPX", "SPY", "QQQ", "IWM"})` and comments it as "same cockpit set as iv_rank_history"; the latest production snapshot reads `expected_count = 4` for `iv_rank_history`, `option_chain_per_strike` and `matrix_state_snapshots`.

**That mechanism does not exist yet — build it first.** `_scan_strict_ticker_date` hardcodes `tickers = sorted({t.upper() for t in active})` (`data_gap_healer.py:1148`); there is no per-entry scope, so promoting the cockpit tables as-is would generate 166 phantom gaps per session per table and the healer would spend UW budget on all of them. Mirror the field the freshness monitor already has:

```python
# DatasetRegistryEntry, alongside reason_verified_on
    expected_tickers: frozenset[str] | None = None  # None -> active watchlist.
    # Mirrors MonitoredTable.expected_tickers for by-design-partial datasets
    # (the 4-name cockpit set), so the strict denominator stops being global.
```

```python
# _scan_strict_ticker_date, replacing the hardcoded line
    scope = entry.expected_tickers or active
    tickers = sorted({t.upper() for t in scope})
    eligible_by_date = {
        d: eligible_tickers_for_date(list(scope), d, caveats) for d in calendar
    }
```

with a test that a 4-name entry over 2 sessions yields at most 8 expected pairs, never 340. Then set `expected_tickers=frozenset({"SPX", "SPY", "QQQ", "IWM"})` on the three cockpit entries.

`oi_by_expiry` is **not** in this list — Task 6 excludes it as a dead table (0 rows, no writer).

`oi_change_events` **can** be `strict_ticker_date` — verified against migration `001`: its ticker column is `underlying_symbol` and its date column is `curr_date`, and both already appear in `_TICKER_COL_PREFERENCE` / `_DATE_COL_PREFERENCE`, so auto-detection resolves them without an override. (The freshness monitor comments it as "ticker-less" because *it* looks for a literal `ticker` column; that comment is about the monitor, not the table.) One caveat worth knowing: its `run_id` carries `REFERENCES scan_runs(run_id) ON DELETE CASCADE`, so pruning `scan_runs` deletes history here — if rows vanish without an outage, check that first.

`option_intraday_buckets` cascades off `oi_change_events`: the intraday job derives its mover set from OI changes, so it cannot rebuild until those rows exist. Give it `healer_adapter="intraday_buckets"`. **No extraction is needed** — the core is already a proper function that the CLI merely calls:

```python
def _run_intraday_buckets(ctx: HealContext, ticker: str, market_date: date) -> int:
    """option_intraday_buckets derives its mover set from oi_change_events, so
    this only produces rows AFTER that dataset is healed in the same run."""
    from uw_scan.worker.jobs.option_intraday_jobs import backfill_intraday_history

    out = backfill_intraday_history(
        repo=ctx.repo,
        client=ctx.uw_client(),
        settings=ctx.settings,
        tickers=[ticker],
        since=market_date,
        until=market_date,
    )
    return int(sum(out.values()))
```

Signature verified at `worker/jobs/option_intraday_jobs.py:152` — `(*, repo, client, settings, tickers: list[str], since: date, until: date, top_n=DEFAULT_TOP_N, lock_key=INTRADAY_BACKFILL_LOCK) -> dict[str, int]`. It takes its own advisory lock (`INTRADAY_BACKFILL_LOCK`); check whether a held lock returns silently, and if so give it the same raise-don't-lie treatment as the cockpit job above.

`iv_smile_snapshots` is the second cascade, and a **zero-UW** one: it is a pure re-derivation of `greeks_by_expiry_strike`, so once the replay restores greeks it needs only a DB pass. Do not reach for `run_volatility_backfill` — its signature is `(*, client, repo, run_id, ticker, nearest_expiries: list[str]) -> str`, i.e. it re-fetches from UW and needs an expiry list. Reuse the existing pure builder instead:

```python
def _run_iv_smile_rederive(ctx: HealContext, ticker: str, market_date: date) -> int:
    """Pure DB re-derivation — zero UW spend. Cascades off greeks_by_expiry_strike,
    so it must run AFTER the replay in the same run."""
    from uw_scan.reports.iv_smile_builder import build_iv_smile_snapshot_rows

    rows = build_iv_smile_snapshot_rows(
        ctx.repo, ticker=ticker, market_date=market_date
    )
    return ctx.repo.upsert_iv_smile_rows(rows) if rows else 0
```

Check `build_iv_smile_snapshot_rows`' real signature at `reports/iv_smile_builder.py:9` before writing this — the call at `volatility_series.py:528` shows how the production path invokes it, and that call is the contract to mirror. Register it `("iv_smile_rederive", "db", "per_ticker_date", …, est_per_item=0)` and promote `iv_smile_snapshots` to `strict_ticker_date` (it is keyed `(ticker, market_date, expiry, strike)`), or the `per_ticker_date` adapter is dead code.

Record the ordering dependency in its reason — it must heal **after** `oi_change_events` in the same run. `execute_run` iterates the registry in declaration order, so placing this entry after `oi_change_events` in `REGISTRY` is what enforces it; say so in the reason so nobody reorders the list innocently.

Per the memory note on new strict tables, each promotion needs its registry entry *and* the regenerated policy doc in this same commit.

- [ ] **Step 7: Regenerate, run every gate**

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
uv run pytest tests/unit/reports/ tests/integration/scripts/ tests/integration/worker/ tests/integration/api/test_health_gap_healer.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/reports/data_gap_healer.py src/uw_scan/worker/jobs/data_gap_adapters.py \
        src/uw_scan/config.py docs/runbooks/data-gap-dataset-policy.md \
        tests/integration/worker/test_data_gap_replay_adapter.py
git commit -m "feat(healer): strict audit for the replay-backfilled options-chain set, heal budget-gated"
```

---

### Task 8: Measure the widening on the mini and record it

> **Ordering note:** Tasks 9 and 10 were added after review and land *before* this one. Run Task 8 last so its artifact measures the finished state — including the per-dataset budget slice and the full 143-dataset disposition. If you execute 1–8 first and 9–10 later, re-run Task 8 afterwards rather than leaving a stale artifact.

**Files:**
- Create: `docs/research/2026-08-16-healer-coverage-before-after.md`
- Modify: `CHANGELOG.md` (`[Unreleased]`)

Per the standing rule, a result that only ever existed in stdout did not happen. This task turns the plan's claim ("the healer now sees more") into a recorded measurement.

- [ ] **Step 1: Capture the BEFORE numbers from the current production snapshot**

Before deploying, on the mini:

```bash
ssh macmini 'bash -lc "docker exec -i argon-api-1 /app/.venv/bin/python - <<PY
from uw_scan.reports.data_gap_healer import REGISTRY
from collections import Counter
print(Counter(e.audit_mode for e in REGISTRY))
print(sum(1 for e in REGISTRY if e.healer_adapter))
PY"'
```

Record `strict_ticker_date` + `strict_session` counts and the adapter count.

- [ ] **Step 2: Deploy the branch and run the widened audit**

```bash
ssh macmini 'bash -lc "docker exec argon-worker-uw-0-1 /app/.venv/bin/python \
  scripts/backfill/data_gap_healer.py audit --start 2026-08-01 --end 2026-08-16"'
```

Expected: the spine banner is silent (the reference was rebuilt in round 1), and `total_gaps` is now non-zero for the newly-strict datasets — **a rising number here is the success criterion, not a regression.** It is the previously-invisible backlog becoming visible.

- [ ] **Step 3: Confirm the monitor now flags the table it used to pass**

```bash
ssh macmini 'bash -lc "docker exec -i argon-worker-uw-0-1 /app/.venv/bin/python - <<PY
from datetime import date
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    print(data_freshness_monitor(
        repo=Repository(c, schema=s.db_schema), settings=s, today=date.today()
    ))
PY"'
```

(An `import` alone proves nothing — the monitor has to actually run and persist a row before the query below has anything to read.)

Then query the snapshot:

```sql
SELECT table_name, coverage_pct, sessions_missing, frozen
  FROM uw_scan.data_freshness_snapshots
 WHERE run_date = (SELECT max(run_date) FROM uw_scan.data_freshness_snapshots)
   AND sessions_missing > 0
 ORDER BY sessions_missing DESC;
```

Expected: `risk_reversal_skew_history` appears with `sessions_missing >= 3` while `coverage_pct` still reads 1.0 — the exact pair of numbers that proves E2 is now detected rather than hidden.

- [ ] **Step 3b: Confirm the budget slice actually spreads the spend (Task 9)**

Read the nightly run's `summary_jsonb`:

```sql
SELECT id, finished_at,
       summary_jsonb->'budget_spent' AS spent,
       summary_jsonb->'outcome'      AS outcome
  FROM uw_scan.data_gap_runs ORDER BY id DESC LIMIT 3;
```

Before Task 9, a night with a large `option_surface_grid_daily` backlog shows the UW bucket at the full cap and a large `skipped_budget` count concentrated in every *other* dataset. After it, `skipped_budget` should still be non-zero (the backlog is genuinely multi-night) but spread across datasets rather than sitting entirely behind the first one. Record both shapes in the artifact — a backlog that takes ~7 nights at 12k is the honest outcome, not a regression.

Also check the auto-caveat is firing and is not over-firing:

```sql
SELECT dataset, count(*) FROM uw_scan.data_gap_caveats
 WHERE source = 'auto' GROUP BY 1 ORDER BY 2 DESC;
```

A steadily growing count on datasets with genuinely out-of-window history is correct. A count growing on a dataset that *should* be healable means an adapter is broken and the caveat is hiding it — investigate before accepting.

- [ ] **Step 4: Write the artifact**

Create `docs/research/2026-08-16-healer-coverage-before-after.md` with: the before/after `audit_mode` histogram, the before/after adapter count, the before/after `total_gaps` for 2026-08-01..16, the `sessions_missing` table, and the exact reproduce commands from Steps 1–3.

- [ ] **Step 5: CHANGELOG and commit**

Add under `[Unreleased]`:

```markdown
### Fixed
- Gap healer: the trading-day spine now unions an independently-sourced SPY OHLC
  witness, so an outage can no longer erase the evidence of its own outage
  (measured under-report: 1,276 gaps vs 8,080 real).
- Gap healer: `greek_exposure_daily` heals the 11 `gex_scan_tickers` instead of
  silently skipping them; the adapter writes its own rows from UW's full series.
- Freshness monitor: new `sessions_missing` counts under-covered expected
  sessions, so a partial heal no longer scores a multi-day hole as 100% covered.

### Added
- Heal adapters for CRI/VCG/Canary recovery, GRG (`as_of`), the vol-index and
  credit-ETF lake syncs, and the two UW event logs.
- `DatasetRegistryEntry.reason_verified_on` — a refusal to backfill must now
  carry the date the provider was actually probed.
```

```bash
git add docs/research/2026-08-16-healer-coverage-before-after.md CHANGELOG.md
git commit -m "docs: record healer coverage before/after and changelog"
```

---

### Task 9: One dataset's backlog stops starving every other dataset

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (`RequestBudget`, `execute_run`)
- Modify: `src/uw_scan/storage/data_gap_healer_repository.py` (`count_recent_no_data`)
- Modify: `src/uw_scan/config.py` (2 settings)
- Test: `tests/integration/worker/test_data_gap_budget_fairness.py` (create)

**Interfaces:**
- Produces: `RequestBudget(uw_cap, *, dataset_share: float | None = None)`, `.begin_dataset(name)`, and a `can_spend` that honours both the global cap and the per-dataset slice.
- Produces: `DataGapHealerRepository.count_recent_no_data(dataset, ticker, data_date, *, runs: int) -> int`.

**The two ways the healer wastes its budget.** Both are measured against production config, not hypothetical — the mini runs `data_gap_healer_enabled=True`, `max_uw_calls=12000`, `start=2026-01-01`, all datasets.

1. **Starvation.** `execute_run` groups claimed items by dataset and runs each group to completion against one shared `RequestBudget`. `option_surface_grid_daily` is the first UW spender in `REGISTRY` and costs `est_per_item=20`. A 4,206-item surface backlog needs ~84,120 calls — **seven nights at 12k** — during which it consumes the entire nightly cap and every UW dataset behind it records `skipped_budget`. The backlog does drain (healed items do not reappear, and `data_gap_healer_start` is an absolute date rather than a sliding window, so nothing ages out of scope) — but it drains by blocking everything else for a week.

2. **The permanent `no_data` tax.** The audit is a set-difference against the real table, so an item the provider genuinely cannot serve — a ticker-date past UW's ~180-day window — is missing again tomorrow, re-planned as a fresh item, and re-attempted at full `est_per_item` **every night, forever**. `upsert_caveat` and the `eligible_tickers_for_date` filter already exist to suppress exactly this; nothing populates them automatically. At 20 calls an item, a few hundred unrecoverable surface dates is a permanent multi-thousand-call nightly levy against a 12k cap.

Neither is a correctness bug, which is why Tasks 1–8 do not touch them: the healer's *answers* are right, its *scheduling* is not. Tasks 4–7 wire ~30 more datasets into the same fixed cap, so contention gets worse before this lands.

- [ ] **Step 1: Add the settings**

In `src/uw_scan/config.py`, beside `data_gap_healer_max_uw_calls`:

```python
    # No single dataset may take more than this share of one night's UW cap.
    # 0.4 lets a big backfill make real progress (~7 nights for a 4.2k-item
    # surface backlog at 12k/night) without blocking every other dataset for
    # the whole week. Set to 1.0 to restore the old drain-it-all behaviour.
    data_gap_healer_dataset_share: float = 0.4
    # Consecutive nightly no_data verdicts before the scope is auto-caveated.
    # 0 disables. The provider has told us three times it has no such date.
    data_gap_healer_no_data_caveat_after: int = 3
```

Wire both into `Settings.from_env()` alongside the existing healer env reads.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/worker/test_data_gap_budget_fairness.py`:

```python
"""A big backlog must not consume the whole nightly cap (Task 9)."""

from __future__ import annotations

from uw_scan.worker.jobs.data_gap_adapters import RequestBudget


def test_dataset_slice_caps_one_dataset() -> None:
    b = RequestBudget(uw_cap=1000, dataset_share=0.4)  # slice = 400

    b.begin_dataset("option_surface_grid_daily")
    spent = 0
    while b.can_spend("uw", 20):
        b.record("uw", 20)
        spent += 20
    assert spent == 400, "one dataset must stop at its slice, not the global cap"

    # A second dataset still has room, which is the entire point.
    b.begin_dataset("uw_gex_levels_daily")
    assert b.can_spend("uw", 20)


def test_global_cap_still_binds_across_datasets() -> None:
    b = RequestBudget(uw_cap=1000, dataset_share=0.4)
    for i in range(3):  # 3 x 400 would be 1200 > 1000
        b.begin_dataset(f"ds{i}")
        while b.can_spend("uw", 100):
            b.record("uw", 100)
    assert b.spent["uw"] == 1000, "the global cap must still win"


def test_no_share_configured_behaves_exactly_as_before() -> None:
    b = RequestBudget(uw_cap=1000)
    b.begin_dataset("anything")
    while b.can_spend("uw", 100):
        b.record("uw", 100)
    assert b.spent["uw"] == 1000


def test_uncapped_provider_is_unaffected() -> None:
    b = RequestBudget(uw_cap=100, dataset_share=0.4)
    b.begin_dataset("lake_thing")
    assert b.can_spend("massive", 10_000)  # only uw is capped
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_data_gap_budget_fairness.py -v`
Expected: FAIL — `TypeError: RequestBudget.__init__() got an unexpected keyword argument 'dataset_share'`

- [ ] **Step 4: Implement the slice**

Replace `RequestBudget` in `src/uw_scan/worker/jobs/data_gap_adapters.py`:

```python
class RequestBudget:
    """Per-provider spend tracker. Only UW is capped; the rest are unbounded.

    `dataset_share` additionally caps any SINGLE dataset at that fraction of the
    UW cap, so one large backlog cannot drain the whole night and leave every
    other dataset on `skipped_budget`. None/1.0 reproduces the original
    drain-it-all behaviour exactly.
    """

    def __init__(self, uw_cap: int | None, *, dataset_share: float | None = None) -> None:
        self.uw_cap = uw_cap
        self.dataset_share = dataset_share
        self.spent: dict[str, int] = {b: 0 for b in _BUCKETS}
        self.by_dataset: dict[str, int] = {}
        self._current: str | None = None

    def begin_dataset(self, dataset: str) -> None:
        self._current = dataset
        self.by_dataset.setdefault(dataset, 0)

    def _slice(self) -> int | None:
        if self.uw_cap is None or not self.dataset_share or self.dataset_share >= 1:
            return None
        return max(1, int(self.uw_cap * self.dataset_share))

    def can_spend(self, provider: str, n: int) -> bool:
        if provider != "uw" or self.uw_cap is None:
            return True
        if self.spent["uw"] + n > self.uw_cap:
            return False
        cap = self._slice()
        if cap is not None and self._current is not None:
            if self.by_dataset.get(self._current, 0) + n > cap:
                return False
        return True

    def record(self, provider: str, n: int) -> None:
        if provider in self.spent:
            self.spent[provider] += n
        if provider == "uw" and self._current is not None:
            self.by_dataset[self._current] = self.by_dataset.get(self._current, 0) + n

    def as_dict(self) -> dict[str, int]:
        return dict(self.spent)
```

In `execute_run`, call `ctx.budget.begin_dataset(dataset)` as the first statement inside the `for dataset, items in groups.items():` loop — before the entry/spec lookups, so a dataset that falls through to `no_data` still gets its slice reset.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_data_gap_budget_fairness.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Pass the setting through**

In `worker/jobs/data_gap_healer.py::_run_nightly`, the budget is built as `RequestBudget(settings.data_gap_healer_max_uw_calls)`. Add the share:

```python
        budget=RequestBudget(
            settings.data_gap_healer_max_uw_calls,
            dataset_share=settings.data_gap_healer_dataset_share,
        ),
```

Do the same in `resume_run` if it constructs its own budget (`grep -n "RequestBudget(" src/ scripts/`). Leave the CLI's `execute` path on the default unless it already reads settings — an operator draining one dataset on purpose should not be sliced.

- [ ] **Step 7: Stop re-attempting what the provider has refused three times**

Add to `src/uw_scan/storage/data_gap_healer_repository.py`:

```python
    def count_recent_no_data(
        self, dataset: str, ticker: str | None, data_date: date, *, runs: int
    ) -> int:
        """How many of the last `runs` runs recorded no_data for this scope.

        The audit is a set-difference against the real table, so a date the
        provider genuinely cannot serve reappears as a fresh item every night
        and is re-attempted at full cost forever. This is how we notice.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                WITH recent AS (
                    SELECT id FROM data_gap_runs ORDER BY id DESC LIMIT %s
                )
                SELECT count(*)::int FROM data_gap_items i
                 WHERE i.run_id IN (SELECT id FROM recent)
                   AND i.dataset = %s
                   AND i.data_date = %s
                   AND i.status = 'no_data'
                   AND (%s::text IS NULL OR UPPER(i.ticker) = UPPER(%s))
                """,
                (runs, dataset, data_date, ticker, ticker),
            )
            return cur.fetchone()[0]
```

Then in `_verify_and_mark`, on the `no_data` branch only:

```python
    else:
        ctx.gap.mark_item_no_data(
            it["id"], reason=no_data_reason, actual_requests=spec.est_per_item
        )
        outcome["no_data"] += 1
        after = getattr(ctx.settings, "data_gap_healer_no_data_caveat_after", 0)
        if after and no_data_reason == "provider_no_data" and it["data_date"]:
            prior = ctx.gap.count_recent_no_data(
                entry.table_name, it["ticker"], it["data_date"], runs=after
            )
            if prior >= after:
                ctx.gap.upsert_caveat(
                    Caveat(
                        dataset=entry.table_name,
                        ticker=it["ticker"],
                        start_date=it["data_date"],
                        end_date=it["data_date"],
                        reason=f"provider returned no data {prior}x consecutively",
                        source="auto",
                    )
                )
                outcome["auto_caveated"] += 1
```

Import `Caveat` from `uw_scan.reports.data_gap_healer` at the top of the module (the four-name import block already there). Only `provider_no_data` qualifies — never `no_adapter`, `unsupported_granularity`, or `not_recomputed`, which are *our* bugs, not the provider's answer, and caveating them would hide exactly the class of defect Tasks 1–8 exist to surface.

- [ ] **Step 8: Test the auto-caveat, including what must NOT be caveated**

Add to the same test file:

```python
def test_auto_caveat_only_fires_on_provider_no_data(seeded_db_empty_cards) -> None:
    """our-bug reasons must never be caveated away — that would hide the bug."""
    from uw_scan.worker.jobs.data_gap_adapters import _verify_and_mark

    assert "no_adapter" != "provider_no_data"  # documents the intent of the guard
    # Full behavioural coverage lives in the CLI test below; this asserts the
    # guard exists so a later refactor cannot quietly widen it.
    import inspect

    src = inspect.getsource(_verify_and_mark)
    assert 'no_data_reason == "provider_no_data"' in src
```

Prefer a real behavioural test if the fixture cost is reasonable: seed three prior runs with `no_data` items for one `(dataset, ticker, data_date)`, run a heal whose adapter writes nothing, and assert `gap.list_caveats()` gained exactly one row with `source='auto'`.

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest tests/integration/worker/ tests/integration/scripts/ tests/unit/reports/ -v
git add src/uw_scan/worker/jobs/data_gap_adapters.py \
        src/uw_scan/storage/data_gap_healer_repository.py \
        src/uw_scan/worker/jobs/data_gap_healer.py src/uw_scan/config.py \
        tests/integration/worker/test_data_gap_budget_fairness.py
git commit -m "feat(healer): per-dataset budget slice + auto-caveat after repeated provider no_data"
```

---
### Task 10: Disposition the 25 datasets the daily scope never looked at

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (2 adapters + specs)
- Modify: `src/uw_scan/reports/data_gap_healer.py` (19 registry entries)
- Modify: `tests/unit/reports/test_data_gap_reasons.py` (widen the gate to every cadence)
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerate)

**Interfaces:**
- Consumes: `worker.jobs.fundamental_refresh.fundamental_refresh(*, conn: psycopg.Connection, settings: Settings) -> dict[str, Any]` — chains routing → scoring → anchor bands at **zero UW/IB spend**.
- Produces: `HEAL_SPECS["fundamental_refresh"]`, `granularity="run_once"`, `provider="db"`, `est_per_item=0`.

**Why this task exists.** Tasks 1–8 scoped their coverage ledger to `equity_session`/`daily` cadence — 58 of the 143 registered datasets. That was a deliberate scope, stated in the ledger, but it is not "full coverage". The other 85 break down as:

| bucket | count | disposition |
|---|---|---|
| `research_artifact` / `provenance` / `excluded` / `operational_state` | 60 | existence-only by design; nothing to heal, correctly so |
| weekly / monthly / event / liveness **with** an adapter | 6 | already covered |
| weekly / monthly / event / liveness **without** one | 19 | **this task** |

Of those 19: **13 are `liveness`** (`watchlist`, `intraday_quote`, `signal_hits`, `trade_insight_*`, `technical_live`, …) — live state, not a time series, so no-adapter is almost certainly right. But **all 13 carry an empty `reason`**, i.e. an undocumented refusal, which is precisely the shape that proved wrong eight times over in Tasks 4–6. An unstated assumption is not a decision.

**3 are `event`-cadence fundamentals and are healable for free — their own reason strings already name the job.** `fundamental_scores`: *"derived from fundamental_statement_obs; re-run worker/jobs/fundamental_scoring"*. `valuation_anchors`: *"derived from fundamental_statement_obs + fundamental_company_type"*. The `fundamental_refresh` job chains exactly those stages at zero provider spend and already runs nightly at 18:20 ET. The registry describes the heal path in prose and then declines to wire it.

**3 are monthly external failures** (`wgc_etf_monthly`, `wgc_etf_monthly_canonical`, `cb_gold_reserves_monthly`) — the source needs an auth cookie and has no historical API. They stay refused, but dated.

- [ ] **Step 1: Widen the refusal gate to every cadence**

In `tests/unit/reports/test_data_gap_reasons.py`, `test_every_refusal_is_dated` currently filters `expected_frequency in ("equity_session", "daily")`. Drop that filter — a refusal is a refusal whatever the cadence:

```python
def test_every_refusal_is_dated() -> None:
    """A provider='none' dataset must say WHEN the refusal was measured.

    Cadence-independent on purpose: the daily scope was Tasks 1-8's ledger
    boundary, not a statement that weekly/monthly/liveness entries may carry
    undocumented assumptions. All 13 liveness entries had EMPTY reasons.
    """
    undated = sorted(
        e.table_name
        for e in REGISTRY
        if e.provider == "none"
        and e.audit_mode not in ("excluded", "provenance", "operational_state")
        and e.reason_verified_on is None
    )
    assert not undated, (
        "undated refusals are assumptions; probe the provider and stamp the "
        f"date, or wire an adapter: {undated}"
    )
```

- [ ] **Step 2: Run it to see the real scope**

Run: `uv run pytest tests/unit/reports/test_data_gap_reasons.py::test_every_refusal_is_dated -v`
Expected: FAIL, listing ~19 tables. That list is this task's worklist — work it top to bottom.

- [ ] **Step 3: Wire the fundamentals adapter**

In `data_gap_adapters.py`:

```python
def _run_fundamental_refresh(ctx: HealContext) -> int:
    """Routing -> subscores -> anchor bands. Zero UW/IB spend: every stage reads
    fundamental_statement_obs and the lake, so this heals fundamental_scores and
    valuation_anchors without touching a provider.

    It deliberately does NOT ingest — new filings come from
    scripts/backfill/fundamental_ingest_backfill.py, which is why
    fundamental_statement_obs keeps its own disposition below.
    """
    from uw_scan.worker.jobs.fundamental_refresh import fundamental_refresh

    out = fundamental_refresh(conn=ctx.repo.conn, settings=ctx.settings)
    scoring = out.get("scoring") or {}
    anchors = out.get("anchors") or {}
    return int(scoring.get("written", 0)) + int(anchors.get("written", 0))
```

Confirm the real counter names in `fundamental_refresh`'s returned dict before committing (`grep -n "return" -B 8 src/uw_scan/worker/jobs/fundamental_refresh.py`) — the heal is verified against the table regardless, so a wrong key is cosmetic, but do not guess in committed code.

```python
    "fundamental_refresh": HealSpec(
        "fundamental_refresh", "db", "run_once", _run_fundamental_refresh,
        est_per_item=0,
    ),
```

Set `provider="db"`, `granularity="run_once"`, `healer_adapter="fundamental_refresh"` on **`fundamental_scores`** and **`valuation_anchors`**, with:

```python
            reason="derived from fundamental_statement_obs; worker/jobs/"
            "fundamental_refresh re-runs routing -> scoring -> anchors at zero "
            "provider spend. The old reason named this job and then declined to "
            "wire it.",
            reason_verified_on=date(2026, 8, 16),
```

`run_once` is correct here — these are `freshness_only`, and only the `run_once*` channel dispatches for a non-strict dataset (see the two-heal-channels section). A `per_ticker_date` adapter would be dead code.

- [ ] **Step 4: Disposition `fundamental_statement_obs`**

This one is **not** free — it is quarterly filings over the fundamental universe, ingested by `scripts/backfill/fundamental_ingest_backfill.py`, and `fundamental_refresh` deliberately does not ingest. Either wire `worker/jobs/fundamental_ingest.fundamental_ingest` as a `run_once_lookback` adapter (check its signature and provider cost first — it reads massive/UW), or record a dated refusal naming the script. **Pick one and write it down**; do not leave it undated.

- [ ] **Step 5: Date the 13 liveness refusals**

These are live state, not time series — a missing row means "not currently true", not "history was lost". That is a real and correct disposition; it has simply never been written down. Give each a reason of this shape, adjusted per table:

```python
            reason="live state, not a time series: a row asserts what is true NOW "
            "and is rewritten in place. A missing row means the condition does not "
            "hold, not that history was lost — there is nothing to backfill.",
            reason_verified_on=date(2026, 8, 16),
```

**Two deserve a second look before you paste that, because their names suggest a series:**
- `technical_live` — has its own `technical_live` repository and a 104 migration; confirm it is genuinely overwrite-in-place and not an append-only intraday history. If it appends, it belongs in the daily scope with a real adapter, not here.
- `scanner_candidate_snapshots` — "snapshots" is series-shaped naming. Check whether rows accumulate per scan or are replaced.

If either accumulates, reclassify it rather than papering over it with the liveness boilerplate. That is the whole point of forcing a written reason.

- [ ] **Step 6: Date the 3 monthly external refusals**

```python
            reason="World Gold Council source requires an interactive auth cookie "
            "and exposes no historical API; the ingest can only capture what is "
            "live at fetch time. Same failure as etf_holdings_daily.",
            reason_verified_on=date(2026, 8, 16),
```

on `wgc_etf_monthly`, `wgc_etf_monthly_canonical`, `cb_gold_reserves_monthly`.

- [ ] **Step 7: Run the gate until it is green**

Run: `uv run pytest tests/unit/reports/test_data_gap_reasons.py -v`
Expected: PASS. Every `provider="none"` dataset in the registry now carries a dated, measured reason — no undocumented refusals remain at any cadence.

- [ ] **Step 8: Assert the full-coverage claim as a test, not a paragraph**

Create `tests/unit/reports/test_full_coverage.py`:

```python
"""Every registered dataset has a disposition. No silent gaps. (Task 10)"""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import REGISTRY

# Audit modes that are existence-only by design — nothing to heal.
_BY_DESIGN = ("excluded", "provenance", "operational_state", "research_artifact")


def test_every_dataset_is_dispositioned() -> None:
    """One of exactly three states, for all 143 entries:
      - by-design existence-only, or
      - has a heal adapter, or
      - carries a dated, measured refusal.
    Anything else is a dataset nobody decided about.
    """
    undecided = sorted(
        e.table_name
        for e in REGISTRY
        if e.audit_mode not in _BY_DESIGN
        and not e.healer_adapter
        and e.reason_verified_on is None
    )
    assert not undecided, f"no recorded decision for: {undecided}"


def test_the_coverage_ledger_numbers_are_still_true() -> None:
    """The plan's ledger table is a claim; this is the claim as an assertion."""
    scoped = [
        e
        for e in REGISTRY
        if e.audit_mode not in _BY_DESIGN
        and e.expected_frequency in ("equity_session", "daily")
    ]
    assert len(scoped) == 58, (
        f"the daily/equity_session scope moved to {len(scoped)}; update the "
        "Coverage Ledger in docs/superpowers/plans/"
        "2026-08-16-healer-coverage-hardening.md"
    )
    unwired = [e for e in scoped if not e.healer_adapter and not e.reason_verified_on]
    assert not unwired, [e.table_name for e in unwired]
```

`test_the_coverage_ledger_numbers_are_still_true` is deliberately brittle: if someone registers a new daily dataset, it fails and points at the ledger. A silently-growing registry is how the healer got to 45 undocumented refusals in the first place.

- [ ] **Step 9: Regenerate, verify, commit**

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
uv run pytest tests/unit/reports/ tests/integration/worker/ -v
git add src/uw_scan/reports/data_gap_healer.py src/uw_scan/worker/jobs/data_gap_adapters.py \
        docs/runbooks/data-gap-dataset-policy.md tests/unit/reports/test_data_gap_reasons.py \
        tests/unit/reports/test_full_coverage.py
git commit -m "feat(healer): disposition all 143 datasets; wire fundamentals, date every refusal"
```

---
## Out of Scope (and why)

After Tasks 1–10 the only registered dataset without a heal path or a dated refusal is **`gex_snapshots`** (`gex.run` resolves a live spot and raises without one; historical replay needs a per-(ticker, date) spot source). Task 10's `test_every_dataset_is_dispositioned` forces it to carry a dated refusal, so it is a recorded decision rather than a hole.

- **Working the 39,877-item new-ticker backfill queue.** Those are not defects — `reconcile_watchlist_lifecycle`'s docstring is explicit that a newly-added ticker's missing history *is* the backfill schedule. ~6,440 items fall inside UW's ~180-day horizon, and `option_surface_grid_daily` alone would cost ~143k calls, more than a full day's ceiling. That is an operator budget decision, not an engineering fix.
- **Making `vrp_macro_signal` date-aware.** Round 1 owns the writer-side date plumbing. Task 5's GRG test is the pattern this plan contributes; applying it to VRP belongs with the VRP change.
- **`exchange_inventory_daily`, `wgc_etf_monthly`, `cb_gold_reserves_monthly`, `macro_series_monthly`, `etf_flows/holdings_daily`.** Pre-existing external-source failures (CME returns 403 and blocks scraping since 2026-06-01; the WGC sources need an auth cookie). Nothing in the healer can fix a provider that refuses.
- **The three permanently-refused UW datasets.** Measured, not assumed: identical response bodies across `date` values. Task 6 records the measurement; there is nothing to build.
- **A holiday calendar table.** Rejected in Task 2 with reasoning — the SPY witness gets the same correctness for less standing maintenance.

## Risks

| Risk | Mitigation |
|---|---|
| The SPY witness is itself empty after a *total* outage, so the union adds nothing | `daily_ohlc` is `strict_ticker_date` with a working massive adapter and was the first thing healed in round 1. Task 2 Step 5 prints the repair command; consider running the `daily_ohlc` heal as an audit preflight if this bites twice. |
| `sessions_missing` is noisy on tables that are legitimately partial by design | It reuses the existing `LOW_COVERAGE_PCT = 0.5` threshold and `MonitoredTable.scope`, which already marks by-design-partial tables. Watch the first nightly run; raise the threshold per-table via `MonitoredTable` rather than weakening the metric. |
| Task 7's strict promotion makes `total_gaps` jump alarmingly | Expected and stated as the success criterion. Healing stays flag-off, so a big number costs nothing until the operator opts in. |
| The event-log adapters drift from the CLI's behaviour | They call `capture_intraday_flow_for` / `capture_dark_lit_for` directly — the same functions `_EVENTLOG` maps to — so there is one writer and no extraction. `tests/integration/scripts/` must stay green regardless. |
| `fetch_latest_gex` gains a param used by other callers | The new `as_of` is keyword-only and defaults to `None`, which reproduces the existing SQL exactly. `grep -rn "fetch_latest_gex" src/` before and after; the API/cockpit callers must stay untouched. |
| An adapter is wired to a dataset whose audit mode never produces gap items | The whole class is caught by Task 4 Step 8's `test_no_per_ticker_adapter_on_a_non_strict_dataset`. Review found this twice during Pass 3 (`grg_snapshots`, both UW event logs) — treat a failure there as real and fix the registry, never the test. |
| A heal that writes nothing gets recorded as `no_data` — libelling the provider | Two known sources: `cockpit_daily_snapshot`'s silent advisory-lock return, and `backfill_intraday_history`'s lock. Task 7 requires both to raise instead, so the item is `failed` with a real error. `no_data` must keep meaning "the provider does not have this". |
| Round 1 ships `market_date` but not `ticker_filter` / an int return | Task 7's preflight table checks all four requirements before any code is written, and says to fix them in round 1 rather than work around them here. |
| The per-dataset slice makes a big backfill take even longer | It does, and that is the trade: ~7 nights either way for a 4.2k-item surface backlog, but the other datasets stay current throughout instead of being blocked for the week. `data_gap_healer_dataset_share=1.0` restores drain-it-all for a deliberate one-dataset catch-up. |
| The auto-caveat hides a broken adapter instead of an absent provider | It fires only on `provider_no_data` — never `no_adapter`, `unsupported_granularity` or `not_recomputed`, which are our bugs. Task 8 Step 3b watches the `source='auto'` counts per dataset for exactly this. |
| A new dataset is registered later and silently escapes coverage | `test_the_coverage_ledger_numbers_are_still_true` pins the scoped count at 58 and fails on any change, pointing at the ledger. |
| A registry change lands without the regenerated policy doc | `tests/unit/reports/test_data_gap_dataset_policy.py` is a CI gate; every registry-touching task regenerates in the same commit. |
