# Macro MC1 FOMC, SEP, and Policy Paths Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ingest free official FOMC decisions and SEP distributions, preserve revisions and release
times, and expose actual, committee, dealer, and market-implied policy paths as separate contracts.

**Architecture:** extend the existing FOMC calendar/statement source with dedicated Federal Reserve
SEP and New York Fed survey adapters. Normalize all releases into MC0 artifacts/observations and
assemble four independent policy-path objects; the existing Frenzy path remains a delayed,
third-party market shadow and is never labeled official.

**Tech Stack:** httpx/BeautifulSoup, `openpyxl` for the NY Fed's official structured SME workbook,
Postgres MC0 evidence store, APScheduler, Pydantic v2, FastAPI.

---

## Preconditions and PR boundary

- MC0/GM0 is verified and merged.
- Recheck official page structures before coding:
  Federal Reserve FOMC calendars/statements, official SEP tables/FAQ, and New York Fed Survey of
  Market Expectations.
- Persist representative official HTML/PDF fixtures under `tests/fixtures/macro/`; do not unit-test
  against the live internet.
- No Chair-specific anonymous-dot inference and no combined “Fed path” score.

### Task 1: Write source-parser fixtures and failing tests

**Files:**
- Create: `tests/fixtures/macro/fed_sep_2026_06.html`
- Create: `tests/fixtures/macro/nyfed_sme_2026_06.xlsx`
- Create: `tests/fixtures/macro/nyfed_sme_2026_06.pdf`
- Modify: `tests/unit/sources/test_fomc_calendar.py`
- Create: `tests/unit/sources/test_fed_sep.py`
- Create: `tests/unit/sources/test_nyfed_sme.py`

**Steps:**

1. Pin one FOMC statement with target action and vote split.
2. Pin one official SEP table containing the participant distribution and published medians.
3. Pin one NY Fed SME structured-data release containing meeting-path/distribution fields and its
   matching human-readable PDF.
4. Test exact dates, units, participant-count totals, medians, source record IDs, and release times.
5. Test malformed/missing tables raise a normalization error rather than returning an empty release.
6. Run the three tests. Expected: new source modules are missing and tests FAIL.

### Task 2: Implement official Federal Reserve SEP parsing

**Files:**
- Create: `src/uw_scan/sources/fed_sep.py`
- Modify: `src/uw_scan/sources/fomc_calendar.py`
- Test: `tests/unit/sources/test_fed_sep.py`
- Test: `tests/unit/sources/test_fomc_calendar.py`

**Required typed outputs:**

```text
SepRelease(release_date, meeting_date, source_url, source_record_id, projections)
SepProjection(variable, horizon, central_tendency, range, median, participant_distribution)
```

**Steps:**

1. Discover SEP links from official calendar/release pages rather than hardcoding the latest URL.
2. Parse exact one-eighth-point dot distribution counts when the official table provides them; retain
   published medians separately.
3. Validate all distribution counts are nonnegative integers and totals are internally consistent per
   horizon.
4. Preserve anonymous distributions only. Do not expose a participant identity field.
5. Emit audit metadata needed by MC0 before returning normalized rows.
6. Run parser tests. Expected: PASS.

### Task 3: Implement New York Fed dealer-expectations parsing

**Files:**
- Create: `src/uw_scan/sources/nyfed_sme.py`
- Create: `tests/unit/sources/test_nyfed_sme.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Steps:**

1. Use the already-locked production `openpyxl` dependency to parse the official structured data;
   do not add a PDF-coordinate parser to the critical data path.
2. Discover the latest SME release from the NY Fed publisher page and retain both exact XLSX and
   PDF bytes, media types, lengths, and artifact hashes before parsing.
3. Extract only preregistered policy-path/distribution rows. Store workbook sheet, panel, and
   publisher value tag in `source_record_id` metadata so a reviewer can reproduce extraction.
4. Reject a release if expected labels, units, or table totals change.
5. Normalize the explicit `Dealer` panel to dealer path points without mixing the separate market-
   participant panel or translating either into SEP or market-implied semantics.
6. Run fixture tests. Expected: PASS.

### Task 4: Persist four typed policy paths

**Files:**
- Create: `src/uw_scan/macro/policy.py`
- Create: `src/uw_scan/macro/__init__.py`
- Modify: `src/uw_scan/models/macro.py`
- Modify: `src/uw_scan/storage/macro_context.py`
- Create: `tests/unit/macro/test_policy_paths.py`
- Modify: `tests/integration/storage/test_macro_context_repository.py`

**Steps:**

1. Add `PolicyPathKind = actual | committee_projection | dealer_expectations | market_implied`.
2. Create a pure assembler that refuses duplicate kinds and never averages across kinds.
3. Map official statements to `actual`, SEP to `committee_projection`, SME to
   `dealer_expectations`, and futures/OIS observations to `market_implied`.
4. Allow Frenzy rows only when evidence is labeled `free_third_party_shadow`; surface their delay and
   source explicitly.
5. Test disagreement remains visible and removing one path does not mutate another.
6. Test an as-of before an SEP release cannot see that SEP.

### Task 5: Add worker ingestion and immutable release persistence

**Files:**
- Create: `src/uw_scan/worker/jobs/macro_policy_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Create: `tests/integration/worker/test_macro_policy_jobs.py`

**Steps:**

1. Implement independent jobs for FOMC statements/calendar, SEP, and NY Fed SME; each writes raw
   artifact/audit before normalized observations.
2. Add explicit enable flags defaulting off and bounded retry/backoff at the orchestration layer.
3. Do not make the official jobs depend on Frenzy availability.
4. Test unchanged rerun writes no new fact; a changed artifact creates a new release/vintage.
5. Test one source failure leaves other paths available and records degraded freshness.

### Task 6: Expose a policy comparison API

**Files:**
- Create: `src/uw_scan/api/routers/macro.py`
- Modify: `src/uw_scan/api/server.py`
- Modify: `src/uw_scan/models/macro.py`
- Create: `tests/integration/api/test_macro_policy_router.py`
- Modify: `web/lib/types.ts` via generation

**Endpoint:** `GET /api/macro/policy?as_of=YYYY-MM-DD`

**Steps:**

1. Return four separately keyed path objects, evidence refs, release times, freshness, and
   contradictions.
2. Return `null` plus a reason for a missing path; never synthesize a substitute path.
3. Verify historical `as_of` replay and OpenAPI component stability.
4. Regenerate TypeScript types.

### Task 7: Real-source probe, documentation, and conditional checkpoint

**Files:**
- Create: `scripts/research/fomc_sep_source_probe.py`
- Create: `docs/research/2026-08-12-fomc-sep-source-probe/README.md`
- Create: `docs/research/2026-08-12-fomc-sep-source-probe/probe.json`
- Create: `docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md`
- Modify: `src/uw_scan/sources/CLAUDE.md`

Run the probe against official free sources, persist status/content hash/table counts, and add a
`--self-check`. Then run:

```bash
uv run pytest tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fed_sep.py tests/unit/sources/test_nyfed_sme.py tests/unit/macro/test_policy_paths.py tests/integration/storage/test_macro_context_repository.py tests/integration/worker/test_macro_policy_jobs.py tests/integration/api/test_macro_policy_router.py -q
cd web && npm run gen:types
uv run python scripts/research/fomc_sep_source_probe.py --self-check
git diff --check
```

Expected: all tests and self-check pass; the probe distinguishes HTTP/parse/empty states.

If and only if explicitly authorized, checkpoint with a scoped `feat(macro): ingest official FOMC
and SEP evidence` commit.

## MC1 exit criteria

- official decisions/votes/statements replay by release time;
- SEP distributions and medians replay without participant attribution;
- dealer expectations and market-implied pricing remain independent;
- Frenzy is visibly third-party/delayed and non-load-bearing;
- parser drift fails loudly with retained artifacts;
- source failure degrades one path, not the whole policy view;
- real official-source probe and worker/database/API tests pass.
