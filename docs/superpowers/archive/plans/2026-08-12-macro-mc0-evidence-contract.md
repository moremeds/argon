# Macro MC0 Evidence Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **Execution status (2026-08-12):** implementation verified on
> `feat/macro-evidence-contract`; repository history records merge status. Live source adapters and
> production cutover remain outside MC0.

**Goal:** create the immutable, free-first, point-in-time evidence substrate that every macro domain
uses, while preserving the existing rates and gold read paths during migration.

**Architecture:** add an append-only artifact/observation store and typed evidence reference contract
in a new macro domain. Existing rates/gold tables remain legacy read models; a measured dual-read
inventory precedes any adapter or cutover. Mock/static/demo values are rejected at the persistence
boundary and may exist only in test fixtures with explicit provenance.

**Tech Stack:** PostgreSQL/psycopg, Pydantic v2, Python 3.13 via `uv`, existing repository mixin and
dataset-registry conventions.

---

## Preconditions and PR boundary

- Start from current `origin/main` in a new `.worktrees/<slug>` worktree; do not reuse
  `feat/fundamental-tier1-ingest`.
- Recheck the next migration number. This plan reserves `115_macro_evidence.sql` based on the current
  branch; rename before coding if another migration has landed.
- This PR adds schema, persistence, contracts, registry entries, and a legacy inventory only. It does
  not add live source jobs, domain scores, UI, or PM integration.
- No commit step is authorized merely by this document. Run the checkpoint only if the user has
  explicitly authorized commits for the execution task.

### Task 1: Freeze the evidence and time design

**Files:**
- Create: `docs/superpowers/archive/specs/2026-08-12-macro-evidence-contract-design.md`
- Modify: `docs/superpowers/archive/plans/2026-08-12-top-down-macro-context-program.md`

**Steps:**

1. Define `published_at`, `available_at`, `first_observed_at`, artifact `retrieved_at`/`last_seen_at`,
   and `period_end` with
   examples for a revised CPI release, a daily market series, a weekly CFTC release, and an SEP
   table.
2. Freeze the artifact and observation identities:

```text
artifact unique: (source, source_record_id, content_hash)
observation unique: (source, series_id, period_end, available_at, content_hash)
```

3. Define allowed `quality_status` values (`valid`, `invalid`, `partial`, `quarantined`) and
   `cost_class` values (`free_official`, `free_publisher`, `already_entitled`,
   `free_third_party_shadow`, `paid_authorized`).
4. State that `source_kind in {mock, static, demo}` is rejected outside `option_wizard_test`.
5. Record dual-read rules: legacy tables remain authoritative until an adapter proves row/value/time
   parity and the read flag is explicitly flipped.
6. Update MC0 status from `planned` to `specified`; do not mark it verified.

**Verification:**

Run `rg -n "available_at|free_official|mock|dual-read" docs/superpowers/archive/specs/2026-08-12-macro-evidence-contract-design.md`.
Expected: each invariant is present and defined once.

### Task 2: Add failing migration and repository tests

**Files:**
- Create: `tests/integration/storage/test_macro_context_repository.py`
- Create: `tests/unit/models/test_macro_models.py`

**Steps:**

1. Add an integration test that inserts one artifact and observation twice and expects one logical
   row with `last_seen_at` advanced.
2. Add a restatement test: same source/series/period with a new `available_at` and content hash must
   create a second observation; an `as_of` query before the revision returns the predecessor.
3. Add a source-disagreement test: official and third-party observations coexist and official
   precedence is selected without deleting dissent.
4. Add a rejection test for `source_kind="mock"` outside the test-only escape hatch.
5. Add Pydantic tests for timezone-aware timestamps, numeric units, allowed cost classes, and an
   evidence reference that round-trips without losing IDs.
6. Run:

```bash
uv run pytest tests/integration/storage/test_macro_context_repository.py tests/unit/models/test_macro_models.py -q
```

Expected: FAIL because the migration, models, and repository domain do not exist.

### Task 3: Add the immutable macro evidence schema

**Files:**
- Create: `src/uw_scan/storage/migrations/115_macro_evidence.sql`

**Required tables:**

```text
macro_source_artifacts
  artifact_id BIGSERIAL PRIMARY KEY
  source, source_kind, source_record_id, source_url (domain-neutral payload identity)
  published_at, available_at, retrieved_at, last_seen_at
  content_hash, parser_version, quality_status, cost_class
  media_type, content_length
  raw_jsonb, raw_text, raw_bytes (exactly one non-null for a successful fetch)
  UNIQUE (source, source_record_id, content_hash)

macro_observations
  obs_id BIGSERIAL PRIMARY KEY
  artifact_id FK -> macro_source_artifacts
  domain, series_id, period_end, frequency, unit
  value_numeric, value_text, value_jsonb (exactly one non-null)
  source, source_record_id, published_at, available_at
  first_observed_at, last_seen_at, content_hash, parser_version
  quality_status, cost_class
  UNIQUE (source, series_id, period_end, available_at, content_hash)
```

**Steps:**

1. Add checks for allowed observation-domain/source-kind/quality/cost values, one-of-three observation value
   columns, and one-of-three artifact payload columns. `raw_bytes` is required for PDF/XLSX payloads
   whose exact bytes cannot be reconstructed from parsed JSON/text.
2. Recompute artifact hash/length and normalized observation hash in both Python and PostgreSQL.
3. Add database guards that allow only monotonic sighting metadata, enforce artifact availability and
   quality bounds, and reject evidence updates/deletes.
4. Add PIT indexes on `(series_id, period_end, available_at DESC)` and artifact lookup indexes.
5. Make the migration idempotent; do not alter/drop legacy rates or gold tables.
6. Run migrations twice against the test database through the normal integration fixture.

### Task 4: Implement the repository and typed contracts

**Files:**
- Create: `src/uw_scan/storage/macro_context.py`
- Modify: `src/uw_scan/storage/repository.py`
- Create: `src/uw_scan/models/macro.py`
- Modify: `src/uw_scan/models/__init__.py`

**Required repository surface:**

```python
insert_macro_artifact(...)->int
insert_macro_observations(...)->int
fetch_macro_observation_as_of(series_id, period_end, as_of, preferred_sources)->dict|None
fetch_macro_series_as_of(series_id, as_of, from_date=None, preferred_sources)->list[dict]
fetch_macro_observation_history(series_id, period_end)->list[dict]
```

**Steps:**

1. Use explicit argument lists and `Jsonb`; do not add methods directly to the aggregate repository.
2. `insert_macro_observations` may update only sighting metadata for the identical immutable identity.
3. PIT queries require timezone-aware `as_of`, explicit non-empty source precedence, artifact and
   observation `available_at <= as_of`, and exclude invalid/quarantined evidence by default.
4. Implement `MacroEvidenceRef`, `MacroObservation`, `MacroSourceArtifact`, and literal enums in
   `models/macro.py`; preserve public model identity through existing export helpers.
5. Run the tests from Task 2. Expected: PASS.

### Task 5: Register the temporal datasets and policy documentation

**Files:**
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Modify: `docs/runbooks/data-gap-dataset-policy.md`
- Test: `tests/integration/worker/test_data_gap_full_coverage.py`
- Test: `tests/unit/reports/test_data_gap_dataset_policy.py`

**Steps:**

1. Register `macro_source_artifacts` and `macro_observations` as provenance/event-temporal datasets;
   do not classify them as strict daily ticker coverage.
2. Regenerate the policy document using the repository's existing renderer.
3. Run:

```bash
uv run pytest tests/integration/worker/test_data_gap_full_coverage.py tests/unit/reports/test_data_gap_dataset_policy.py -q
```

Expected: PASS and the committed policy document matches the registry.

### Task 6: Persist the legacy inventory and dual-read acceptance baseline

**Files:**
- Create: `scripts/research/macro_legacy_inventory.py`
- Create: `docs/research/2026-08-12-macro-legacy-inventory/README.md`
- Create: `docs/research/2026-08-12-macro-legacy-inventory/inventory.json`
- Create: `docs/research/2026-08-12-macro-legacy-inventory/VERDICT.md`

**Steps:**

1. Inventory every existing rates/gold series/table, date span, revision key, source, timestamp
   semantics, and downstream consumer.
2. Flag overwriting identities, missing provenance, mixed/mock source status, and sources with no
   official fallback.
3. Persist the exact reproduce command and add `--self-check` for deterministic JSON ordering and
   required table coverage.
4. Do not write production rows or call paid providers.
5. Run the self-check and record the output in `VERDICT.md`.

### Task 7: Final verification and conditional checkpoint

Run:

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh
uv run pytest tests/integration/storage/test_macro_context_repository.py tests/unit/models/test_macro_models.py tests/integration/worker/test_data_gap_full_coverage.py tests/unit/reports/test_data_gap_dataset_policy.py -q
uv run python scripts/research/macro_legacy_inventory.py --self-check
git diff --check
git status --short
```

Expected: migrations are idempotent, tests/self-check pass, and only MC0 files plus the required
policy regeneration are changed.

If and only if commits were explicitly authorized:

```bash
git add docs/superpowers/archive/specs/2026-08-12-macro-evidence-contract-design.md docs/superpowers/archive/plans/2026-08-12-top-down-macro-context-program.md src/uw_scan/storage/migrations/115_macro_evidence.sql src/uw_scan/storage/macro_context.py src/uw_scan/storage/repository.py src/uw_scan/models/macro.py src/uw_scan/models/__init__.py src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md tests/integration/storage/test_macro_context_repository.py tests/unit/models/test_macro_models.py scripts/research/macro_legacy_inventory.py docs/research/2026-08-12-macro-legacy-inventory
git commit -m "feat(macro): add immutable evidence contract"
```

## MC0 exit criteria

- revisions survive and replay PIT;
- identical refresh is idempotent;
- source disagreement survives canonical selection;
- mock/static/demo cannot enter production evidence;
- cost/source/time semantics are typed;
- legacy history remains untouched;
- registry/policy gates pass;
- the persisted inventory identifies every adapter required by MC1–MC3.

## Execution record

- Worktree: `.worktrees/macro-evidence-contract`
- Development DB boundary: `option_wizard_local` read-only inventory only
- Automated DB boundary: `option_wizard_test`
- Migration replay: two consecutive full migration passes succeeded
- Tests: 1,715 unit tests and 927 integration tests passed (11 integration skips), including
  recomputed content identity, Python/PostgreSQL JSON parity, direct-SQL immutability and finite
  numeric rejection, revisions, PIT source precedence, conservative availability, artifact quality
  bounds, registry/policy, legacy rates/gold regressions, and public model exports
- Inventory: 19 relations covered; deterministic inside a repeatable-read transaction; zero provider
  calls
- Static gates: Ruff check/format and `git diff --check` passed
- Checkpoint: feature PR required; no direct push or deployment is authorized
