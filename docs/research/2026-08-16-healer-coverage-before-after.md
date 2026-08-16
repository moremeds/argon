# Gap healer coverage hardening — before/after, measured

**Date:** 2026-08-16
**Branch:** `fix/healer-coverage-hardening`
**Plan:** `docs/superpowers/plans/2026-08-16-healer-coverage-hardening.md`
**Environment:** Mac mini `option_wizard` (production), read via
`docker exec argon-api-1 /app/.venv/bin/python`

BEFORE numbers are from the **deployed** `:latest` image. AFTER numbers are from
this branch's registry. The branch is **not deployed** — Task 8 Steps 2/3/3b
(post-deploy audit, monitor run, budget-slice check) are therefore **not** in
this artifact; see *Not yet measured* at the end.

---

## Headline: the deployed healer reports zero gaps during an active outage

```
run #76  audit window=2026-08-01..2026-08-16  total_gaps=0
```

Run on production at 2026-08-16. At that same moment, **11 monitored tables held
zero rows on three or more of the last five expected sessions**, and every one of
them reported `coverage_pct = 1.000` with `frozen = False`.

This is not the Aug 11–14 outage — that one was healed in round 1 and its tables
now read 170/170. This is a **second, still-open** outage, and neither instrument
saw it.

### Why the audit said 0

`scan_dataset` emits gap items for `strict_ticker_date` and `strict_session`
only. In the deployed registry that is **13 of 143** datasets, and those 13 are
genuinely covered. All 11 affected tables are `freshness_only`, so they were
never in the denominator. `total_gaps = 0` was a true statement about 9% of the
desk, presented as a statement about the desk.

### Why the freshness monitor said 100%

`coverage_pct` counts distinct tickers with a row within `grace_days` (4) of the
table's **own** `max_data_date`. A recovery run on 2026-08-16 wrote rows stamped
with a current date, which pulled `max_data_date` forward; the 4-day window then
reached back **over** the hole to Aug 10/11's healthy 173 tickers.

The partial write is what blinded it. **A partial heal makes the monitor blinder,
not sharper** — measured, not theorised.

---

## The 11 tables, as measured

Expected sessions from the unioned spine: `2026-08-10, 08-11, 08-12, 08-13, 08-14`
(Aug 15/16 are Sat/Sun — correctly absent). Expected watchlist tickers: 170.
`sess_miss` = sessions below `LOW_COVERAGE_PCT = 0.5`, i.e. the new
`sessions_missing` field.

| table | `coverage_pct` (deployed) | `sessions_missing` (new) | per-session distinct tickers |
|---|---|---|---|
| `options_volume_daily` | 1.000 | **4** | `[170, 0, 0, 0, 0]` |
| `option_chain_per_strike` | 1.000 | **4** | `[171, 0, 0, 0, 0]` |
| `uw_positioning` | 1.000 | **4** | `[173, 0, 0, 0, 0]` |
| `exposures_by_expiry_strike` | 1.000 | **3** | `[174, 0, 0, 0, 170]` |
| `oi_by_strike` | 1.000 | **3** | `[173, 0, 0, 0, 170]` |
| `greeks_by_expiry_strike` | 1.000 | **3** | `[173, 0, 0, 0, 170]` |
| `iv_term_snapshots` | 1.000 | **3** | `[174, 0, 0, 0, 170]` |
| `interpolated_iv_snapshots` | 1.000 | **3** | `[174, 0, 0, 0, 170]` |
| `max_pain_by_expiry` | 1.000 | **3** | `[173, 170, 0, 0, 0]` |
| `exposures_summary` | 1.000 | **3** | `[174, 170, 0, 0, 0]` |
| `pcr_history` | 1.000 | **3** | `[173, 169, 0, 0, 0]` |

Tables that are genuinely healthy — `daily_ohlc`, `vrp_daily`,
`greek_exposure_daily`, `option_surface_grid_daily`, `stock_analytics_daily`,
`realized_volatility_history`, `volatility_stats_history`,
`risk_reversal_skew_history`, `uw_gex_levels_daily`,
`uw_volatility_signal_daily`, `uw_short_pressure_daily`,
`uw_dark_lit_flow_prints`, `uw_intraday_option_flow_bars` — all score
`sessions_missing = 0`. **The new metric does not cry wolf**: 13 clean, 11 dirty,
and the split is exactly the deep-scan set.

### Root cause of this outage (not fixed by this branch)

`scan_runs` rows with a full-scan shape (`notes` NULL or `''`) by day:

```
2026-08-10  1321
2026-08-11  2342
   (Aug 12, 13, 14 — none)
2026-08-16   170
```

Every affected table is written by `pipeline.run_single_stock`. full_scan stopped
after Aug 11 and did not run again until a partial pass on Aug 16. Healing these
dates needs round 1's `market_date` plumbing (`full_scan_once` has no `date`
parameter), which is why they carry **dated refusals** on this branch rather than
adapters — see Task 7, blocked.

---

## Registry: before → after

| metric | before (deployed) | after (this branch) |
|---|---|---|
| registered datasets | 143 | 143 |
| `strict_ticker_date` | 10 | **12** |
| `strict_session` | 3 | **4** |
| strict total (audited for gaps) | 13 | **16** |
| `freshness_only` | 70 | 66 |
| `excluded` | 10 | 11 |
| heal adapters wired | 24 | **39** |
| entries with `reason_verified_on` | 0 (field absent) | **59** |
| datasets with no adapter **and** no dated refusal | 47 | **0** |

The last row is the point of the exercise. Every one of the 143 datasets is now
either existence-only by design, wired to an adapter, or carrying a refusal with
the date it was measured. Asserted as
`tests/unit/reports/test_full_coverage.py::test_every_dataset_is_dispositioned`.

---

## Spine union safety, measured

Task 2 unions SPY's massive `daily_ohlc` into the trading-day spine. The stated
risk is a phantom session — a witness bar on a non-trading day — which would
manufacture a gap for every strict dataset.

```
phantom weekend rows in the SPY witness, last 60d:   NONE
phantom weekend rows in the reference spine, last 60d: NONE
```

massive publishes SPY bars only on real sessions, confirmed on 60 days of
production data. The union cannot invent a session.

Separately, `risk_reversal_skew_history` **does** hold one row on Sunday
2026-08-09 (`JNK`, 1 row). It is harmless precisely because `_calendar_dates`
reads only the reference and the witness and never the audited dataset — the
"no self-union" property the original docstring was protecting. Had the spine
unioned datasets, that single JNK row would have created a phantom Sunday and a
170-ticker phantom gap in every strict table.

---

## Reproduce

```bash
# 1. registry state (deployed)
ssh macmini '/opt/homebrew/bin/docker exec -i argon-api-1 /app/.venv/bin/python - <<PY
from collections import Counter
from uw_scan.reports.data_gap_healer import REGISTRY
print(Counter(e.audit_mode for e in REGISTRY))
print(sum(1 for e in REGISTRY if e.healer_adapter))
PY'

# 2. the audit that reports 0
ssh macmini '/opt/homebrew/bin/docker exec argon-worker-uw-0-1 \
  /app/.venv/bin/python scripts/backfill/data_gap_healer.py audit \
  --start 2026-08-01 --end 2026-08-16'

# 3. the per-session table above (script committed alongside this note)
ssh macmini '/opt/homebrew/bin/docker exec -i argon-api-1 /app/.venv/bin/python -' \
  < docs/research/_scripts/2026-08-16-measure-sessions-missing.py

# 4. registry state (this branch, local)
uv run python -c "
from collections import Counter
from uw_scan.reports.data_gap_healer import REGISTRY
c=Counter(e.audit_mode for e in REGISTRY)
print(c, sum(1 for e in REGISTRY if e.healer_adapter),
      sum(1 for e in REGISTRY if e.reason_verified_on))"
```

---

## Not yet measured (requires deploying this branch)

Recorded honestly rather than omitted:

- **Post-deploy `total_gaps`.** The three audit-mode promotions (`grg_snapshots`,
  both UW event logs) will raise it. A rising number is the success criterion —
  it is previously-invisible backlog becoming visible — but the actual figure is
  unmeasured.
- **`sessions_missing` persisted by the real nightly monitor.** The table above
  was computed with the shipped definition against live data, but through a
  standalone script, not `data_freshness_monitor` writing
  `data_freshness_snapshots.sessions_missing`. Migration 120 is not applied on
  the mini.
- **The per-dataset budget slice (Task 9).** Needs a nightly run under the new
  `data_gap_healer_dataset_share=0.4` to compare `budget_spent` /
  `skipped_budget` shape against the current drain-it-all behaviour.
- **The auto-caveat counts (Task 9).** `data_gap_caveats WHERE source='auto'` is
  necessarily empty until the branch has run three nights.
- **Task 7 entirely.** Blocked on round 1
  (`docs/superpowers/plans/2026-08-16-historical-replay-backfill.md`); preflight
  verified 2026-08-16 that `run_single_stock` has no `market_date` and
  `cockpit_daily_snapshot` has no `market_date`/`ticker_filter`, returns `None`,
  and silently returns when `COCKPIT_SNAPSHOT_LOCK` is held.
