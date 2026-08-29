# Macro Desk Signal-First Redesign Implementation Plan

> **Execution note:** complete each task with red/green verification and commit each
> closed milestone. Do not push without a new explicit request.

**Goal:** Make every Macro tab concise, fully visible without horizontal scrolling, and
explicitly bound to live/derived/planned/reference data while preserving analytical
meaning and replay correctness.

**Architecture:** Keep the current API calls, route registry, replay gates, and panel
composition. Replace the presentation boundary: a fluid AppShell, compact shared chrome,
human label helpers, collapsible audit details, responsive tables, and a concise Method
tab. Treat data provenance as structured metadata rather than repeated primary copy.

**Tech:** Next.js 16, React 19, TypeScript, CSS, Vitest, Playwright.

---

## Task 1: Lock the new shell and overflow contract

**Files:**
- Modify: `web/tests/unit/AppShell.test.tsx`
- Modify: `web/tests/unit/macroMasthead.test.tsx`
- Modify: `web/tests/unit/macroTabBar.test.tsx`
- Modify: `web/tests/e2e/macro-desk.spec.ts`
- Modify: `web/components/shared/AppShell.module.css`
- Modify: `web/components/macro/MacroMasthead.tsx`
- Modify: `web/components/macro/BoardLegend.tsx`
- Modify: `web/components/macro/MacroTabBar.tsx`
- Modify: `web/components/macro/tabs.ts`
- Modify: `web/components/macro/MacroFooter.tsx`
- Modify: `web/app/macro/shell.css`

1. Add failing tests for the compact title/purpose/status, labels without ordinals, and
   absence of the proposal/legend/question rail.
2. Add a failing browser assertion that every Macro route fits at 1280/1440/1660 with no
   horizontal scrollable descendant.
3. Make AppShell Macro main fluid and remove horizontal scroll ownership.
4. Implement compact chrome and a grid/wrapping tab row.
5. Run the focused unit tests and browser overflow spec.
6. Commit: `feat(macro): simplify the desk shell and remove horizontal scroll`

## Task 2: Create the presentation vocabulary

**Files:**
- Create: `web/components/macro/presentation.ts`
- Create: `web/components/macro/DataDetails.tsx`
- Create: `web/tests/unit/macroPresentation.test.tsx`
- Modify: `web/components/macro/domain/BoardPanel.tsx`
- Modify: `web/app/macro/board.css`

1. Add failing tests for humanized states, field names, source labels, and visible basis
   labels (`Live`, `Derived`, `Planned`).
2. Add a failing test that panel Q metadata remains in attributes but has no visible chip.
3. Implement the centralized formatters and shared Data details disclosure.
4. Change BoardPanel/BoardSecTitle to use the new hierarchy.
5. Replace horizontal table scrolling with wrapping/fixed-layout and narrow stacked rows.
6. Run focused tests and commit: `feat(macro): add human presentation and audit details`

## Task 3: Simplify Overview, Fed, and Rates

**Files:**
- Modify: `web/components/macro/OverviewDesk.tsx`
- Modify: `web/components/macro/overview/*.tsx`
- Modify: relevant components under `web/components/rates/`
- Modify: `web/tests/unit/macroDesk.test.tsx`
- Modify: relevant Rates/Fed unit tests

1. Add failing copy/identifier tests around key panels.
2. Shorten section/panel names and interpretive text; translate raw states and variables.
3. Keep all live values and replay gates unchanged.
4. Move source paths/formulas into Data details.
5. Verify targeted tests and screenshots; commit:
   `feat(macro): focus overview fed and rates on decisions`

## Task 4: Simplify Inflation, Dollar, Gold, Energy, and Factors

**Files:**
- Modify: `web/components/macro/DomainStateTab.tsx`
- Modify: `web/components/macro/domain/{ConfidencePanels,InflationPanels,UsdPanels,EnergyProposal,FactorExport,FactorTable}.tsx`
- Modify: `web/app/macro/[tab]/goldTab.tsx`
- Modify: related unit tests

1. Add failing tests for human labels and removal of raw visible identifiers.
2. Reduce each tab standfirst to one sentence and each refusal to one concise limit.
3. Preserve live/derived values and classify proposed/reference content explicitly.
4. Make all tables fit without horizontal scrolling.
5. Verify targeted tests and screenshots; commit:
   `feat(macro): simplify domain tabs without losing evidence`

## Task 5: Replace Design Notes with Method and audit bindings

**Files:**
- Replace: `web/components/macro/DesignNotes.tsx`
- Delete: `web/components/macro/designNotesReference.ts`
- Modify: `web/tests/unit/macroDesignNotes.test.tsx`
- Create: `web/tests/unit/macroBindingAudit.test.tsx`
- Modify: runtime components found by the binding audit

1. Add a failing test for the concise Method sections and absence of internal review copy.
2. Add binding-audit tests that classify each runtime panel and reject frozen analytical
   values in planned/reference content.
3. Replace the 18,500-character reference artifact with current method/coverage/limits.
4. Fix any static or mislabeled runtime data found by the audit.
5. Verify and commit: `refactor(macro): replace design notes with a live method audit`

## Task 6: Full regression and visual review

**Files:**
- Modify only files implicated by failures
- Add screenshots under `output/playwright/macro-signal-first/`
- Update: `CHANGELOG.md`

1. Run Macro unit tests, typecheck/lint as configured, and all relevant Playwright specs.
2. Run the nine-route × three-width overflow/visible-identifier sweep.
3. Review Overview, Fed, Inflation, Gold, and Method screenshots against the design gates.
4. Remove unnecessary code exposed by the review.
5. Add the Unreleased changelog entry.
6. Commit verification/remediation and changelog as the final meaningful milestone.
