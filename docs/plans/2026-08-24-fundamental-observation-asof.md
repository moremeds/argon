# Fundamental Observation As-Of Implementation Plan

> **STATUS 2026-08-24: implemented, awaiting review.** Tasks 0–10 executed on
> `feat/fundamental-pm-research-system`. Full suite `4031 passed, 14 skipped`;
> ruff/no-Yahoo/diff clean; migrations idempotent on a fresh DB. Six recorded
> deviations and one deliberately-unmet gate (the production coverage audit, which
> needs authorization) are documented in §14 of
> `docs/handover/2026-08-24-fundamental-pm-research-system-claude-handover.md`.
> Not committed, pushed, or deployed.

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan
> task-by-task. Use `superpowers:test-driven-development` for every behavior change and
> `superpowers:verification-before-completion` before any completion claim.

**Goal:** add honest version-level availability evidence and separate current versus fail-closed
as-of statement readers, then route historical fundamental scoring through an explicit evidence
policy without changing current-page behavior or rewriting old results.

**Architecture:** preserve `fundamental_statement_obs` as the immutable content-version table. Add an
append-only child table of availability evidence claims because one observation may first be only
capture-bounded and later gain SEC amendment/publication proof. Keep the current reader's newest-row
semantics under an explicit name. Add a separate as-of reader that chooses the strongest eligible
claim under a required policy and returns the evidence metadata used. Historical scoring opts into
that reader and binds the evidence policy to result identity.

**Tech stack:** PostgreSQL/psycopg 3, Python 3.13 via `uv`, pytest/pytest-postgresql, existing
fundamental storage and APScheduler worker conventions.

**Program context:** this is Pre-Job 0 of
`docs/superpowers/plans/2026-08-24-fundamental-pm-research-system-program.md`. It enables corrected
research; it does not itself validate or rerun any historical signal.

**Authorization boundary:** do not commit, push, open a PR, alter the primary checkout, or touch
production without a new explicit user instruction. Suggested commit messages below are future
checkpoints only; stop before each commit unless authorization exists.

---

## Contract fixed by this plan

### Observation and claim model

`fundamental_statement_obs` remains one row per normalized content version. Add a suggested next
migration (verify the number immediately before implementation):

`src/uw_scan/storage/migrations/132_fundamental_obs_availability.sql`

The new `fundamental_obs_availability` table contains at least:

```text
availability_id       BIGSERIAL primary key
obs_id                BIGINT not null FK fundamental_statement_obs(obs_id)
claim_key             TEXT not null
evidence_class        TEXT not null
available_at          TIMESTAMPTZ null
evidence_source       TEXT not null
evidence_ref          TEXT null
evidence_jsonb        JSONB not null default '{}'
recorded_at           TIMESTAMPTZ not null default now()
unique(obs_id, claim_key)
```

Constraints:

- `evidence_class` is one of `true_pit`, `capture_bounded`, `current_vintage`, `unknown`;
- `available_at` is required for `true_pit` and `capture_bounded`;
- `available_at` is null for `current_vintage` and `unknown`;
- a claim is append-only; stronger later evidence inserts another claim rather than overwriting the
  earlier one;
- `claim_key` is deterministic for idempotent replay;
- indexes support `(obs_id, evidence_class, available_at)` and the as-of join path;
- `ON DELETE CASCADE` matches the source observation's existing lifecycle, although production code
  does not delete observations.

### Evidence meaning

- `true_pit`: exact content-version availability is backed by an amendment/publication artifact or
  equivalent positive version-level source evidence.
- `capture_bounded`: Argon can safely admit the content no earlier than `available_at`, normally the
  first capture of that exact content hash. This is conservative and does not reconstruct earlier
  market knowledge.
- `current_vintage`: a historical snapshot that can support today's current panel but no historical
  version-availability claim.
- `unknown`: evidence is insufficient even to select a usable timestamp.

The original period's `filing_published_at` is not sufficient by itself to call a later content hash
`true_pit`.

### Reader policies

Define a closed enum/type, with final names frozen in Task 1:

- `TRUE_PIT_ONLY`: admit only `true_pit` claims at or before cutoff;
- `CAPTURE_BOUNDED`: admit `true_pit` or `capture_bounded` at or before cutoff, prefer `true_pit` for
  audit metadata when both support the selected version;
- no historical policy admits `current_vintage` or `unknown`;
- current view is a separate reader, not a permissive historical policy.

Among eligible content versions for `(source, ticker, period_end, period_type, statement)`, select the
version with the latest eligible `available_at`; use `obs_id` only as a deterministic final tie-break,
never as availability evidence.

### Legacy-row policy

The migration/backfill must not invent true-PIT history.

1. Every existing row receives an idempotent `current_vintage` classification claim identifying the
   migration/rule version.
2. It may receive a `capture_bounded` claim at its persisted `first_observed_at`, because Argon can
   safely admit the exact content at or after that capture time.
3. No existing row receives `true_pit` solely from `filing_published_at`.
4. A later SEC/provider evidence job may add `true_pit`; that source adapter is outside this child
   project unless a bounded fixture/probe is required to validate the contract.

### Compatibility

- current stock pages and current anchor refresh continue reading the newest accepted version;
- rename the current contract to `current_statement_panel(...)`;
- retain `statement_panel(...)` as a temporary documented compatibility alias to current behavior;
- historical scoring calls `statement_panel_as_of(...)` explicitly;
- existing `fundamental_scores` and `valuation_anchors` rows are untouched;
- corrected results use a new engine/version identity and must not collide with old rows.

---

## Task 0: Re-prove the baseline and freeze the diff boundary

**Files:** none.

**Step 1: Verify repository identity and ownership boundary**

Run:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git worktree list --porcelain
```

Expected:

- branch `feat/fundamental-pm-research-system`;
- baseline `86161f1d` unless an explicitly reviewed update has occurred;
- only intended planning/handoff files are uncommitted;
- primary-checkout dirty research files remain outside this worktree.

Stop on any unexpected code modification.

**Step 2: Refresh the moved worktree environment**

Run:

```bash
uv sync --extra postgres
```

This is required because the worktree path changed after the original environment was created.

**Step 3: Run the targeted baseline**

Run the exact suite recorded in the handoff. At minimum:

```bash
uv run pytest \
  tests/unit/fundamentals \
  tests/unit/worker/test_fundamental_ingest_filing_dates.py \
  tests/unit/worker/test_fundamental_ingest_daily.py \
  tests/unit/worker/test_fundamental_scoring_cutoff.py \
  tests/unit/worker/test_fundamental_concentration_capture.py \
  tests/integration/storage/test_fundamental_obs.py \
  tests/integration/storage/test_fundamental_scores.py \
  tests/integration/api/test_fundamentals_endpoint.py \
  tests/integration/api/test_fundamental_statements_endpoint.py
```

Expected baseline: the previously recorded run was `209 passed`. Record the new exact count and any
environment drift. Do not reinterpret a baseline failure as part of this feature.

---

## Task 1: Freeze availability policy in pure code

**Files:**

- Create: `src/uw_scan/fundamentals/observation_time.py`
- Create: `tests/unit/fundamentals/test_observation_time.py`
- Modify: `src/uw_scan/fundamentals/__init__.py` only if a public export is needed

**Step 1: Write failing policy tests**

Cover:

1. accepted evidence classes are closed;
2. `true_pit` and `capture_bounded` require timezone-aware `available_at`;
3. current-vintage/unknown reject an availability timestamp in normalized application input;
4. `TRUE_PIT_ONLY` rejects every non-true-PIT class;
5. `CAPTURE_BOUNDED` admits true-PIT and capture-bounded only;
6. same-instant claims prefer true-PIT metadata;
7. naive datetimes are rejected rather than assumed local/UTC.

Run:

```bash
uv run pytest tests/unit/fundamentals/test_observation_time.py -q
```

Expected: fail because the module does not exist.

**Step 2: Implement the minimum pure types/policy**

Use `str` enums or literals and small pure validation/priority helpers. Do not put SQL, provider
logic, or scoring logic here.

**Step 3: Re-run and lint the focused files**

```bash
uv run pytest tests/unit/fundamentals/test_observation_time.py -q
uv run ruff check src/uw_scan/fundamentals/observation_time.py \
  tests/unit/fundamentals/test_observation_time.py
```

Expected: pass.

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): define observation availability policy`. Do not commit without explicit user
authorization.

---

## Task 2: Add the append-only availability schema

**Files:**

- Create: `src/uw_scan/storage/migrations/132_fundamental_obs_availability.sql`
- Modify: `src/uw_scan/storage/migrations/README.md`
- Modify: `tests/integration/storage/test_fundamental_obs.py`
- Modify: `tests/integration/storage/test_migrations.py` only if the suite has a targeted convention

**Step 1: Confirm the migration number is still free**

```bash
ls src/uw_scan/storage/migrations | tail -n 20
```

If another branch has taken `130`, select the next valid number and update this plan/handoff before
continuing. Do not create a silent collision.

**Step 2: Write failing migration/constraint tests**

Use the real migrated test schema to prove:

- the table and indexes exist;
- all four classes obey timestamp constraints;
- `obs_id` must reference a real observation;
- duplicate `(obs_id, claim_key)` is rejected or handled idempotently by repository code;
- the migration can execute twice without error.

Run the focused test and confirm failure because the table is absent.

**Step 3: Implement the additive migration**

Use `CREATE TABLE IF NOT EXISTS`, named constraints, `CREATE INDEX IF NOT EXISTS`, and comments that
state why original filing date is not version availability.

Do not rewrite migration 114. Do not update existing rows in a one-shot untracked migration block;
legacy claim seeding is an explicit resumable repository/job step in Task 5.

**Step 4: Run migration tests twice**

```bash
uv run pytest tests/integration/storage/test_fundamental_obs.py -q
uv run pytest tests/integration/storage/test_migrations.py -q
```

Also run the repository's migration command twice against an isolated allowed database tier if that
is part of the existing test procedure. Record both results.

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): add observation availability evidence schema`.

---

## Task 3: Implement availability claim persistence

**Files:**

- Create: `src/uw_scan/storage/fundamental_observation_availability.py`
- Create: `tests/integration/storage/test_fundamental_observation_availability.py`
- Modify: `src/uw_scan/storage/fundamental_obs.py` only for the minimal ingest integration/identity
  handoff

**Step 1: Write failing repository tests**

Cover:

1. inserting a capture-bounded claim and reading it back;
2. replaying the same deterministic claim writes nothing new;
3. a later true-PIT claim coexists with the capture claim;
4. attempts to mutate an existing claim's class/time/evidence fail or no-op visibly;
5. batch claim recording is set-based and does not query once per observation;
6. transaction failure does not leave a partially advertised successful backfill;
7. arbitrary schema names work in test isolation.

Confirm failure before creating the repository.

**Step 2: Implement a standalone domain repository**

Do not add methods to aggregate `storage/repository.py`. Keep SQL parameterized and schema handling
consistent with `FundamentalObsRepository`. Writers commit according to the established standalone
fundamental repository convention.

Required methods should be narrow; suggested responsibilities:

- `record_claims(...)`;
- `claims_for_obs_ids(...)`;
- `ensure_capture_claims_for_observations(...)` using a set-based insert/select;
- `claim_counts(...)` for verification/operations.

Do not add source-specific SEC parsing here.

**Step 3: Re-run tests and inspect query behavior**

```bash
uv run pytest tests/integration/storage/test_fundamental_observation_availability.py -q
uv run ruff check src/uw_scan/storage/fundamental_observation_availability.py \
  tests/integration/storage/test_fundamental_observation_availability.py
```

Use test instrumentation or SQL inspection to confirm the batch path is not N+1.

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): persist version availability evidence`.

---

## Task 4: Split current and as-of readers

**Files:**

- Create: `src/uw_scan/storage/fundamental_observation_panels.py`
- Create: `tests/integration/storage/test_fundamental_observation_panels.py`
- Modify: `src/uw_scan/storage/fundamental_obs.py`
- Modify current reader callers only as required for explicit naming

**Step 1: Write the decisive failing integration fixtures**

Insert real rows/claims for one identity:

- original content, true-PIT available in 2020;
- restated content, true-PIT available in 2023;
- changed content with only capture-bounded availability in 2024;
- changed historical snapshot with current-vintage only;
- an optional unknown claim.

Assert:

1. current reader returns the newest accepted observation;
2. true-PIT as-of 2021 returns the original;
3. true-PIT as-of 2024 returns the 2023 restatement, not capture/current-vintage rows;
4. capture-bounded as-of before the capture excludes it;
5. capture-bounded as-of after the capture selects it;
6. current-vintage/unknown never enter either historical mode;
7. same-period source and statement partitions do not bleed into each other;
8. selection metadata names the claim/class/time used;
9. row ordering is deterministic at equal timestamps.

Run and confirm the expected pre-change failure: current `statement_panel()` selects maximum
`obs_id`, so the later version incorrectly wins the old cutoff.

**Step 2: Implement a focused panel repository/helper**

Keep SQL selection and the existing panel reshaping in one production implementation. Avoid
duplicating the `income-statements`/`balance-sheets`/`cash-flows`, `filing_dates`, and `obs_ids`
shape across current and as-of readers.

Suggested public contracts:

```text
current_statement_panel(tickers=None, period_type="quarterly")
statement_panel_as_of(
    as_of: datetime,
    evidence_policy: ObservationEvidencePolicy,
    tickers=None,
    period_type="quarterly",
)
```

The as-of return shape additionally carries per-period selection evidence or an adjacent typed
metadata structure. Do not make callers reconstruct it from raw claims.

**Step 3: Preserve compatibility explicitly**

`FundamentalObsRepository.statement_panel()` may remain as a documented temporary wrapper to
`current_statement_panel()`. Add a test proving the wrapper and explicit current reader agree.

Do not silently redirect current page/anchor consumers to fail-closed history.

**Step 4: Run focused and existing repository tests**

```bash
uv run pytest \
  tests/integration/storage/test_fundamental_observation_panels.py \
  tests/integration/storage/test_fundamental_obs.py -q
uv run ruff check src/uw_scan/storage/fundamental_observation_panels.py \
  src/uw_scan/storage/fundamental_obs.py
```

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): split current and as-of statement readers`.

---

## Task 5: Seed honest legacy classifications through a resumable path

**Files:**

- Create: `src/uw_scan/worker/jobs/fundamental_observation_availability.py`
- Create: `scripts/backfill/fundamental_observation_availability.py`
- Create: `tests/unit/worker/test_fundamental_observation_availability.py`
- Create or modify an integration test for the backfill's durable path
- Modify: `docs/runbooks/data-gap-dataset-policy.md`

**Step 1: Write failing tests for classification and resume**

Cover:

1. every legacy observation gets a deterministic current-vintage claim;
2. every observation with a valid aware `first_observed_at` gets a capture-bounded claim at exactly
   that timestamp;
3. no row gets true-PIT from `filing_published_at` alone;
4. a partially completed batch resumes idempotently;
5. rerun writes zero duplicate claims;
6. counters report scanned, current-vintage inserted, capture inserted, already-present, and failed;
7. ticker/range/batch bounds work without changing classification semantics.

**Step 2: Implement one shared core**

The script calls the same job/core used by any scheduler/operator path. Do not duplicate SQL or
classification logic in the script. This is an operator backfill, not a page-triggered action and
not automatically placed on the nightly provider budget.

The backfill persists progress or is naturally resumable by deterministic claims and bounded keyset
pagination. Do not use OFFSET over a table that may grow during forward capture.

**Step 3: Run a real test-database backfill twice**

Prove through a newly opened connection:

- first run creates the expected claims;
- second run creates none;
- source observation counts are unchanged;
- claim-class counts reconcile to the fixtures.

**Step 4: Update operational policy**

Document that availability claims are derived evidence for statement observations, how to backfill,
how to inspect class counts, and why true-PIT coverage is expected to remain lower than statement
coverage.

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): classify legacy observation availability`.

---

## Task 6: Add forward capture-bounded claims without changing content identity

**Files:**

- Modify: `src/uw_scan/worker/jobs/fundamental_ingest.py`
- Modify: `src/uw_scan/worker/jobs/fundamental_ingest_daily.py` only if orchestration requires it
- Modify: `tests/unit/worker/test_fundamental_ingest_filing_dates.py`
- Add focused ingest integration coverage

**Step 1: Write failing ingest tests**

Prove:

1. a newly inserted content version receives a capture-bounded claim tied to its actual persisted
   `first_observed_at`;
2. an unchanged refetch does not create a new availability claim;
3. a changed payload receives a new observation and its own capture claim;
4. later filing-date fill preserves content identity and existing claim;
5. a crash between observation and claim phases is safe: as-of excludes the unclaimed row, and rerun
   repairs the claim;
6. no provider envelope timestamp enters `content_hash`;
7. batch behavior does not introduce per-row queries.

**Step 2: Implement fail-closed integration**

After observation persistence, call the set-based claim method for the persisted batch identities.
If claim persistence fails, surface the stage failure; do not report the ingest fully successful.
Because the source row may already have committed, the retry must heal without another fact row.

Do not classify a provider filing date as true-PIT here unless the payload contains and the contract
validates exact version-level publication evidence. The default forward claim is capture-bounded.

**Step 3: Run ingest regressions**

```bash
uv run pytest \
  tests/unit/worker/test_fundamental_ingest_filing_dates.py \
  tests/unit/worker/test_fundamental_ingest_daily.py \
  tests/integration/storage/test_fundamental_obs.py -q
```

**Authorization checkpoint:** suggested future commit
`feat(fundamentals): capture availability for statement versions`.

---

## Task 7: Route historical scoring through explicit evidence policy

**Files:**

- Modify: `src/uw_scan/worker/jobs/fundamental_scoring.py`
- Modify: `src/uw_scan/fundamentals/scoring.py`
- Modify: `src/uw_scan/storage/fundamental_scores.py`
- Add an additive score/run migration if evidence policy is not already part of durable identity
- Modify: `tests/unit/worker/test_fundamental_scoring_cutoff.py`
- Modify: `tests/integration/storage/test_fundamental_scores.py`
- Add integration coverage joining the as-of panel to scoring

**Step 1: Write failing historical-scoring tests**

Cover:

1. a later restatement does not affect an earlier true-PIT scoring bucket;
2. a later cutoff uses the restatement;
3. capture-bounded mode admits only after capture;
4. true-PIT mode reports/excludes insufficient rows and may cause a thin cross-section rather than
   filling from current-vintage;
5. evidence policy changes `inputs_hash` or durable run identity;
6. identical cutoff/policy/method/observations reproduces the same hash;
7. existing future-knowledge cutoff behavior remains intact;
8. old current-vintage score rows are preserved and distinguishable.

**Step 2: Make mode explicit at the job boundary**

Add an evidence-policy argument with no ambiguous historical default. Scheduled current-page refresh
may retain current behavior under an explicitly named mode/version until M1/M3 migrate it; research
and backtest entry points must pass the policy deliberately.

Do not set all production consumers to `TRUE_PIT_ONLY` in this task if coverage has not been measured.
The purpose is correctness and transparent abstention, not an unreviewed product cutover.

**Step 3: Persist identity and counters**

Store or associate:

- requested cutoff/as-of;
- evidence policy;
- selected observation IDs and claim IDs/classes;
- excluded counts by reason/class;
- engine version and input hash.

If existing score schema cannot hold this without ambiguity, add an additive migration and a new
engine version. Never overload `filing_date_known` to mean version-level PIT.

**Step 4: Run scoring/storage tests**

```bash
uv run pytest \
  tests/unit/worker/test_fundamental_scoring_cutoff.py \
  tests/integration/storage/test_fundamental_scores.py \
  tests/integration/storage/test_fundamental_observation_panels.py -q
```

**Authorization checkpoint:** suggested future commit
`fix(fundamentals): make historical scoring evidence-policy aware`.

---

## Task 8: Protect current anchors, card, and API compatibility

**Files:**

- Modify only as needed: `src/uw_scan/worker/jobs/fundamental_anchors.py`
- Modify only as needed: `src/uw_scan/fundamentals/card.py`
- Modify only as needed: `src/uw_scan/api/routers/stock.py`
- Modify: `tests/unit/fundamentals/test_card.py`
- Modify: `tests/integration/api/test_fundamentals_endpoint.py`
- Modify: `tests/integration/api/test_fundamental_statements_endpoint.py`

**Step 1: Add regression tests before caller edits**

Assert:

- current card/statement history still sees the latest current-vintage observation;
- current anchor inputs do not disappear merely because a row is not true-PIT;
- existing response fields and OpenAPI component names remain stable;
- no public field is relabeled true-PIT without evidence;
- if selection metadata is added, it is backward-compatible and semantically explicit.

**Step 2: Make current-reader calls explicit**

Replace ambiguous internal calls with `current_statement_panel` where this clarifies intent. Do not
redesign the UI or add a new tab in Pre-Job 0.

**Step 3: Run API/card regressions**

```bash
uv run pytest \
  tests/unit/fundamentals/test_card.py \
  tests/unit/fundamentals/test_card_history.py \
  tests/integration/api/test_fundamentals_endpoint.py \
  tests/integration/api/test_fundamental_statements_endpoint.py -q
```

If and only if the OpenAPI contract changes:

```bash
cd web
npm run gen:types
npm run typecheck
npm run test
```

**Authorization checkpoint:** suggested future commit
`refactor(fundamentals): name current statement consumers explicitly`.

---

## Task 9: Add class-distribution audit and operator inspection

**Files:**

- Modify: `scripts/backfill/fundamental_observation_availability.py`
- Create: `docs/research/2026-08-24-fundamental-observation-availability/README.md`
- Create generated result files in that directory only after running against the named target
- Modify: relevant runbook/plan status after evidence exists

**Step 1: Define the audit before production execution**

Required output dimensions:

- row and ticker count by evidence class/source/year/statement/period type;
- rows with multiple content versions;
- earliest/latest eligible availability per policy;
- true-PIT/capture-bounded/current-vintage/unknown coverage by recent and historical windows;
- observations without any claim;
- examples of original/restated selection across cutoffs;
- exact host/database, code commit, command, started/completed timestamps;
- failures and exclusions.

**Step 2: Add deterministic self-checks**

The artifact must fail its self-check when:

- totals do not reconcile;
- any `true_pit` claim lacks positive evidence reference/time;
- a current-vintage/unknown claim has `available_at`;
- an observation has no current classification after backfill;
- selected as-of version violates its policy cutoff.

**Step 3: Do not run production without authorization**

Prepare the command and expected resource/cost behavior. Production mutation requires explicit user
authority. A test/local artifact is not production evidence.

**Authorization checkpoint:** suggested future commit
`docs(fundamentals): audit observation availability coverage` after the artifact is reviewed.

---

## Task 10: Proportional verification and review handoff

**Files:**

- Modify: `docs/handover/2026-08-24-fundamental-pm-research-system-claude-handover.md`
- Modify: `CHANGELOG.md` under `[Unreleased]` only when implementation exists and a PR is being
  prepared
- Update this child plan and the master program status with exact evidence

**Step 1: Run the complete relevant suite**

```bash
uv run pytest \
  tests/unit/fundamentals \
  tests/unit/worker/test_fundamental_ingest_filing_dates.py \
  tests/unit/worker/test_fundamental_ingest_daily.py \
  tests/unit/worker/test_fundamental_scoring_cutoff.py \
  tests/unit/worker/test_fundamental_observation_availability.py \
  tests/integration/storage/test_fundamental_obs.py \
  tests/integration/storage/test_fundamental_observation_availability.py \
  tests/integration/storage/test_fundamental_observation_panels.py \
  tests/integration/storage/test_fundamental_scores.py \
  tests/integration/api/test_fundamentals_endpoint.py \
  tests/integration/api/test_fundamental_statements_endpoint.py
```

Then:

```bash
uv run ruff check .
uv run python scripts/check_no_yahoo.py
git diff --check
git status --short
```

Run full `uv run pytest` before review because migration/storage behavior is repository-wide. Record
the exact pass/fail/skip counts and elapsed time; do not summarize a failure away.

**Step 2: Run migration idempotency proof**

Apply all migrations twice on the allowed isolated/test tier. Query constraints/indexes and claim
counts from a new connection. Record exact commands/results.

**Step 3: Run the real path when authorized**

For any deployed claim, use the real operator/job path:

```text
operator/backfill or enqueue
  -> persisted observation claims
  -> repository as-of read
  -> historical scoring run
  -> persisted result/provenance
  -> API inspection if exposed
```

A direct function call in a temporary script is not the production smoke.

**Step 4: Produce a review report**

State:

- schema and policy actually implemented;
- class distribution and historical spans;
- rows still current-vintage/unknown;
- current-page compatibility evidence;
- exact tests and migration results;
- any API/client impact;
- production work not performed;
- historical claims still blocked;
- next milestone: M1 input eligibility/canonical evidence, followed by M3 corrected research.

**Step 5: Stop before GitHub mutation**

Do not commit, push, or open a PR without explicit user authorization. When authorized, milestone
commits may follow the checkpoints above, the changelog must ride the feature PR, and the branch must
go through a PR before main.

---

## Pre-Job 0 completion gate

Pre-Job 0 is ready for review only when all are true:

- availability terminology and timestamp semantics are frozen in code/docs;
- existing rows/results are preserved;
- a later restatement cannot appear in an earlier true-PIT replay;
- unknown revision timing fails closed;
- capture-bounded rows enter only at/after their conservative capture time;
- current pages retain newest-current behavior;
- same-content refresh and filing-date recovery remain idempotent;
- historical scoring identity includes its evidence policy and selected versions;
- migrations rerun cleanly;
- real SQL integration tests prove selection behavior;
- exact class distribution and unsupported historical spans are reported;
- full relevant tests/lint/no-Yahoo/diff checks are recorded;
- no research verdict has been upgraded merely because the software exists;
- no production mutation, commit, push, PR, or primary-checkout edit occurred without authorization.

## Explicit non-goals

- SEC/Massive full canonical reconciliation beyond evidence required to validate this contract;
- statement-violation exclusion from score math (M1);
- final typed result-provenance graph (M1/M2), except the availability claim FK;
- company-type coverage;
- valuation research rerun;
- score-weight or direction changes;
- UI/Radar/industry-chain/report/narrative/agent implementation;
- deletion or reinterpretation of old current-vintage results;
- automatic production backfill or release.
