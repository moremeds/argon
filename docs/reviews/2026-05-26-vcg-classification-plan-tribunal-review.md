# VCG Classification Plan — Tribunal Review (Pass 1–3 Consolidated)

**Date**: 2026-05-26
**Target**: `docs/superpowers/plans/2026-05-26-vcg-regime-classification-accuracy.md` v0.2 (3,043 lines)
**Spec**: `docs/superpowers/specs/2026-05-26-vcg-regime-classification-design.md` v0.2
**Reviewers**:
- **Codex** (gpt-5.3-codex via codex-cli 0.133.0) — weight 1.0 — bug detection focus — 12 findings
- **Claude** (codebase-aware, full repo access) — weight 1.0 — integration correctness focus — Pass 1 (8 findings) + Pass 3 adversarial (6 findings)
- **Gemini** (gemini-cli 0.41.2) — weight 0.5 — FAILED (trusted-directory check, exit 55) — bilateral mode invoked per skill failure-handling table

**Mode**: Bilateral (Codex + Claude, 2-way)
**Verdict**: **FIX-FIRST** — 8 critical and 10 important findings must be resolved before implementation begins

---

## Consensus findings (Codex + Claude agree)

### CR-1 [CRITICAL] Replay determinism claim is structurally unachievable
**Flagged by**: Codex ISSUE-3 (conf 98) + Claude Pass 1.C
**Category**: bug — spec violation
**Description**:
First render passes `cm_by_period`, `named_crisis_overlay`, real `vcg_source`. `render_replay` passes `cm_by_period={}`, `named_crisis_overlay=[]`, and synthetic `vcg_source` reconstructed from `params`. Plan Task 10.4 hedges by diff'ing only headline sections — but spec §12 says "replay yields byte-identical report bytes". The two are contradictory.

**Resolution options**:
1. Persist the rendered report markdown itself in `summary.extras.classification.report_md`. Replay reads and returns the stored bytes. True byte-identical.
2. Persist `cm_by_period` as JSON in `summary.extras` AND persist named-crisis-overlay results. Replay reconstructs.
3. Narrow the spec claim from "byte-identical replay" to "verdict-block byte-identical".

**Recommendation**: Option 1 (persist report bytes). Simplest. Acceptance test becomes trivial.

---

### CR-2 [CRITICAL] Concurrent script invocations race on idempotent reuse
**Flagged by**: Codex ISSUE-8 (conf 86) + Claude Pass 3.G
**Category**: bug — concurrency
**Description**:
`find_completed_classification_run` + `insert_classification_run` is a check-then-insert race. Two scripts running simultaneously both see "no run exists" and both insert.

**Resolution**: Add migration 062 with a partial unique index:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS regime_classification_completed_uniq
  ON uw_scan.regime_backtest_runs (
    indicator, composite_method, run_scope,
    ((params->>'vcg_source_run_id')::int),
    ((params->>'label_version')::int)
  )
  WHERE composite_method = 'classification_accuracy'
    AND completed_at IS NOT NULL
    AND archived_at IS NULL;
```
Then catch the `UniqueViolation` in `insert_classification_run` and re-query.

---

## Codex-only findings (Codex 1.0, Claude did not catch)

### CO-1 [CRITICAL] `macro_series_daily` query will fail on multi-vintage data
**Flagged by**: Codex ISSUE-1 (conf 96)
**Category**: bug
**Description**:
`macro_series_daily` is keyed by `(series_id, obs_date, as_of)` — multi-vintage. Plan's `load_input_series` selects `(obs_date, series_id, value)` directly. When NFCI has multiple `as_of` rows per `obs_date` (post-revision), `pivot` raises `ValueError: Index contains duplicate entries`.

**Resolution**: Change to `SELECT DISTINCT ON (series_id, obs_date) ... ORDER BY series_id, obs_date, as_of DESC`. Add `as_of <= %s` parameter for point-in-time replay.

---

### CO-2 [CRITICAL] NaN metrics will crash JSONB insertion
**Flagged by**: Codex ISSUE-2 (conf 90)
**Category**: bug
**Description**:
`per_class_prf` returns `float('nan')` for absent classes (intentionally — patch §4 from earlier review). `persist_and_render` stores `scoring["per_class"]`, `kappa`, `weighted_f1` directly in `summary` JSONB. PostgreSQL JSONB does not accept `NaN` tokens. Real runs with absent PANIC/BOUNCE classes will fail at the `Jsonb(summary)` wrapping step, BEFORE daily rows are inserted.

**Resolution**: Add `_sanitize_for_json` recursive helper that converts `NaN`/`±inf` → `None`. Add test seeding absent PANIC class + verifying successful persistence.

---

### CO-3 [IMPORTANT] Percentile tie semantics map flat series to maximally-suppressed
**Flagged by**: Codex ISSUE-4 (conf 88)
**Category**: bug — semantics
**Description**:
`compute_rolling_percentile_rank` uses `(cohort < today).sum() / len(cohort)`. For constant cohort = today, count = 0 → percentile 0.0. Classifies flat-but-normal periods as SUPPRESSED.

**Resolution**: Decide tie semantics in YAML (`percentile_tie_rule: 'strict_lt' | 'average_rank' | 'le'`). Add unit test for constant cohort.

---

### CO-4 [IMPORTANT] NORMAL silently absorbs unclassified fall-through
**Flagged by**: Codex ISSUE-6 (conf 84)
**Category**: bug — semantics
**Description**:
Spec §6.4: NORMAL = "all percentiles in [25,75] AND drawdown < 5%". Plan's `classify_level1_instantaneous` returns `NORMAL` for ALL fall-through cases — including states outside the NORMAL band that don't trigger any stress threshold (e.g., vix_pct=0.20 but rv/credit/vvix in [0.30, 0.75]).

**Resolution options**:
1. Add `UNCLASSIFIED` state to taxonomy, scored separately (changes spec).
2. Cover the gap by extending NORMAL or SUPPRESSED bands to be exhaustive.
3. Document the fall-through behavior explicitly in YAML + spec.

**Recommendation**: Option 2 with explicit NORMAL band widening to `[0.20, 0.80]` and SUPPRESSED requiring strict-below. Keeps 6-class taxonomy.

---

### CO-5 [IMPORTANT] Migration 061 hardcoded composite_method list can regress other branches
**Flagged by**: Codex ISSUE-7 (conf 87)
**Category**: bug — migration safety
**Description**:
Migration 061 drops any constraint matching `'%composite_method%'` and re-adds a fixed allow-list. If another open branch added a composite_method value (e.g., `risk_parity_4`) and merged first, migration 061 silently removes it.

**Resolution**: In the migration's DO block, query `SELECT DISTINCT composite_method FROM regime_backtest_runs` BEFORE dropping. Verify the new allow-list is a superset of observed values. If not, raise.

---

### CO-6 [IMPORTANT] E2E synthetic seed violates `macro_series_daily` schema
**Flagged by**: Codex ISSUE-9 (conf 97)
**Category**: testing
**Description**:
Phase 9 E2E inserts into `macro_series_daily (obs_date, series_id, value)`. Real table requires `as_of` and `source` NOT NULL. Test fails at seed, never reaches scoring path.

**Resolution**: Seed `as_of=%s, source='test'` (and optionally `release_date`). Verify via `\d uw_scan.macro_series_daily` in Task 0.3 probe; update Task 9.1 seed accordingly.

---

### CO-7 [IMPORTANT] `build_confusion_matrix` pairs by position, not by index
**Flagged by**: Codex ISSUE-10 (conf 82)
**Category**: bug — pure-function contract
**Description**:
`pd.DataFrame({"truth": truth.values, "pred": pred.values}).dropna()` pairs by position. Caller `score_against_vcg` pre-aligns by date, so it works — but the pure function's contract is unsafe. Future caller passing differently-indexed series will silently mis-align.

**Resolution**: Inside `build_confusion_matrix`, align by index: `pd.concat([truth.rename("truth"), pred.rename("pred")], axis=1).dropna()`. Add test with reversed-order pred index.

---

### CO-8 [IMPORTANT] `label_mismatch` triggers on cm.empty or zero-disagreement
**Flagged by**: Codex ISSUE-11 (conf 80)
**Category**: bug
**Description**:
Spec §9: `label_mismatch` requires top-2 off-diagonals ≥ MISMATCH_CONCENTRATION of total disagreement. Plan code appends `label_mismatch` when `cm.empty` OR when `total_disagreement == 0` — both bypass the quantitative trigger.

**Resolution**: In both edge cases, do NOT append `label_mismatch`. Return `not_evaluable` for the mode or fall through to `unknown`.

---

### CO-9 [MINOR] Rolling-window off-by-one against "prior 252 days" reading
**Flagged by**: Codex ISSUE-5 (conf 78)
**Category**: bug — semantics
**Description**:
`compute_rolling_percentile_rank` with `window=252`: today is index `-1`, cohort is `arr[:-1]` = 251 prior days. If spec meant "current day vs prior 252 days", off-by-one. If spec meant "252-day window total", correct.

**Resolution**: Add YAML comment clarifying semantics. Current implementation = "window of 252 days inclusive of current; cohort is the 251 prior days". Standard finance convention.

---

### CO-10 [MINOR] `eval_end` from YAML is ignored when not `auto`
**Flagged by**: Codex ISSUE-12 (conf 76)
**Category**: bug
**Description**:
YAML supports `eval_end`. Script uses `scoring["aligned"].index.max()`. For `auto` this is fine. For fixed `eval_end` (replay cutoff), the YAML value is silently ignored.

**Resolution**: In `score_against_vcg`, parse `eval_end`; if not `auto`, filter `aligned.index <= eval_end_ts`.

---

## Claude-only findings (Claude 1.0, Codex did not catch)

### CL-1 [CRITICAL] `per_universe_macro_f1=None` is hardcoded — `benchmark_coverage` failure mode structurally unreachable
**Flagged by**: Claude Pass 1.A
**Category**: bug — spec violation
**Description**:
`main()` always passes `per_universe_macro_f1=None` to `classify_failure_mode`. Result: `benchmark_coverage` is permanently `not_evaluable`, regardless of whether NDX/RUT data is present. Spec §9 lists it as a real failure mode, not deferred placeholder.

**Resolution options**:
1. Implement per-universe scoring (significant new code: re-run truth-derivation against NDX/RUT after Phase A2 lands).
2. Document this gap explicitly: "benchmark_coverage requires per-universe scoring; deferred to follow-up PR after Phase A2 merges."

**Recommendation**: Option 2 for v1 (call out as known gap with explicit deferral); Option 1 in a follow-up PR.

---

### CL-2 [CRITICAL] INCONCLUSIVE verdict → `primary = "unknown"` (spec §9 violation)
**Flagged by**: Claude Pass 1.B
**Category**: bug — spec violation
**Description**:
Spec §9: failure mode emitted for "both FAIL and INCONCLUSIVE verdicts." Plan's `classify_failure_mode` precedence chain: panic_suppression / signal_sparsity / label_mismatch / benchmark_coverage / adequate_v1. The first four can only trigger under FAIL conditions; `adequate_v1` only under PASS. INCONCLUSIVE → none trigger → `primary = "unknown"`.

**Resolution**: Add `underpowered_test` mode with explicit trigger: `verdict.overall == "INCONCLUSIVE"`. Insert into precedence chain between `signal_sparsity` and `label_mismatch`. Cover the spec gap.

---

### CL-3 [CRITICAL] NFCI vintage not captured — replay drifts as FRED revises
**Flagged by**: Claude Pass 3.I
**Category**: bug — spec violation (§6.2)
**Description**:
Spec §6.2: "vintage pinned to latest-available-as-of-`run_at_date`". Plan's `load_input_series` queries FRED via `macro_series_daily` at run time. FRED revises NFCI after release. Replay 3 months later gets different values for the same dates → different labels → different report. Breaks the spec's replay-determinism claim independently of CR-1.

**Resolution**: Snapshot the raw NFCI value (and ANFCI sensitivity) per day in `label_components.NFCI_value`. Update spec §6.2 to require this. Combined with CO-1 (DISTINCT ON for vintage), replay reads from snapshot rather than re-querying FRED.

---

### CL-4 [IMPORTANT] Duplicate `trade_date` in `load_vcg_daily` silently masked
**Flagged by**: Claude Pass 1.D
**Category**: bug — defensive
**Description**:
`df.set_index("trade_date")["level"]` silently keeps one of duplicate rows. If `regime_backtest_daily` somehow has duplicates for a VCG run, classification scores half the data.

**Resolution**: `df.set_index("trade_date", verify_integrity=True)` raises on duplicates. One-line fix.

---

### CL-5 [IMPORTANT] E2E uses `repo.conn.info.dsn` — psycopg 3 sanitizes passwords
**Flagged by**: Claude Pass 1.E
**Category**: testing
**Description**:
`monkeypatch.setenv("UW_SCAN_DB_URL", repo.conn.info.dsn)` — `Connection.info.dsn` in psycopg 3 returns DSN with password masked as `xxxxx`. Script's `connect(db_url)` will fail authentication.

**Resolution**: Construct DSN explicitly from fixture parameters, or use a `conn.info`-derived URL helper that preserves credentials. Standard pytest-postgresql fixtures expose `postgresql_dsn` or similar.

---

### CL-6 [IMPORTANT] Post-hoc disclosure for NFCI release-lag not implemented
**Flagged by**: Claude Pass 1.F
**Category**: spec compliance
**Description**:
Spec §6.1 rule 4: "Any label that uses lagged data is marked as post-hoc in the report." NFCI has 3-5 day release lag. Report renderer doesn't surface this.

**Resolution**: Add a `Methodology > Data vintages` section to report listing each component with its lag characteristic. Format: `| NFCI | post-hoc | 3-5 day release lag | non-tradable signal |`.

---

### CL-7 [IMPORTANT] Empty `vol_index_daily.SPX` causes downstream AttributeError
**Flagged by**: Claude Pass 3.H
**Category**: bug — defensive
**Description**:
`pivot.get("SPX")` returns `None` if SPX absent. `compute_trailing_drawdown(None)` then errors with confusing message.

**Resolution**: After `load_input_series`, assert non-None for VIX/VVIX/SPX/NFCI with explicit error message naming the missing series.

---

### CL-8 [IMPORTANT] `insert_run` / `bulk_insert` / `mark_completed` are 3 separate transactions
**Flagged by**: Claude Pass 3.K
**Category**: bug — atomicity
**Description**:
Failure mid-bulk leaves a run row + partial daily rows but `completed_at IS NULL`. `find_completed_classification_run`'s `WHERE completed_at IS NOT NULL` filter handles idempotency correctly, but orphans pollute the table. Migration 060's `archived_at` is the soft-clean escape, but no Phase task uses it.

**Resolution**: Either (a) wrap the 3 calls in a single `with conn.transaction():` block, OR (b) add a cleanup task in Phase 10 that archives orphan rows older than N hours.

---

### CL-9 [MINOR] `_normalize_date_index` defined but partially duplicated inline
**Flagged by**: Claude Pass 1.G
**Category**: style
**Description**:
`_normalize_date_index` is called in `load_input_series` but `load_vcg_daily` does the same operation inline. Minor DRY.

**Resolution**: Call `_normalize_date_index` consistently or inline both for symmetry.

---

### CL-10 [MINOR] `instant_label or None` may misbehave under pd.NA
**Flagged by**: Claude Pass 1.H
**Category**: bug — defensive
**Description**:
`components_row.get("instant_label") or None`. `pd.NA or None` returns `None` in current pandas but raises `TypeError: boolean value of NA is ambiguous` in some contexts. Version-fragile.

**Resolution**: Use `(v if not pd.isna(v) else None)` explicitly.

---

### CL-11 [MINOR] `normalize_vcg_label` error message lacks remediation hint
**Flagged by**: Claude Pass 3.L
**Category**: usability
**Description**:
On unknown VCG label, raises `ValueError(f"unknown VCG label: {raw!r}")`. Doesn't tell future maintainer where to add the new label.

**Resolution**: Append: `"; if VCG emits new labels, extend _VCG_LABEL_ALIASES in src/uw_scan/cards/regime_classification_scoring.py"`.

---

### CL-12 [MINOR] Migration 061 transaction semantics unverified
**Flagged by**: Claude Pass 3.J
**Category**: migration safety
**Description**:
DROP CONSTRAINT then ADD CONSTRAINT inside `DO $$ ... LOOP`. If `scripts/migrate.sh` doesn't wrap each `.sql` file in BEGIN/COMMIT, a concurrent INSERT between DROP and ADD could write a row bypassing the (briefly absent) constraint.

**Resolution**: Wrap the migration explicitly in `BEGIN; ... COMMIT;`. Verify migrate.sh transaction semantics.

---

## Confidence-filtered (no items dropped — all ≥76 confidence)

All Codex findings carried confidence ≥76; all Claude findings reflected my own confident assessment. No auto-dismissal applied.

## Refuted in debate (N/A — bilateral mode without rebuttal)

The skill's debate-and-rebuttal protocol assumes ≥3 reviewers. In bilateral mode, no contested-issue debate was run. All Codex-only and Claude-only findings were individually evaluated and accepted based on codebase analysis.

---

## Verdict matrix

| Severity | Count | Action |
|---|---:|---|
| **CRITICAL** | 7 | Apply before any code execution. Spec §9, §12, §6.2 violations + production-crash bugs. |
| **IMPORTANT** | 11 | Apply before merge. Bugs that work in happy-path but break on real data. |
| **MINOR** | 6 | Apply opportunistically. Documentation + DRY + error messages. |

**Recommended verdict**: **FIX-FIRST** — plan v0.2 cannot execute without addressing at least CR-1, CR-2, CO-1, CO-2, CO-6, CL-1, CL-2, CL-3.

## Stats

- Total unique issues raised: 24
- Codex-only: 12 (10 surfaced new findings I missed)
- Claude-only: 12 (all surfaced via Pass 1 and Pass 3)
- Consensus (Codex + Claude): 2 (CR-1, CR-2)
- Refuted: 0
- Auto-dismissed: 0
- Mode: Bilateral (Gemini unavailable due to trusted-directory check)

---

## Assumptions still unverified (Pass 6 gate)

| Assumption | Evidence | Status |
|---|---|---|
| `archived_at` migration 060 is merged to main | NOT verified | ⬜ Phase 0 Task 0.1 catches at runtime |
| `regime_backtest_daily.payload` is JSONB | VERIFIED via grep at plan-write time | ✅ |
| `uw_scan.macro_series_daily` schema | NOT verified at plan-write; Codex CO-1 + CO-6 imply it has `as_of` + `source` columns | ⬜ Phase 0 Task 0.3 probe required |
| NFCI / USREC integrated via `sources/fred.py` | NOT verified | ⬜ Phase 0 Task 0.3 probe required |
| `composite_method` CHECK constraint existence | NOT verified | ⬜ Phase 0 Task 0.4 probe — gates Migration 061 |
| `scripts/migrate.sh` wraps migrations in transactions | NOT verified | ⬜ Required for CL-12 safety |
| `seeded_db_empty_cards` fixture provides `regime_backtest_runs` table | Inferred from existing test usage | ⚠️ Probable but not directly verified |
| `pytest-postgresql` fixture exposes a DSN with credentials | NOT verified | ⬜ CL-5 dependency |

**Per /review-cycle Pass 6 rule**: never declare done with unverified assumptions. The above are explicitly disclosed. Implementation execution should make Phase 0 probes (Tasks 0.1–0.4) mandatory gates.

---

## Next steps for the user

The skill's Pass 4 says "apply all fixes". I have NOT auto-applied because:
1. The plan is large (3,043 lines); 24 fixes across many sections is a substantial v0.3 rewrite.
2. Some findings have multiple resolution options (CR-1, CO-4, CL-1) requiring user judgment.
3. Your iterative pattern (round 1, round 2, this tribunal = round 3) implies you want to weigh in.

**Decide**:
1. Apply ALL 24 fixes → plan v0.3 rewrite (~3,500 lines).
2. Apply only CRITICAL (8) → plan v0.3a with KNOWN-GAPS section listing the 16 IMPORTANT/MINOR.
3. Apply specific subset by ID (e.g., "apply CR-1, CR-2, CO-1, CO-2, CL-1, CL-2, CL-3").
4. Accept the review findings as-is, treat them as known-gaps in plan v0.2, proceed to implementation with eyes open.

**Hard guardrail (from /review-cycle)**: Never commit, push, or open PR from inside this skill. Hand off to `/ship` or explicit user instruction.
