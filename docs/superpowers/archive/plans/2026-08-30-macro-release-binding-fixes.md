# Macro Release Binding Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Macro replay vintage-correct and safe across independently deployed API/Web images before merging and releasing PR #399.

**Architecture:** Add an optional UTC replay ceiling to the existing Gold inputs and gauge APIs, then pass it through the typed web client from Overview. Keep live calls byte-compatible by omitting the query when no replay was requested. Treat the shell snapshot as deliberately live, make that clock visible, and classify the producer-less rates event panel as Planned.

**Tech Stack:** FastAPI, psycopg 3, Pydantic v2, Next.js 16, React 19, TypeScript, pytest, Vitest, Playwright.

---

### Task 1: Vintage-bound Gold input series

**Files:**
- Modify: `tests/integration/api/test_gold_router_gauge.py`
- Modify: `src/uw_scan/api/routers/gold.py`
- Modify: `web/tests/unit/apiGold.test.ts`
- Modify: `web/lib/api.ts`

**Step 1: Write the failing API test**

Seed two vintages for one observation date, request
`/api/gold/inputs/DFII10?as_of=2025-01-02`, and assert the response selects the vintage
whose stored `as_of` is at or before that UTC day-end.

**Step 2: Verify RED**

Run `uv run pytest tests/integration/api/test_gold_router_gauge.py -q`.

Expected: the new assertion fails because the route ignores `as_of` and returns the later vintage.

**Step 3: Implement the smallest backend change**

Add `as_of: date | None` to `get_input_series`, resolve it with the desk's shared
`resolve_instant`, and pass the result as `as_of_max` to `fetch_macro_series_daily`.
When omitted, continue passing `None` so the live query is unchanged.

**Step 4: Verify GREEN**

Run the same pytest command and expect all tests in the file to pass.

**Step 5: Write and verify the failing web-client test**

Assert that `api.goldInputSeries(..., { asOf: "2026-08-22" })` emits
`as_of=2026-08-22` and that a live call emits no `as_of`. Run
`cd web && npm run test -- tests/unit/apiGold.test.ts`.

Expected before implementation: FAIL because the range type and query builder have no replay ceiling.

**Step 6: Implement and verify the web client**

Add optional `asOf` to the range contract, emit it as `as_of`, and rerun the test to GREEN.

### Task 2: Vintage-bound persisted gauge history

**Files:**
- Modify: `tests/integration/storage/test_gold_repo_posture.py`
- Modify: `tests/integration/api/test_gold_router_gauge.py`
- Modify: `src/uw_scan/storage/gold.py`
- Modify: `src/uw_scan/api/routers/gold.py`
- Modify: `web/tests/unit/apiGold.test.ts`
- Modify: `web/lib/api.ts`

**Step 1: Write the failing repository and API tests**

The repository test inserts one in-bound and one future-computed posture row and asserts
`fetch_gold_gauge_history(as_of_max=...)` excludes the future row. The API test requests
`/api/gold/gauge?as_of=...` and asserts both current series inputs and persisted history
are bounded to that day.

**Step 2: Verify RED**

Run `uv run pytest tests/integration/storage/test_gold_repo_posture.py tests/integration/api/test_gold_router_gauge.py -q`.

Expected: FAIL because the repository and route do not accept an as-of ceiling.

**Step 3: Implement the backend bound**

Add `as_of_max` to `fetch_gold_gauge_history` and apply `computed_at <= %s`. Add optional
`as_of` to `/api/gold/gauge`; when present, use its UTC day-end for the two macro-series
reads and the persisted-history read, and use the requested date as the correlation
calculation date. Preserve the live path when omitted.

**Step 4: Verify GREEN**

Rerun the focused pytest command and expect all tests to pass.

**Step 5: Test and implement the web client**

Add a failing assertion that `api.goldGauge("2026-08-22")` emits
`?as_of=2026-08-22` while `api.goldGauge()` emits no query. Implement the optional
parameter and rerun the focused Vitest file to GREEN.

### Task 3: Bind Overview replay and survive the old API image

**Files:**
- Modify: `web/app/macro/[tab]/overviewTab.tsx`
- Modify: `web/tests/unit/macroDesk.test.tsx`
- Modify: `web/tests/e2e/macro-replay.spec.ts`

**Step 1: Write failing tests**

Add coverage that replay Overview requests Gold inputs and gauge with the replay ceiling.
Add a rendering case whose gauge payload omits `history_60d`, representing the currently
deployed v0.13.0 API, and assert Overview degrades to a named empty anchor rather than throwing.

**Step 2: Verify RED**

Run `cd web && npm run test -- tests/unit/macroDesk.test.tsx` and the focused Playwright
spec against the local stack. Expected: the compatibility case throws and replay requests
lack `as_of`.

**Step 3: Implement minimal binding changes**

Pass `asOf` into `api.goldGauge` and every `api.goldInputSeries` replay read. Normalize
`gauge.value.history_60d ?? []` before filtering, so an old API image produces an empty
panel until the new API arrives.

**Step 4: Verify GREEN**

Rerun the focused unit and browser tests and expect both to pass.

### Task 4: Make clocks and producer status explicit

**Files:**
- Modify: `web/components/macro/MacroMasthead.tsx`
- Modify: `web/components/macro/MacroFooter.tsx`
- Modify: `web/components/rates/FedDesk.tsx`
- Modify: `web/tests/unit/macroMasthead.test.tsx`
- Modify: `web/tests/unit/rates/FedDesk.test.tsx`

**Step 1: Write failing presentation tests**

Assert the shell says `live chain` and `Live snapshot`, including while the replay menu
shows a historical date. Assert the empty-by-construction rates event panel exposes a
Planned basis rather than Live/REAL.

**Step 2: Verify RED**

Run `cd web && npm run test -- tests/unit/macroMasthead.test.tsx tests/unit/rates/FedDesk.test.tsx`.

Expected: FAIL on the old labels and REAL basis.

**Step 3: Implement and verify GREEN**

Change labels only; do not move the snapshot fetch or invent an event producer. Rerun the
focused tests and expect them to pass.

### Task 5: Full verification and milestone commit

**Files:**
- Move after completion: `docs/superpowers/plans/2026-08-30-macro-release-binding-fixes.md` to `docs/superpowers/archive/plans/`

**Step 1: Run backend verification**

Run the affected integration, storage, rates replay, and confidence-term tests.

**Step 2: Run full web verification**

Run `npm run test`, `npm run typecheck`, `npm run lint`, and `npm run build` under `web/`.

**Step 3: Run browser smoke**

Visit all nine live tabs and representative replay tabs at 1280px. Require no error
boundary, no console error, and no horizontal overflow.

**Step 4: Archive the completed plan and commit**

Stage source, tests, docs, and commit as
`fix(macro): make replay data and release clocks honest`.

**Step 5: Push, wait for all PR checks, then merge and release**

Push the feature branch, wait for PR #399 to be green and mergeable, merge through GitHub,
align local `main`, run `scripts/release/cut.sh prepare patch`, merge the generated release
PR after CI, then run `scripts/release/cut.sh tag`.

Finally verify production version, DB health, Gold gauge history, rates replay bounds,
Frenzy distributions, current confidence-term kinds, and all nine Macro routes.

## Completion record

Completed 2026-08-30. Tasks 1–4 followed RED/GREEN TDD and were saved as separate
milestone commits. Task 3 used a focused `overviewTabBinding` unit boundary rather than
modifying the broad desk renderer test: it directly exercises the async route component,
captures the props handed to presentation, and reproduces the old-API missing-field crash.

Release gate evidence before push:

- backend: 4470 passed, 0 failed, 14 skipped;
- web: 142 files and 1104 tests passed;
- TypeScript, ESLint, Ruff, and the Next.js production build passed;
- real-browser sweep: all nine tabs at 1280, 1440, and 1660px, with zero horizontal
  overflow, error boundaries, console errors, or page errors;
- replay Overview showed the layout's `live chain` and `Live snapshot` labels explicitly.
