# Codebase Uplift Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce release risk, complexity, and avoidable performance cost in the unusual-whales codebase without changing product behavior.

**Architecture:** Treat this as a sequence of small PRs, not one broad cleanup. Start with hygiene and verification gates, then move to measured refactors in the highest-change surfaces: Trade Insights AI, frontend lint/runtime purity, migration ordering, and persistence batching. Preserve public contracts, API shapes, database semantics, and visual layout unless a task explicitly says otherwise.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, psycopg 3, Postgres migrations, Next.js 16, React 19, TypeScript, Vitest, Playwright, GitHub Actions.

---

## Verified Assumptions and Safety Corrections

These assumptions were verified against the repo on 2026-05-24 before execution:

- `main` and `origin/main` were both at `e23a3cd39eae81ee3343984dc6534b417c839cd9`.
- This plan was untracked in the base checkout. A fresh worktree from `origin/main` will not contain it unless the plan is committed first or made available in that worktree before implementation starts.
- Existing duplicate migration prefixes are real and currently tolerated by lexical migration order: `037`, `038`, `039`, `040`, `041`, `042`, `047`, `052`, `053`, `054`, `055`.
- `src/uw_scan/reports/trade_insights_ai/validators.py` exists and `src/uw_scan/reports/trade_insights_ai/validators/` does not. Do not create a `validators/` directory beside `validators.py`.
- `web/package-lock.json` exists, but there is no repo-level `.nvmrc`, `.node-version`, or `mise.toml`. The lockfile shows Next requires Node `>=20.9.0`, so CI must pin Node explicitly.
- `web/components/rates/RatesDesk.tsx` still owns helper/source formatting and sections beyond the first five planned extracts. The rates split must include those helpers or explicitly leave them as a follow-up.

Abort or split the PR whenever a task starts changing product behavior, API shape, SQL semantics, or layout outside its stated scope. If a refactor fails verification twice for the same reason, stop and write down the blocker before continuing.

---

## Ground Rules

- Use an isolated worktree for implementation, for example `.claude/worktrees/codebase-uplift`.
- Before executing from a fresh worktree, verify this plan exists in that worktree with `test -f docs/plans/2026-05-24-codebase-uplift.md`. If it does not, land or carry the plan into the worktree first.
- Never push directly to `main`.
- Keep each task in its own PR unless explicitly grouped below.
- Run the narrow verification first, then the broader gate.
- Do not mix behavior changes with pure moves.
- Do not rename old migrations casually without a migration-order guard first.
- Do not change API contracts unless the task says to regenerate and verify `web/lib/types.ts`.

## Target PR Sequence

1. **PR A — Hygiene and Guardrails:** `.gitignore`, artifact cleanup, duplicate migration-prefix detection.
2. **PR B — Frontend CI and Lint Baseline:** fix current web lint errors, add web checks to CI.
3. **PR C — Documentation Accuracy:** update stale repo doctrine and decide which untracked review docs should land.
4. **PR D — Persistence Batching:** convert proven per-row insert loops to `executemany`.
5. **PR E0 — Trade Insights AI Prompt Metadata Contract:** remove hard-coded prompt-version copy with an explicit API field.
6. **PR E — Trade Insights AI UI Split:** decompose the 1,493-line client component without API changes.
7. **PR F — Trade Insights AI Backend Split:** split lenient coercion and validators while preserving public entry points.
8. **PR G — Rates/Regime UI Size Reduction:** split large panels after the CI baseline is enforced.

---

## PR A: Hygiene and Guardrails

### Task A1: Create a clean worktree

**Files:**
- No code files.

**Steps:**
1. Run:
   ```bash
   git fetch origin
   git worktree add .claude/worktrees/codebase-uplift -b chore/codebase-uplift origin/main
   cd .claude/worktrees/codebase-uplift
   ```
2. Verify:
   ```bash
   git status --short --branch
   ```
   Expected: clean branch from `origin/main`.

### Task A2: Add ignore rules for known local artifacts

**Files:**
- Modify: `.gitignore`

**Add patterns:**
```gitignore

# Local browser/debug artifacts
.playwright-cli/
*.log
*.dmg
*.base64.txt
/*-snapshot.md
```

**Steps:**
1. Write the failing checks:
   ```bash
   git check-ignore -v .playwright-cli/page.yml || true
   git check-ignore -v docs/kiro-ide-0.12.224-stable-darwin-arm64.dmg || true
   git check-ignore -v rates-summary-console.log || true
   git check-ignore -v wgc-gold-demand-xlsx-base64.txt || true
   git check-ignore -v rates-decomp-snapshot.md || true
   ```
   Expected before change: no matching ignore rule for these paths.
2. Update `.gitignore`.
3. Re-run the checks.
   Expected after change: each path prints a matching `.gitignore` rule.
4. Verify no tracked file is accidentally ignored:
   ```bash
   git ls-files -ci --exclude-standard
   ```
   Expected: empty.
5. Commit:
   ```bash
   git add .gitignore
   git commit -m "chore: ignore local debug artifacts"
   ```

### Task A3: Add duplicate migration-prefix detection

**Files:**
- Create: `scripts/check_migration_prefixes.py`
- Create or modify: `tests/unit/storage/test_migration_prefixes.py`

**Implementation:**
```python
from __future__ import annotations

from collections import defaultdict
from pathlib import Path


GRANDFATHERED_DUPLICATE_PREFIXES = frozenset(
    {
        "037",
        "038",
        "039",
        "040",
        "041",
        "042",
        "047",
        "052",
        "053",
        "054",
        "055",
    }
)


def duplicate_prefixes(migrations_dir: Path) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in migrations_dir.glob("*.sql"):
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            grouped[prefix].append(path.name)
    return {key: sorted(names) for key, names in grouped.items() if len(names) > 1}


def unexpected_duplicate_prefixes(migrations_dir: Path) -> dict[str, list[str]]:
    duplicates = duplicate_prefixes(migrations_dir)
    return {
        prefix: names
        for prefix, names in duplicates.items()
        if prefix not in GRANDFATHERED_DUPLICATE_PREFIXES
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    duplicates = unexpected_duplicate_prefixes(root / "src/uw_scan/storage/migrations")
    if not duplicates:
        return 0
    for prefix, names in sorted(duplicates.items()):
        print(f"unexpected duplicate migration prefix {prefix}: {', '.join(names)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

**Test:**
```python
from pathlib import Path

from scripts.check_migration_prefixes import (
    duplicate_prefixes,
    unexpected_duplicate_prefixes,
)


def test_duplicate_prefixes_detected(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "001_second.sql").write_text("", encoding="utf-8")
    assert duplicate_prefixes(tmp_path) == {
        "001": ["001_first.sql", "001_second.sql"]
    }


def test_duplicate_prefixes_accepts_unique_prefixes(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "002_second.sql").write_text("", encoding="utf-8")
    assert duplicate_prefixes(tmp_path) == {}


def test_unexpected_duplicate_prefixes_grandfathers_existing_prefixes(
    tmp_path: Path,
) -> None:
    (tmp_path / "037_gex_snapshots.sql").write_text("", encoding="utf-8")
    (tmp_path / "037_gold_macro_series.sql").write_text("", encoding="utf-8")
    assert unexpected_duplicate_prefixes(tmp_path) == {}


def test_unexpected_duplicate_prefixes_rejects_new_collisions(
    tmp_path: Path,
) -> None:
    (tmp_path / "099_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "099_second.sql").write_text("", encoding="utf-8")
    assert unexpected_duplicate_prefixes(tmp_path) == {
        "099": ["099_first.sql", "099_second.sql"]
    }
```

**Steps:**
1. Add script and unit tests.
2. Run:
   ```bash
   uv run pytest tests/unit/storage/test_migration_prefixes.py -q
   ```
   Expected: pass.
3. Run against current tree:
   ```bash
   uv run python scripts/check_migration_prefixes.py
   ```
   Expected: pass, because current duplicate prefixes are explicitly grandfathered.
4. Verify the grandfathered list matches the current tree:
   ```bash
   ls src/uw_scan/storage/migrations/ | awk -F_ '{print $1}' | sort | uniq -d
   ```
   Expected: only `037`, `038`, `039`, `040`, `041`, `042`, `047`, `052`, `053`, `054`, and `055`.
5. Later cleanup only: renumber duplicate migrations in a dedicated migration-history PR after proving migration order against a scratch database. Do not combine renumbering with this CI guard.
6. Commit:
   ```bash
   git add scripts/check_migration_prefixes.py tests/unit/storage/test_migration_prefixes.py
   git commit -m "chore: guard migration prefix uniqueness"
   ```

### Task A4: Wire migration-prefix guard into CI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Steps:**
1. Add after guardrail greps:
   ```yaml
      - name: Migration prefix guard
        run: uv run python scripts/check_migration_prefixes.py
   ```
2. Run:
   ```bash
   uv run python scripts/check_migration_prefixes.py
   ```
3. Commit:
   ```bash
   git add .github/workflows/ci.yml
   git commit -m "ci: check migration prefix collisions"
   ```

---

## PR B: Frontend CI and Lint Baseline

### Task B1a: Fix render-time purity errors

**Files:**
- Modify: `web/app/scanner/page.tsx`
- Modify: `web/components/scanner/CandidateCard.tsx`
- Modify: `web/components/scanner/DiscoveredCard.tsx`
- Modify: `web/components/regime/GexSubTab.tsx`

**Steps:**
1. Capture baseline:
   ```bash
   cd web && npm run lint
   ```
   Expected before fix: current React lint errors.
2. Fix purity errors by passing render-time anchors from server/client parents instead of calling `Date.now()` during render.
3. Run:
   ```bash
   cd web && npm run lint
   cd web && npm run typecheck
   ```
4. Commit:
   ```bash
   git add web/app/scanner/page.tsx web/components/scanner web/components/regime/GexSubTab.tsx
   git commit -m "fix: remove render-time date reads"
   ```

### Task B1b: Fix conditional hook order

**Files:**
- Modify: `web/components/regime/CriSubTab.tsx`

**Steps:**
1. Fix conditional hook order in `CriSubTab.tsx` by moving `useMemo` above early returns or removing the no-op memo.
2. Run:
   ```bash
   cd web && npm run lint
   cd web && npm run test -- regime
   cd web && npm run typecheck
   ```
3. Commit:
   ```bash
   git add web/components/regime/CriSubTab.tsx
   git commit -m "fix: keep regime hooks unconditional"
   ```

### Task B1c: Fix synchronous state-reset effects

**Files:**
- Modify: `web/components/stock/panels/GexHistoryChart.tsx`
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`
- Modify: `web/components/stock/tabs/VolatilityTabClient.tsx`

**Steps:**
1. Fix synchronous set-state-in-effect warnings by deriving initial state from props or moving reset semantics into state keyed by ticker/provider.
2. Remove unused `anyPending` from `TradeInsightsAiAnalysisPanel.tsx`.
3. Run:
   ```bash
   cd web && npm run lint
   cd web && npm run typecheck
   cd web && npm run test
   ```
   Expected: all pass.
4. Commit:
   ```bash
   git add web
   git commit -m "fix: clear frontend state-effect lint"
   ```

### Task B1d: Decide warnings baseline

**Files:**
- Modify only files that still produce warnings after B1a-B1c.

**Steps:**
1. Re-run:
   ```bash
   cd web && npm run lint
   ```
2. If warnings remain but do not fail CI, either fix them in a small follow-up commit or document why they are intentionally deferred.
3. Do not enable a stricter warning gate until the warning count is zero.

### Task B2: Add frontend checks to GitHub Actions

**Files:**
- Modify: `.github/workflows/ci.yml`

**Steps:**
1. Add a separate `web` job with explicit Node setup and npm cache:
   ```yaml
   web:
     name: web typecheck + test + lint + build
     runs-on: ubuntu-latest
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-node@v4
         with:
           node-version: "22"
           cache: npm
           cache-dependency-path: web/package-lock.json
   ```
   Node must be pinned because `web/package-lock.json` shows Next requires Node `>=20.9.0` and the repo has no `.nvmrc` or `.node-version`.
2. Commands:
   ```bash
   cd web
   npm ci
   npm run typecheck
   npm run test
   npm run lint
   npm run build
   ```
3. If `npm run build` requires unavailable live services, document the exact blocker in the PR and add a separate required build job once the blocker is removed. Do not silently omit build.
4. Open a PR and verify GitHub Actions runs both backend and web jobs.
5. Commit:
   ```bash
   git add .github/workflows/ci.yml
   git commit -m "ci: add frontend checks"
   ```

---

## PR C: Documentation Accuracy

### Task C1: Update stale repository doctrine

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `src/uw_scan/storage/CLAUDE.md` if needed

**Steps:**
1. Replace stale language saying `repository.py` is 4,900+ lines with current language:
   - `repository.py` is an aggregate shim.
   - new query methods go into domain mixins or standalone repositories.
   - helper/dataclass re-exports exist for compatibility only.
2. Keep the historical lesson in the module-size budget section.
3. Run:
   ```bash
   rg -n "4,900|5000|legacy mono-module|models.py" CLAUDE.md AGENTS.md src/uw_scan/CLAUDE.md docs/plans docs/reviews
   ```
4. Update only current docs. Do not rewrite archived docs unless intentionally moving them to archive.
5. Commit:
   ```bash
   git add CLAUDE.md AGENTS.md src/uw_scan/storage/CLAUDE.md
   git commit -m "docs: refresh repository architecture guidance"
   ```

### Task C2: Triage untracked review docs

**Files:**
- Decide whether to keep, archive, or delete:
  - `docs/plans/2026-05-19-models-contract-split.md`
  - `docs/reviews/2026-05-16-web-code-review.md`
  - `docs/reviews/2026-05-18-backend-modularization-and-reuse.md`
  - `docs/reviews/2026-05-19-codebase-modularization-and-refactor-review.md`
  - `docs/reviews/2026-05-23-trade-insights-ai-v5-prompts-and-results.md`
  - `docs/reviews/2026-05-23-trade-insights-ai-v5.1-prompts-and-results.md`
  - `docs/reviews/2026-05-23-trade-insights-ai-v5.2-prompts-and-results.md`

**Steps:**
1. For stale docs, either update their header with `Status: superseded` or move them under `docs/reviews/archive/`.
2. For Trade Insights AI prompt/result docs, update references to current v5.3 status or archive older versions.
3. Commit only intentionally retained docs.
4. Verify:
   ```bash
   git status --short
   ```

---

## PR D: Persistence Batching

### Task D1: Batch option storage writers

**Files:**
- Modify: `src/uw_scan/storage/options.py`
- Test: existing storage tests; add focused tests only if param builders are introduced.

**Candidate methods:**
- `insert_interpolated_iv_rows`
- `upsert_oi_per_strike_rows`
- `upsert_options_volume_daily`
- `upsert_option_chain_per_strike`
- `insert_oi_change_rows`
- `insert_max_pain_rows`
- `insert_dark_pool_rows`

**Steps:**
1. Pick one method at a time.
2. Add or locate a regression test for insert count and persisted row values.
3. Preserve the method's current return-count semantics. Most methods return attempted input rows, not affected database row count; do not switch to cursor rowcount as part of batching.
4. Extract a `_params` helper when tuple construction is long.
5. Replace `for r in rows: cur.execute(...)` with `cur.executemany(sql, params)`.
6. Use existing `tests/unit/storage/test_batch_write_params.py` for param-builder and `executemany` assertions, and add new assertions there only for newly converted methods.
7. Run focused tests:
   ```bash
   uv run pytest tests/unit/storage/test_batch_write_params.py -q
   uv run pytest tests/integration/storage/ -q
   ```
8. Run benchmark if a live scratch DB is acceptable:
   ```bash
   uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 1000
   ```
9. Commit:
   ```bash
   git add src/uw_scan/storage/options.py tests
   git commit -m "perf: batch option storage writes"
   ```

### Task D2: Batch scanner and trade-insights candidate writes

**Files:**
- Modify: `src/uw_scan/storage/scan_results.py`
- Modify: `src/uw_scan/storage/trade_insights_ai.py`

**Steps:**
1. Add focused regression tests for row replacement/upsert behavior.
2. Convert safe insert loops to `executemany`.
3. Preserve delete-then-insert transaction boundaries for candidate replacement.
4. Run:
   ```bash
   uv run pytest tests/integration/storage/test_repository_trade_insights_ai.py -q
   uv run pytest tests/integration/storage/ -q
   ```
5. Commit:
   ```bash
   git add src/uw_scan/storage/scan_results.py src/uw_scan/storage/trade_insights_ai.py tests
   git commit -m "perf: batch scanner and trade insight persistence"
   ```

---

## PR E0: Trade Insights AI Prompt Metadata Contract

### Task E0.1: Remove hard-coded prompt-version copy from UI

**Files:**
- Modify backend response model if needed.
- Modify API latest response.
- Regenerate: `web/lib/types.ts`
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`

**Steps:**
1. Add `current_prompt_version` and optional `current_prompt_label` to the API response.
2. Add backend model tests and OpenAPI snapshot verification.
3. Run:
   ```bash
   uv run pytest tests/test_trade_insights_ai.py tests/integration/api/test_trade_insights_ai_endpoint.py tests/integration/api/test_openapi_snapshot.py -q
   ```
4. Start API and regenerate frontend types:
   ```bash
   cd web && npm run gen:types
   ```
5. Update UI to consume the API field.
6. Run:
   ```bash
   cd web && npm run typecheck && npm run test
   ```
7. Commit:
   ```bash
   git add src web tests
   git commit -m "refactor: expose trade insights ai prompt metadata"
   ```

**Abort criteria:**
- If adding prompt metadata changes existing analysis payload semantics or persisted row shape, stop and split the persistence/API work into its own contract PR.
- If `web/lib/types.ts` changes beyond the intended response model, inspect the OpenAPI diff before continuing.

---

## PR E: Trade Insights AI UI Split

### Task E1: Extract polling hook

**Files:**
- Create: `web/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling.ts`
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`
- Test: `web/tests/unit/tradeInsightsAiAnalysisPanel.test.tsx`

**Steps:**
1. Write hook tests for:
   - initial latest fetch
   - run request
   - one provider pending while the other can run
   - 503 unavailable state
2. Move state and polling functions into the hook.
3. Keep exported component behavior unchanged.
4. Run:
   ```bash
   cd web && npm run test -- tradeInsightsAiAnalysisPanel
   cd web && npm run typecheck
   ```
5. Commit:
   ```bash
   git add web/components/stock/panels web/tests
   git commit -m "refactor: extract trade insights ai polling hook"
   ```

### Task E2: Extract presentational components

**Files:**
- Create: `web/components/stock/panels/tradeInsightsAi/ProviderTabBar.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/ConsensusBreakdown.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/TriggerEvidenceCard.tsx`
- Create: `web/components/stock/panels/tradeInsightsAi/LegsTable.tsx`
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`

**Steps:**
1. Extract one component at a time.
2. Keep props typed from `TradeInsightsAiAnalysisResponse`.
3. Do not change text or layout in this PR.
4. Run after each extraction:
   ```bash
   cd web && npm run test -- tradeInsightsAiAnalysisPanel
   cd web && npm run typecheck
   ```
5. Commit:
   ```bash
   git add web/components/stock/panels
   git commit -m "refactor: split trade insights ai panel components"
   ```

**Abort criteria:**
- Do not change API response shape, persisted analysis fields, prompt schema, or visible copy in PR E.
- If a component extraction requires broad prop drilling, extract a typed view model helper first and keep the rendering diff small.

---

## PR F: Trade Insights AI Backend Split

### Task F1: Split lenient coercion by responsibility

**Files:**
- Create package: `src/uw_scan/reports/trade_insights_ai/leniency/`
- Move helpers from: `src/uw_scan/reports/trade_insights_ai_lenient.py`
- Preserve import: existing callers of `_coerce_claude_outcome_dict`

**Target modules:**
- `identity.py`
- `vocabulary.py`
- `candidates.py`
- `normalization.py`
- `__init__.py`

**Steps:**
1. Add characterization tests around current Claude coercion cases.
2. Move pure helpers first without changing behavior.
3. Keep `trade_insights_ai_lenient.py` as a compatibility wrapper initially.
4. Run:
   ```bash
   uv run pytest tests/test_trade_insights_ai.py tests/unit/worker/test_trade_insights_claude_runner.py -q
   uv run ruff check src/uw_scan/reports/
   ```
5. Commit:
   ```bash
   git add src/uw_scan/reports tests
   git commit -m "refactor: split trade insights ai leniency helpers"
   ```

### Task F2: Split hard validators by contract layer

**Files:**
- Create package: `src/uw_scan/reports/trade_insights_ai/validator_rules/`
- Keep compatibility module: `src/uw_scan/reports/trade_insights_ai/validators.py`
- Preserve public import: `validate_trade_insights_ai_outcome`

**Target modules:**
- `validator_rules/identity.py`
- `validator_rules/structure.py`
- `validator_rules/triggers.py`
- `validator_rules/sources.py`
- `validator_rules/imperative.py`
- `validator_rules/__init__.py`

**Steps:**
1. Add tests that call the public validator entry point from `uw_scan.reports.trade_insights_ai`, not private helpers.
2. Move validator groups one at a time from `validators.py` into `validator_rules/`.
3. Keep `validators.py` as the import-compatible orchestrator. Do not create `src/uw_scan/reports/trade_insights_ai/validators/` unless `validators.py` is removed in the same commit and all imports are updated.
4. Keep error messages stable unless a test explicitly updates them.
5. Run:
   ```bash
   uv run pytest tests/test_trade_insights_ai.py -q
   uv run pytest tests/integration/worker/test_trade_insights_ai_jobs.py -q
   uv run ruff check src/uw_scan/reports/
   ```
6. Commit:
   ```bash
   git add src/uw_scan/reports tests
   git commit -m "refactor: split trade insights ai validators"
   ```

---

## PR G: Rates and Regime UI Size Reduction

### Task G1: Split `RatesDesk.tsx` by section

**Files:**
- Create: `web/components/rates/sections/SummarySection.tsx`
- Create: `web/components/rates/sections/PolicySection.tsx`
- Create: `web/components/rates/sections/SupplySection.tsx`
- Create: `web/components/rates/sections/PositioningSection.tsx`
- Create: `web/components/rates/sections/DecompositionSection.tsx`
- Create: `web/components/rates/sections/CrossMarketSection.tsx`
- Create: `web/components/rates/sections/EventsSection.tsx`
- Create: `web/components/rates/sections/SourceFreshnessSection.tsx`
- Create: `web/components/rates/sections/SynthesisSection.tsx`
- Create: `web/components/rates/sourceHelpers.ts`
- Modify: `web/components/rates/RatesDesk.tsx`

**Steps:**
1. Move one section at a time.
2. Move source/publisher/link helpers into `sourceHelpers.ts` only after the section using them is extracted.
3. Keep CSS module class names and layout unchanged.
4. Run after each move:
   ```bash
   cd web && npm run test -- rates
   cd web && npm run typecheck
   ```
5. If the first pass only extracts the five largest sections, lower the PR success criterion to "RatesDesk reduced meaningfully without layout change" and create a follow-up issue for the remaining sections instead of claiming the full file is split.
6. Commit:
   ```bash
   git add web/components/rates
   git commit -m "refactor: split rates desk sections"
   ```

### Task G2: Extract regime shared primitives

**Files:**
- Create: `web/components/regime/primitives/`
- Modify:
  - `web/components/regime/GexSubTab.tsx`
  - `web/components/regime/VcgSubTab.tsx`
  - `web/components/regime/CriSubTab.tsx`

**Steps:**
1. Identify duplicated tile/card/chart patterns.
2. Extract one primitive at a time.
3. Keep visual output unchanged.
4. Run:
   ```bash
   cd web && npm run typecheck
   cd web && npm run test
   cd web && npm run lint
   ```
5. Commit:
   ```bash
   git add web/components/regime
   git commit -m "refactor: extract regime ui primitives"
   ```

---

## Explicitly Deferred Work

- **Repository import cleanup:** Do not combine `from uw_scan.storage.repository import ...` migration with PR A-G. `Repository` itself remains an intentional aggregate construction surface; only helper/dataclass compatibility imports should move to domain modules in a later mechanical PR.
- **Migration renumbering:** The guard in PR A prevents new duplicate prefixes. Renumbering existing migration files is deferred until a dedicated migration-history PR verifies lexical apply order against a scratch database.
- **Frontend warning-as-error:** Add CI lint first after the baseline passes. Only enable warning-as-error once warnings are at zero and local `npm run lint` confirms the stricter gate.

---

## Final Verification Before Each PR

Run the relevant narrow tests plus:

```bash
git diff --check
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run pytest tests/unit/ -q
cd web && npm run typecheck
cd web && npm run test
cd web && npm run lint
```

For backend API/model changes also run:

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
cd web && npm run gen:types
git diff -- web/lib/types.ts
```

For persistence/migration changes also run:

```bash
UW_SCAN_DB_NAME=option_wizard_test bash scripts/migrate.sh
uv run pytest tests/integration/storage/ -q
```

## Success Criteria

- Current untracked artifact risks are gone or ignored.
- CI runs backend and frontend gates.
- `npm run lint` passes.
- Duplicate migration prefixes cannot recur silently.
- `TradeInsightsAiAnalysisPanel.tsx` is reduced below 500 lines.
- `trade_insights_ai_lenient.py` and `validators.py` are reduced below 500 lines each or become compatibility wrappers below 150 lines.
- Highest-volume storage write paths use `executemany`.
- No API contract drift without regenerated `web/lib/types.ts`.
