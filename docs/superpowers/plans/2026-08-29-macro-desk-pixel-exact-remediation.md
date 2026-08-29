# Macro Desk Pixel-Exact Remediation Implementation Plan

> Execute in order. Each behavior change starts with a failing test. Do not commit or
> push without separate user authorization.

**Execution note (2026-08-30):** the operator subsequently authorized local milestone
commits. Push, PR mutation, merge, and deployment remain unauthorized.

**Goal:** close correctness, data, visual, and maintainability gaps in PR #399 and
prove a full-shell, nine-tab, live-bound port of the approved Claude board.

## 1. Correctness regressions

- Add a web API unit test proving a replay calendar date uses the `as_of` parameter
  instead of a naive `as_of_ts`; run it red, fix `macroContextSnapshot`, and run it green.
- Add repository/router/model tests for persisted daily 60-day gold gauge history; run
  them red, implement the additive response field and repository query, and run green.
- Regenerate OpenAPI TypeScript types and update focused contract snapshots.

## 2. Full Macro shell

- Add an `AppShell` test proving `/macro*` retains the 220px Sidebar and translates the
  complete 1440px macro canvas to its right, while normal routes keep their fluid shell.
- Add shell/component tests for reference order, complete nine-tab navigation, classes,
  numbering, and replay query preservation.
- Implement route-aware `AppShell`, Macro masthead, intro/legend/question strip, and
  board tab classes. Move shell-only rules from global CSS into scoped board CSS.

## 3. Exact per-tab inventory

- Add one declarative reference-manifest test for all 58 panel titles and order.
- Refactor Fed and Rates to remove or fold non-reference Summary, Cross-Market, and
  Source Freshness panels and rename the curve panel.
- Bind Overview and Gold to the persisted 60-day history and reference headings.
- Fold Energy's preview material into the two reference panels.
- Rebuild Design Notes as the 11 reference panels with board primitives.
- Match reference section headings, questions, grids, provenance, and refusal placement
  on Inflation, USD, Gold, and Factor Export.

## 4. Module and CSS simplification

- Split `[tab]/page.tsx` into per-tab loaders/components, keeping dispatch small.
- Split Overview zone modules that exceed 500 lines along panel seams.
- Remove dead Rates CSS selectors and shell styles no longer referenced.
- Reduce historical comments and compress the feature CHANGELOG entry without deleting
  user-visible behavior.
- Run typecheck and focused tests after each seam move.

## 5. Exhaustive visual gate

- Replace first-match probing with all-occurrence DOM/style/geometry capture.
- Include app bar, intro, PM strip, tabs, main wrapper, all nine tabs, and Design Notes.
- Add deterministic board-snapshot API fixtures for visual verification while retaining
  separate live-binding tests.
- Produce paired screenshots and a JSON/Markdown report under
  `output/playwright/board-compare/`.
- Iterate until every unexplained DOM/style/geometry difference is closed.

## 6. Production verification and final review

- Run focused Python and web tests, then full Python/web suites, generated-type check,
  typecheck, lint, posture lint, and version sync.
- Build Next production output and run Playwright against the production server for all
  tabs, redirects, replay, unavailable data, and responsive breakpoints.
- Review `origin/main...HEAD` for correctness, unused code, excess comments/CSS, API
  compatibility, and accidental unrelated changes.
- Update the handover with current measurements and remaining external-data limitations.
- Stop before commit/push/PR mutation.

## 7. Activate the approved market-implied shadow

- Run the existing Frenzy parser and worker integration tests before changing an
  environment; this is configuration activation, not a new source implementation.
- Enable `UW_SCAN_MACRO_MARKET_SHADOW_INGEST_ENABLED=true` in the local and Mac mini
  environment files while keeping `RATES_POLICY_PATH_URL` on the audited Frenzy URL.
- Restart only the environment-frozen worker that owns macro-policy scheduling.
- Execute one initial production worker ingestion so the page does not wait for the
  next 19:15 ET cron, then let the daily scheduler maintain the series.
- Verify the persisted artifact, `POLICY_PATH_MARKET_IMPLIED` observation, API source
  classification, non-empty probability distributions, and visible probability bars.
- Confirm a repeated ingest is idempotent for an unchanged payload and retains
  `delay_status=unknown`: request-varying raw bytes may add an exact artifact, but the
  unchanged normalized distribution must not add an observation. Do not commit
  environment files or credentials.
