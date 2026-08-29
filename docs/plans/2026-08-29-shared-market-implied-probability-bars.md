# Shared Market-Implied Probability Bars Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render the Frenzy per-meeting probability distribution correctly on both Overview and Fed without zero-probability segments distorting the bar.

**Architecture:** Extract one pure market-implied meeting-bar component used by both tabs. The component visually renders only finite positive buckets, preserves every publisher bucket in an accessible description, and allocates the usable track by flex weight so padding and gaps cannot alter the probability ratio. Overview binds directly to `market_implied.path.points` and retains its existing refusal only when that path is absent.

**Tech Stack:** React 19, TypeScript, Next.js 16, Vitest, Testing Library, hand-written CSS.

---

### Task 1: Lock the publisher distribution behavior

**Files:**
- Modify: `web/tests/unit/rates/fixture.ts`
- Modify: `web/tests/unit/rates/FedDesk.test.tsx`

**Step 1: Add a live Frenzy fixture**

Add a `POLICY_COMPARISON_WITH_MARKET_PATH` fixture containing three dated points. Each point includes zero-probability Cut/Hike buckets plus positive Hike 25 bp and Hold buckets.

**Step 2: Write the failing Fed test**

Assert that the first bar exposes the full distribution through `aria-label`, renders only the two positive segments, labels them `Hike 25 bp` and `Hold`, and assigns flex weights matching 55.7 and 44.3.

**Step 3: Run the focused test and verify RED**

Run: `cd web && npm run test -- tests/unit/rates/FedDesk.test.tsx`

Expected: FAIL because the current implementation renders all five buckets and uses percentage width.

### Task 2: Bind Overview to the same live path

**Files:**
- Modify: `web/tests/unit/macroDesk.test.tsx`

**Step 1: Widen the Desk policy type to the real API contract**

Allow the test helper to receive `PolicyComparison` while keeping its empty default.

**Step 2: Write the failing Overview tests**

Assert that a live Frenzy path renders all three meeting bars through the shared test contract and removes `macro-market-implied-refusal`. Retain a separate assertion that a missing path still renders the refusal and its publisher reason.

**Step 3: Run the focused test and verify RED**

Run: `cd web && npm run test -- tests/unit/macroDesk.test.tsx`

Expected: FAIL because Overview currently ignores `market_implied.path.points` and always renders the refusal.

### Task 3: Implement the shared renderer

**Files:**
- Create: `web/components/macro/MarketImpliedMeetingBars.tsx`
- Modify: `web/components/rates/sections/MarketImpliedOddsSection.tsx`
- Modify: `web/components/macro/overview/zone3.tsx`
- Modify: `web/app/macro/board.css`

**Step 1: Add the minimal shared component**

Normalize string probabilities with `Number`, keep finite positive buckets for visible segments, create a full-distribution `aria-label`, and expose each visible probability through `flexGrow` with `flexBasis: 0`.

**Step 2: Replace the Fed-local markup**

Render the shared component for `slot.path.points`, retaining the existing publisher explanation and release caption.

**Step 3: Replace Overview's stale dealer-derived calendar**

When market points exist, render the shared component and a source/release caption. When absent, retain the existing refusal and reason. Update the source rail so it describes the branch actually rendered.

**Step 4: Correct the CSS contract**

Keep the approved orange Hike and blue Hold styling, make segment sizing border-box/min-width-safe, and add a distinct Cut class for future non-zero cut outcomes.

**Step 5: Run focused tests and verify GREEN**

Run: `cd web && npm run test -- tests/unit/rates/FedDesk.test.tsx tests/unit/macroDesk.test.tsx`

Expected: PASS.

### Task 4: Regression and browser verification

**Files:**
- Modify only if a regression is found: files above
- Evidence: `output/playwright/`

**Step 1: Run the relevant web suite**

Run: `cd web && npm run test`

Expected: PASS.

**Step 2: Run static checks**

Run: `cd web && npm run lint`

Expected: PASS.

**Step 3: Verify both live tabs**

Open `/macro/overview` and `/macro/fed` on port 3002. Confirm three meeting bars on each tab, exactly two visible segments for the current data, no `C C H` slivers, no Overview refusal, and matching Hike/Hold proportions.

**Step 4: Review the scoped diff**

Confirm the shared component removed duplicated rendering logic and that no unrelated dirty-worktree files changed as part of this fix. Do not commit without explicit user authorization.
