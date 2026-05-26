# Complexity Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce reusable-module duplication, simplify large modules, and remove obsolete scanner compatibility code without changing product behavior.

**Architecture:** Keep the current public contracts stable by default: `from uw_scan.models import X`, OpenAPI component names, generated `web/lib/types.ts`, repository re-exports, and migration history must remain valid unless a task is explicitly marked as an API-contract change. Execute the work in small PR-sized phases: first documentation and local UI helper reuse, then scanner cleanup, then schema/model splits behind compatibility wrappers.

**Tech Stack:** Python 3.13 via `uv`, FastAPI/Pydantic v2, psycopg 3, Next.js 16/React 19/TypeScript, Vitest, Playwright, pytest/pytest-postgresql.

---

## Current Evidence Snapshot

- Original plan was drafted on `feat/r2-source-plumbing`, then revalidated in the main-based worktree `chore/complexity-cleanup-main-plan` at `origin/main` commit `13bdb09`.
- Main-based worktree dirty state contains only this untracked plan file. The original checkout still has unrelated untracked docs/PDF artifacts; do not stage or modify them unless the user explicitly asks.
- `src/uw_scan/storage/repository.py` is already a thin aggregate shell at 123 lines. Do not refactor it as a monolith; preserve its compatibility re-exports.
- Scanner regime hard-blocking is obsolete in behavior: `src/uw_scan/scanner/pipeline.py` sets `regime = "pass"` and `src/uw_scan/api/routers/scanner.py` normalizes any legacy persisted `regime=block` row back to `"pass"`.
- Large current files: `web/components/stock/panels/tradeInsightsAi/ProviderTabBody.tsx` 849 lines, `web/components/regime/VcgSubTab.tsx` 810, `web/components/regime/CriSubTab.tsx` 766, `src/uw_scan/models/trade_insights_ai.py` 646, `src/uw_scan/api/schemas.py` 597, `tests/test_trade_insights_ai.py` 2715.
- Shared helper anchors already exist: `web/lib/formatters.ts`, `web/lib/svgChart.ts`, and `web/components/regime/primitives/format.ts`.
- Self-review verified these test files exist in the main-based checkout: `tests/unit/test_models_exports.py`, `tests/unit/test_models_trade_insights_ai_provider.py`, `tests/unit/test_regime_schemas.py`, `tests/integration/api/test_openapi_snapshot.py`, `web/tests/unit/formatters.test.ts`, `web/tests/unit/tradeInsightsAiAnalysisPanel.test.tsx`, `web/tests/unit/CriSubTab.test.tsx`, `web/tests/unit/VcgSubTab.test.tsx`, `web/tests/unit/VolatilityRegimePanel.test.tsx`, `web/tests/unit/MagnetGammaBar.test.tsx`, and `web/tests/unit/greekCharts/GreekSubTabs.test.tsx`.

## Non-Goals

- Do not edit source files from this plan unless the user explicitly asks to implement or patch.
- Do not delete or renumber SQL migrations.
- Do not remove `src/uw_scan/storage/repository.py` compatibility exports.
- Do not change visible UI copy while extracting components unless a test is intentionally updated.
- Do not change OpenAPI response shape in Phases 1-4.
- Do not commit unless the user explicitly authorizes commits. If commits are authorized, use one milestone commit per completed phase.

## Phase 0: Baseline And Guardrails

### Task 0.0: Confirm implementation authorization

**Files:**
- No source changes.

**Steps:**
1. If this plan is being opened for audit/review only, stop after reporting findings.
2. Continue to Task 0.1 only after the user explicitly asks to implement or patch.

**Exit Criteria:**
- The current run is either review-only, or explicit implementation authorization exists.

### Task 0.1: Create an isolated implementation branch or worktree

**Files:**
- No source changes.

**Steps:**
1. Check the current checkout:
   ```bash
   git status --short
   git branch --show-current
   git fetch origin
   git log --oneline --left-right --cherry-pick origin/main...HEAD
   ```
2. Decide the implementation base from evidence:
   - Use the current feature branch when cleanup depends on branch-local refactors.
   - Use `origin/main` only when the diff check proves the plan is not relying on branch-local changes.
3. If already in a main-based planning worktree, verify it instead of creating a nested worktree. Before any source edit, commit, or push, create or switch to a non-main implementation branch whose upstream is not `origin/main` or `origin/master`; for example:
   ```bash
   git switch -c chore/complexity-cleanup-main-impl
   git rev-parse --abbrev-ref --symbolic-full-name @{u} || true
   ```
   If an upstream exists and resolves to `origin/main` or `origin/master`, stop and fix the branch tracking before implementation.
4. If creating a worktree, copy this plan file into the worktree before switching context. Do not stage or modify unrelated untracked artifacts.
5. Confirm `AGENTS.md`, `CLAUDE.md`, `src/uw_scan/CLAUDE.md`, `src/uw_scan/storage/CLAUDE.md`, and `web/CLAUDE.md` are read before implementation.

**Exit Criteria:**
- Implementation work is isolated from unrelated untracked artifacts without dropping required branch context.
- The implementer has confirmed the current branch, upstream, base commit, and dirty files.
- The active implementation branch is not tracking `origin/main` or `origin/master`.

### Task 0.2: Capture baseline quality gates

**Files:**
- No source changes.

**Steps:**
1. Run the narrow baseline commands:
   ```bash
   uv run pytest tests/unit/test_models_exports.py -q
   uv run pytest tests/unit/scanner tests/integration/api/test_scanner_endpoint.py -q
   cd web && npm run test -- formatters svgChart tradeInsightsAiAnalysisPanel
   cd web && npm run typecheck
   ```
2. If any command fails before changes, save the failure output in the PR notes and avoid expanding scope to unrelated failures.

**Exit Criteria:**
- A baseline pass/fail record exists before cleanup starts.

## Phase 1: Documentation Accuracy And No-Code Cleanup

### Task 1.1: Fix stale storage guidance

**Files:**
- Modify: `src/uw_scan/CLAUDE.md`
- Check only: `AGENTS.md`, `CLAUDE.md`, `src/uw_scan/storage/CLAUDE.md`

**Steps:**
1. Search for stale guidance:
   ```bash
   rg -n "storage/repository.py|repository.py|New methods go|add .*persistence method" AGENTS.md CLAUDE.md src/uw_scan/CLAUDE.md src/uw_scan/storage/CLAUDE.md
   ```
2. Update `src/uw_scan/CLAUDE.md` so new persistence methods go to domain storage mixins or focused repositories, not directly to `storage/repository.py`.
3. Preserve the warning that `repository.py` remains an aggregate compatibility shell.
4. Verify:
   ```bash
   rg -n "Add the persistence method to `storage/repository.py`|new methods go.*repository.py" AGENTS.md CLAUDE.md src/uw_scan/CLAUDE.md src/uw_scan/storage/CLAUDE.md
   ```
   Expected: no current-doc instruction tells implementers to add new domain methods directly to `repository.py`.

**Exit Criteria:**
- Current docs match the storage mixin architecture.

## Phase 2: Low-Risk Frontend Reuse

### Task 2.1: Extend shared formatting helpers without migrating callers

**Files:**
- Modify: `web/lib/formatters.ts`
- Modify: `web/tests/unit/formatters.test.ts`

**Steps:**
1. Add tests for compact signed money and signed percent options, covering:
   - `null`/`undefined`
   - zero
   - positive/negative thousands
   - positive/negative millions
   - configurable fraction digits
   - fixed versus maximum fraction digit behavior
   - signed zero behavior
   - configurable empty token if needed for `---` versus `—`
   - unchanged default output for existing `fmtPct`, `fmtMoney`, and `fmtMoneyAbbrev` callers
2. Run the failing test:
   ```bash
   cd web && npm run test -- formatters
   ```
3. Add the minimal helper additions to `web/lib/formatters.ts`.
4. Re-run:
   ```bash
   cd web && npm run test -- formatters
   ```

**Exit Criteria:**
- New helper behavior is locked down before migrating panels.

### Task 2.2: Migrate stock-panel formatter duplicates one panel at a time

**Files:**
- Modify: `web/components/stock/panels/GexProfileChart.tsx`
- Modify: `web/components/stock/panels/VolatilityRegimePanel.tsx`
- Modify: `web/components/stock/panels/MagnetGammaBar.tsx`
- Add or modify: `web/tests/unit/GexProfileChart.test.tsx`
- Modify/check: `web/tests/unit/VolatilityRegimePanel.test.tsx`
- Modify/check: `web/tests/unit/MagnetGammaBar.test.tsx`
- Modify/check: `web/tests/unit/greekCharts/GreekSubTabs.test.tsx`

**Steps:**
1. Add a focused `GexProfileChart` formatting test that pins signed percent and compact signed money labels before changing the component.
2. Run the focused failing/passing test:
   ```bash
   cd web && npm run test -- GexProfileChart
   ```
3. Migrate `GexProfileChart.tsx` local `fmtMoney`/`fmtPct` to shared helpers.
4. Run:
   ```bash
   cd web && npm run test -- GexProfileChart VolatilityRegimePanel MagnetGammaBar GreekSubTabs
   cd web && npm run typecheck
   ```
5. Repeat for `VolatilityRegimePanel.tsx`.
6. Repeat for `MagnetGammaBar.tsx`.
7. Keep each panel's existing sign, precision, compact suffix, and empty-token behavior. If a panel requires a materially different display rule, stop and document the exception instead of forcing a bad abstraction.

**Exit Criteria:**
- At least three local formatter duplicates are removed with no visible text drift.

### Task 2.3: Extract Trade Insights AI private UI primitives

**Files:**
- Create: `web/components/stock/panels/tradeInsightsAi/ui.tsx`
- Modify: `web/components/stock/panels/tradeInsightsAi/ProviderTabBody.tsx`
- Modify: `web/components/stock/panels/tradeInsightsAi/TriggerEvidenceCard.tsx`
- Test: `web/tests/unit/tradeInsightsAiAnalysisPanel.test.tsx`

**Steps:**
1. Move duplicated `Tone`, `toneColor`, `plainText`, and `AnalysisCard` into `ui.tsx`.
2. Extract `KeyValueGrid` only if it accepts a required `formatValue` prop, because `ProviderTabBody.tsx` and `TriggerEvidenceCard.tsx` intentionally format empty and numeric values differently today. If that prop makes the shared component noisier than the duplication, leave `KeyValueGrid` local for this phase.
3. Add or update tests covering null, empty-string, and numeric values in both current callers before and after extraction.
4. Keep component prop names and rendered text unchanged.
5. Run:
   ```bash
   cd web && npm run test -- tradeInsightsAiAnalysisPanel
   cd web && npm run typecheck
   ```
6. Confirm `ProviderTabBody.tsx` line count is reduced meaningfully but do not chase a target line count in this phase.

**Exit Criteria:**
- Shared Trade Insights AI UI primitives exist and both current callers use them.

## Phase 3: Scanner Obsolete-Code Cleanup

### Task 3.1: Remove unreachable scanner regime-block branch from ranking

**Files:**
- Modify: `src/uw_scan/scanner/ranking.py`
- Modify: `tests/unit/scanner/test_ranking.py`

**Steps:**
1. Update tests first to assert setup never becomes `blocked` from scanner regime state because scanner regime is no longer a hard veto.
2. Run the focused failing test:
   ```bash
   uv run pytest tests/unit/scanner/test_ranking.py -q
   ```
3. Remove the unreachable `gates.get("regime") == "block"` branch from `derive_setup`.
4. Keep `regime` in the gates dict and API model for now.
5. Re-run:
   ```bash
   uv run pytest tests/unit/scanner/test_ranking.py tests/unit/scanner/test_pipeline.py -q
   ```

**Exit Criteria:**
- Scanner setup states reflect current behavior: earnings/liquidity can cause caution, not obsolete regime blocking.

### Task 3.2: Preserve API compatibility while documenting gated as deprecated-empty

**Files:**
- Modify: `src/uw_scan/api/models/scanner.py`
- Modify: `src/uw_scan/api/routers/scanner.py`
- Modify: `tests/integration/api/test_scanner_endpoint.py`

**Steps:**
1. Confirm the existing scanner endpoint regression test still proves, or update it only if missing:
   - `gated` remains present as `[]`
   - a legacy persisted `regime=block` row is returned to clients as `regime="pass"`
2. Update comments/docstrings to say `ScannerResponse.gated` is retained only for response compatibility.
3. Do not remove `ScannerGatedTicker` or the `gated` field in this phase.
4. Run:
   ```bash
   uv run pytest tests/unit/scanner tests/integration/api/test_scanner_endpoint.py -q
   uv run pytest tests/integration/api/test_openapi_snapshot.py -q
   ```

**Exit Criteria:**
- Obsolete behavior is not implemented, but public response shape is unchanged.

## Phase 4: Frontend Module Size Reduction

### Task 4.1: Split `ProviderTabBody.tsx` by stable presentational sections

**Files:**
- Create: `web/components/stock/panels/tradeInsightsAi/OutcomeHeader.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/SectionCardsGrid.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/ReadinessCard.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/ValidationChecklistCard.tsx`
- Modify: `web/components/stock/panels/tradeInsightsAi/ProviderTabBody.tsx`
- Test: `web/tests/unit/tradeInsightsAiAnalysisPanel.test.tsx`

**Steps:**
1. Extract one component per review-sized step.
2. Keep `ProviderTabBody` as the only exported entry point.
3. Do not change API types or visible copy.
4. After each extraction, run:
   ```bash
   cd web && npm run test -- tradeInsightsAiAnalysisPanel
   cd web && npm run typecheck
   ```

**Exit Criteria:**
- `ProviderTabBody.tsx` falls below 500 lines or has a documented follow-up for the remaining large block.

### Task 4.2: Extract CRI and VCG table/panel subcomponents

**Files:**
- Create focused files under `web/components/regime/cri/`
- Create focused files under `web/components/regime/vcg/`
- Modify: `web/components/regime/CriSubTab.tsx`
- Modify: `web/components/regime/VcgSubTab.tsx`
- Tests: existing CRI/VCG tests under `web/tests/unit/`

**Steps:**
1. Extract pure helpers first only when they already have tests or can get unit tests cheaply.
2. Extract history table components next.
3. Extract hero/summary panels last.
4. Run:
   ```bash
   cd web && npm run test -- CriSubTab VcgSubTab regime-page
   cd web && npm run typecheck
   ```

**Exit Criteria:**
- CRI/VCG files are reduced without changing the `/regime` visible contract.

## Phase 5: Contract-Preserving Backend Splits

### Task 5.1: Split `api/schemas.py` behind re-export compatibility

**Files:**
- Create: `src/uw_scan/api/models/watchlist.py`
- Create: `src/uw_scan/api/models/regime.py`
- Modify: `src/uw_scan/api/schemas.py`
- Add: `tests/unit/test_api_schemas_exports.py`
- Modify router imports only after `schemas.py` re-export compatibility is proven.

**Steps:**
1. Before moving classes, add `tests/unit/test_api_schemas_exports.py` to pin public `uw_scan.api.schemas` names, key `model_fields` defaults, `__module__ == "uw_scan.api.schemas"` for moved public schema classes, and `EMPTY_*` singleton constants.
2. Move only one domain group first, preferably watchlist/job/OHLC models.
3. Keep `from uw_scan.api.schemas import X` working.
4. Run:
   ```bash
   uv run pytest tests/unit/test_api_schemas_exports.py -q
   uv run pytest tests/integration/api/test_watchlist_endpoint.py tests/integration/api/test_regime_router.py tests/unit/test_regime_schemas.py -q
   uv run pytest tests/integration/api/test_openapi_snapshot.py -q
   ```
5. Only after snapshot stability is proven, optionally migrate router imports to domain modules in a later mechanical task.

**Exit Criteria:**
- `api/schemas.py` becomes a compatibility surface, not the implementation home.

### Task 5.2: Split `models/trade_insights_ai.py` without OpenAPI drift

**Files:**
- Create internal modules under a non-conflicting package name such as `src/uw_scan/models/trade_insights_ai_parts/`.
- Modify: `src/uw_scan/models/trade_insights_ai.py`
- Modify: `src/uw_scan/models/__init__.py`
- Tests: `tests/unit/test_models_exports.py`, `tests/test_trade_insights_ai.py`, `tests/unit/test_models_trade_insights_ai_provider.py`, `tests/integration/api/test_openapi_snapshot.py`

**Steps:**
1. Before moving code, add a field-surface test for key public model classes if missing.
2. Move literals and small submodels first.
3. Preserve `__module__ = "uw_scan.models"` for every public Pydantic model using `_preserve_public_module`.
4. Keep `from uw_scan.models import TradeInsightAiOutcome` and OpenAPI component names unchanged.
5. Do not replace `src/uw_scan/models/trade_insights_ai.py` with a same-named package in this cleanup PR; that import-system reshuffle is higher risk than the model split itself.
6. Run:
   ```bash
   uv run pytest tests/unit/test_models_exports.py tests/unit/test_models_trade_insights_ai_provider.py -q
   uv run pytest tests/test_trade_insights_ai.py -q
   uv run pytest tests/integration/api/test_openapi_snapshot.py -q
   ```

**Exit Criteria:**
- The contract file becomes an export/composition surface with no generated schema drift.

## Phase 6: Optional API Contract Deprecation PR

Only start this after Phases 1-5 land and the user explicitly approves an API-contract change.

### Task 6.1: Remove `ScannerResponse.gated`

**Files:**
- Modify: `src/uw_scan/api/models/scanner.py`
- Modify: `src/uw_scan/api/routers/scanner.py`
- Modify: `tests/integration/api/test_scanner_endpoint.py`
- Regenerate: `web/lib/types.ts`
- Modify frontend scanner tests only if they still expect `gated`.

**Steps:**
1. Remove the field in a dedicated contract PR.
2. Run:
   ```bash
   uv run pytest tests/integration/api/test_scanner_endpoint.py tests/integration/api/test_openapi_snapshot.py -q
   uv run python -c 'import json; from uw_scan.api.server import create_app; print(json.dumps(create_app().openapi(), separators=(",", ":")))' > /tmp/uw_openapi.json
   npx --prefix web openapi-typescript /tmp/uw_openapi.json -o web/lib/types.ts
   cd web && npm run test -- scannerPage
   cd web && npm run typecheck
   ```
3. Inspect `git diff -- web/lib/types.ts` and mention the API contract change in the PR.

**Exit Criteria:**
- Public scanner API no longer exposes an always-empty compatibility field.

## Final Verification Before PR Review

Run the narrow gates for touched areas, then:

```bash
git diff --check
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run pytest tests/unit/ -q
cd web && npm run typecheck
cd web && npm run test
```

For backend API/model changes:

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
uv run python -c 'import json; from uw_scan.api.server import create_app; print(json.dumps(create_app().openapi(), separators=(",", ":")))' > /tmp/uw_openapi.json
npx --prefix web openapi-typescript /tmp/uw_openapi.json -o web/lib/types.ts
git diff -- web/lib/types.ts
```

For UI changes with layout risk:

```bash
cd web && npm run test -- regime-page tradeInsightsAiAnalysisPanel volatilityPanels
```

Then run a browser smoke on impacted pages:
- `/stock/TSLA` Trade Insights AI panel
- `/stock/TSLA/volatility`
- `/regime`
- `/scanner`

## Rollback Plan

- Formatter and UI extraction phases should be revertible independently because they do not change API contracts.
- Scanner behavior cleanup keeps API compatibility until Phase 6, so rollback is a normal git revert of Phase 3.
- API/model split phases must be reverted as a whole if OpenAPI component names or generated frontend types drift unexpectedly.

## Review Checklist

- [ ] No migration files deleted or renumbered.
- [ ] No new query methods added to `src/uw_scan/storage/repository.py`.
- [ ] `from uw_scan.models import X` still works for all public models.
- [ ] OpenAPI snapshot unchanged except in explicitly approved contract PRs.
- [ ] `web/lib/types.ts` changes only when API schema changes are intentional.
- [ ] `git diff --name-status -- src/uw_scan/storage/migrations` is empty unless a migration task was explicitly approved.
- [ ] No commits were created without explicit user authorization.
