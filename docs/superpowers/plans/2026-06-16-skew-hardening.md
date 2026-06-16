# Skew Hardening — make the directional engine run, then harden it

**Status:** in progress (branch `feat/skew-hardening`, off `origin/main` @ 3874ac8)
**Goal:** Address the four review findings on the shipped Skew tab. The headline: the
evidence-gated directional engine is **dark in production** (verdict table empty →
every ticker NEUTRAL "no proven separation"). Make it run, fix the regime that starves
it, then the request-path and methodology honesty.

**Approval:** user approved all four + "one branch, milestone commits, one PR";
deferred the #4 regime decision to me (resolved below).

---

## Findings → milestones

| # | Finding | Milestone |
|---|---|---|
| data-bug | single-expiry term persisted as `flat` | **M0 ✅ committed** (`71febff`) |
| #4 | regime is a coin-flip AND fragments the verdict buckets | **M1** |
| #1 | `run_skew_markout`/`backfill` have no scheduler/script caller → feature dark | **M2** |
| #2 | GET recomputes O(n²) + writes on every request; no snapshot fast-path | **M3** |
| #3 | "borrow-clean" uses current borrow on historical dates (look-ahead) | **M4** |
| — | run on prod, verify, research note, review, PR | **M5** |

### #4 decision (locked)
Regime **leaves the verdict bucket key** (`asset_class × deviation × drive` only) — the
fragmentation is what starves verdicts with ~13mo of data. Robustness stays in the
**quarterly catastrophic-degradation gate** (already implemented, full history). The
**canonical CRI level** (latest `cri_snapshots.cri_level`) becomes the live regime tag
shown in the UI + lean basis, replacing the SPY-RV 50th-pct coin-flip. Historical
snapshot `regime` is no longer consumed by the markout, so no CRI-history-depth
dependency. The self-contained SPY-RV fallback is kept (threshold fixed 50→70th pct) for
when no CRI snapshot exists.

---

## M1 — #4: regime out of the bucket key + canonical CRI tag

**Files**
- Create `src/uw_scan/storage/migrations/076_skew_verdict_drop_regime.sql` — drop `regime`
  from `skew_directional_verdicts` PK + column. Idempotent, guarded by column-exists so a
  second `migrate.sh` is a no-op and never wipes freshly-computed verdicts.
- `src/uw_scan/storage/skew.py` — `upsert_skew_directional_verdict` / `get_skew_directional_verdict`
  drop the `regime` param+column; add `fetch_latest_market_regime()` → latest
  `cri_snapshots.cri_level` (basis='eod'), `None` if absent.
- `src/uw_scan/reports/skew_markout.py` — bucket key drops `regime`; upsert drops `regime`.
  Keep quarterly `_survives_window_gate`.
- `src/uw_scan/cards/skew_first_principles.py` — `resolve_directional_lean` drops the
  regime-mismatch gate (verdict no longer carries regime); `regime` kept only as basis
  context. `classify_market_regime` threshold 50→70 (fallback only).
- `src/uw_scan/reports/skew_analytics.py` + `worker/jobs/skew_analytics.py` —
  `build_skew_snapshot_row(..., regime: str | None = None)`: when provided use it (live/
  nightly pass canonical CRI), else fall back to `classify_market_regime`. Assembler +
  nightly look up `fetch_latest_market_regime()`; backfill keeps the self-contained label.
  Verdict lookup drops the `regime=` kwarg.

**Migration 076 idempotency pattern**
```sql
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='uw_scan' AND table_name='skew_directional_verdicts'
               AND column_name='regime') THEN
    ALTER TABLE uw_scan.skew_directional_verdicts DROP CONSTRAINT IF EXISTS skew_directional_verdicts_pkey;
    DELETE FROM uw_scan.skew_directional_verdicts;   -- stale under new key; markout repopulates
    ALTER TABLE uw_scan.skew_directional_verdicts DROP COLUMN regime;
    ALTER TABLE uw_scan.skew_directional_verdicts ADD PRIMARY KEY (asset_class, deviation_class, drive_class);
  END IF;
END $$;
```

**Tests** — update `test_skew_storage.py` verdict round-trip (no regime); `test_skew_markout.py`
bucketing; `resolve_directional_lean` matrix in `test_skew_first_principles.py` (drop the
regime-mismatch case, keep borrow/earnings); migration idempotency.

## M2 — #1: wire the markout + backfill to actually run

**Files**
- `src/uw_scan/worker/jobs/skew_analytics.py` — `skew_markout_refresh()` wrapper: ensure
  the backfill window is covered, then `run_skew_markout`. Idempotent.
- `src/uw_scan/worker/scheduler.py` — register weekly (e.g. Sun 19:00 ET) after the nightly
  rollup, pinned to `uw-0` via the existing `_should_schedule_*` single-flight precedent.
- Manual trigger to light it up immediately without waiting for the cron: add a `jobs`
  enqueue path (mirror existing `/jobs` kinds) **or** a `scripts/` one-off. Decide in M2.

**Tests** — scheduler registration single-flight; job wrapper integration (seeded snapshots
→ verdicts written).

## M3 — #2: snapshot fast-path + O(n) series + read-only GET

- `reports/skew_analytics.py` — split assemble into (a) read-latest-snapshot scalars/lean,
  (b) compute history/rho series in **O(n)** (rolling, not per-point DataFrame rebuild),
  (c) live-compute + persist only on miss/stale. Persist moves to the nightly job; the GET
  becomes read-only (honors `api/CLAUDE.md`).
- Staleness threshold: snapshot older than the latest RR date → live recompute.

**Tests** — fast-path returns persisted snapshot without recompute; miss/stale triggers
compute; series equality vs the old O(n²) path on a seeded series.

## M4 — #3: borrow honesty

- `cards/skew_first_principles.py` — cap lean `confidence` (no `high` when the verdict's
  borrow-clean subset is judged on current borrow) and state the limitation in `basis`.
- `worker/jobs/skew_analytics.py` backfill docstring + design note: PIT borrow history is
  unavailable (spec §11), so the borrow-clean subset is a current-borrow approximation.
- `docs/research/skew-first-principles-markout-2026-06.md` — record the limitation.

## M5 — run, verify, document, review, PR

- Run backfill + markout locally (seeded), confirm verdicts populate + a non-NEUTRAL lean
  appears when a bucket earns TRADABLE_*. Then on the mini.
- Refresh the research note with the re-run verdicts (mostly NONE is the expected, correct
  outcome — skew is a weak directional signal by design).
- `gen:types`, OpenAPI snapshot, `uv run pytest` (skew surface), `npm run typecheck`.
- `/review-cycle` then PR.

## Standing-rule checklist
- uv only · persist analytics to PG · no naked shorts (debit spreads only) · no Yahoo ·
  migrations idempotent · no `Co-Authored-By` trailers · PR before merge.
