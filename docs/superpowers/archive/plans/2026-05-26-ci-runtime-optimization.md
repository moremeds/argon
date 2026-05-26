# CI Runtime Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce GitHub CI wall-clock time without removing or weakening required lint, unit, integration, typecheck, lint, test, or build coverage.

**Architecture:** Keep the existing required Python check name as a stable aggregate gate, but split the work underneath into fast static/unit feedback and sharded integration checks. Preserve the full `tests/integration/` suite by running every integration test across isolated matrix jobs, each with its own Postgres service. Add workflow-level concurrency so obsolete PR runs are canceled when a newer commit supersedes them.

**Tech Stack:** GitHub Actions, `uv`, pytest, Postgres service containers, Next.js 16, Node 22, npm, Vitest, ESLint.

---

## Current Baseline

The current workflow is `.github/workflows/ci.yml`.

Recent successful runs show:

- `web typecheck + test + lint + build`: about 1m15s to 1m24s.
- Python setup, guardrails, and unit tests: under 1 minute after Postgres starts.
- `Integration tests (no live API)`: about 20m to 24m.

Therefore, the wall-clock bottleneck is the single serial `uv run pytest tests/integration/ -v` step.

## Quality Constraints

- Do not remove any existing checks.
- Do not skip Python integration tests based on paths in the first version.
- Do not skip web checks based on paths in the first version.
- Keep live API tests excluded by current behavior: no `UW_SCAN_API_KEY` in CI.
- Keep Postgres-backed integration tests running against disposable CI Postgres, not fakes.
- Keep the existing required Python check name `lint + unit + integration` stable by adding an aggregate gate that depends on the split Python jobs.
- Respect repo policy: do not commit unless the user explicitly asks for commits.

## Expected Outcome

- PRs should still run all current quality gates.
- Obsolete PR runs should auto-cancel; push runs on `main`/`master` should not be canceled by this workflow change.
- Fast failures should appear earlier.
- Full CI should drop from roughly 21-25 minutes to roughly 6-10 minutes if the integration suite balances reasonably across 4 shards.

---

### Task 1: Add Workflow Concurrency

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Add PR-safe concurrency near the top of the workflow**

Add this after `permissions`:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

**Step 2: Validate behavior expectation**

Expected behavior:

- A newer push to the same PR cancels older in-progress runs for that PR.
- Push runs on `main`/`master` are not canceled by this setting.
- The latest commit still receives the full CI suite.

**Step 3: Verify YAML parses**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml"); puts "ok"'
```

Expected:

```text
ok
```

Note: this only proves the file is syntactically valid YAML. GitHub Actions expression and job-graph validation happens in the local verification task with `actionlint` and finally in the PR workflow run.

---

### Task 2: Enable Explicit uv Cache

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Update the existing `Install uv` step**

Change:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v3
  with:
    version: "latest"
```

To:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v3
  with:
    version: "latest"
    enable-cache: true
    cache-dependency-glob: uv.lock
```

**Step 2: Keep dependency sync unchanged**

Leave this command unchanged:

```yaml
- name: Sync deps
  run: uv sync --extra postgres
```

Reason: this preserves the current dependency surface and keeps `uv.lock` authoritative.

**Step 3: Verify YAML parses**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml"); puts "ok"'
```

Expected:

```text
ok
```

Note: this only proves the file is syntactically valid YAML. GitHub Actions expression and job-graph validation happens in the local verification task with `actionlint` and finally in the PR workflow run.

---

### Task 3: Split Python Static/Unit Checks From Integration Checks

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Split the current Python job into a static/unit implementation job**

Change:

```yaml
jobs:
  test:
    name: lint + unit + integration
```

To:

```yaml
jobs:
  python-static-unit:
    name: lint + unit
```

The old required check name `lint + unit + integration` will be preserved later by an aggregate job. Do not use that name for `python-static-unit`.

**Step 2: Remove Postgres service from the static/unit job only if unit tests do not need it**

Before editing the workflow, run locally:

```bash
uv run pytest tests/unit/ -q
```

Expected:

```text
passed
```

If unit tests pass without Postgres, remove the `services.postgres` block and DB creation step from `python-static-unit`.

If unit tests fail because they depend on Postgres, keep the service in `python-static-unit` and document the dependency in a comment. Do not weaken the tests.

**Step 3: Keep all existing static checks in `python-static-unit`**

Preserve these steps:

```yaml
- name: Ruff
  run: uv run ruff check src/ tests/ scripts/

- name: AST except handler check (Guardrail 2)
  run: uv run python scripts/_lint_except.py src

- name: Guardrail greps (3, 5, 9)
  run: |
    set -e
    ! grep -rE 'class _Fake(Cursor|Connection)' tests/integration/ || (echo "Guardrail 5 violation: integration test uses fake cursor/connection"; exit 1)
    ! grep -rE '"\|".join\(' src/ || (echo "Guardrail 9 violation"; exit 1)
    ! grep -rE 'from tests' src/ || (echo "Guardrail 3 violation"; exit 1)
    ! grep -rE 'from uw_scan\.fixtures' src/ || (echo "Guardrail 3 violation"; exit 1)
    echo "guardrail greps clean"

- name: Migration prefix guard
  run: uv run python scripts/check_migration_prefixes.py

- name: Unit tests
  run: uv run pytest tests/unit/ -v
```

**Step 4: Verify local static/unit checks**

Run:

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -q
```

Expected:

```text
All commands pass
```

---

### Task 4: Add a Sharded Python Integration Job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Add a new job after `python-static-unit`**

Add:

```yaml
  python-integration:
    name: integration (${{ matrix.shard }}/${{ matrix.total-shards }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
        total-shards: [4]
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      UW_SCAN_DB_HOST: 127.0.0.1
      UW_SCAN_DB_PORT: 5432
      UW_SCAN_DB_NAME: option_wizard
      UW_SCAN_DB_SCHEMA: uw_scan
      UW_SCAN_DB_USER: postgres
      UW_SCAN_DB_PASSWORD: postgres
      UW_SCAN_TEST_DB_NAME: option_wizard_test
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
          enable-cache: true
          cache-dependency-glob: uv.lock

      - name: Sync deps
        run: uv sync --extra postgres

      - name: Create option_wizard + option_wizard_test DBs
        run: |
          PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE option_wizard"
          PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE option_wizard_test"

      - name: Verify integration shard candidates match pytest collection
        shell: bash
        run: |
          set -euo pipefail
          uv run pytest --collect-only -q tests/integration/ \
            | grep '^tests/' \
            | sed 's/::.*//' \
            | sort -u > /tmp/pytest-collected-files.txt
          find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) \
            | sort > /tmp/shard-candidate-files.txt
          diff -u /tmp/pytest-collected-files.txt /tmp/shard-candidate-files.txt

      - name: Select integration shard
        id: shard
        shell: bash
        run: |
          set -euo pipefail
          mapfile -t files < <(find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) | sort)
          selected=()
          for i in "${!files[@]}"; do
            if (( i % ${{ matrix.total-shards }} == ${{ matrix.shard }} - 1 )); then
              selected+=("${files[$i]}")
            fi
          done

          if (( ${#selected[@]} == 0 )); then
            echo "No tests selected for shard ${{ matrix.shard }}"
            exit 1
          fi

          printf '%s\n' "${selected[@]}" > /tmp/integration-shard.txt
          {
            echo 'files<<EOF'
            printf '%s\n' "${selected[@]}"
            echo 'EOF'
          } >> "$GITHUB_OUTPUT"

      - name: Integration tests (no live API)
        shell: bash
        run: |
          set -euo pipefail
          mapfile -t shard_files < /tmp/integration-shard.txt
          uv run pytest "${shard_files[@]}" -v
```

**Step 2: Confirm every file maps to exactly one shard locally**

Run:

```bash
set -euo pipefail
for shard in 1 2 3 4; do
  find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) | sort | awk -v shard="$shard" -v total=4 'NR % total == shard % total { print }' > "/tmp/uw-ci-shard-$shard.txt"
done
cat /tmp/uw-ci-shard-*.txt | sort > /tmp/uw-ci-all-sharded.txt
find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) | sort > /tmp/uw-ci-all-tests.txt
diff -u /tmp/uw-ci-all-tests.txt /tmp/uw-ci-all-sharded.txt
```

Expected:

```text
No diff output
```

**Step 3: Confirm pytest collection is equivalent**

Run:

```bash
set -euo pipefail
uv run pytest --collect-only -q tests/integration/ | grep '^tests/' | sort > /tmp/uw-ci-collected-all.txt
: > /tmp/uw-ci-collected-sharded.txt
for shard in 1 2 3 4; do
  uv run pytest --collect-only -q $(cat "/tmp/uw-ci-shard-$shard.txt") | grep '^tests/' >> /tmp/uw-ci-collected-sharded.txt
done
sort /tmp/uw-ci-collected-sharded.txt > /tmp/uw-ci-collected-sharded-sorted.txt
diff -u /tmp/uw-ci-collected-all.txt /tmp/uw-ci-collected-sharded-sorted.txt
```

Expected:

```text
No diff output
```

Reason: file coverage alone is not enough. This proves the sharded file lists collect the same pytest node IDs as `uv run pytest tests/integration/`.

**Step 4: Check for obvious shard imbalance**

Run:

```bash
wc -l /tmp/uw-ci-shard-*.txt
```

Expected:

```text
Each shard has a similar number of files
```

If one shard is clearly overloaded after the first GitHub run, replace modulo file sharding with explicit bucket lists based on observed job duration. Do that in a follow-up PR, not before measuring.

---

### Task 5: Add a Stable Aggregate Python Gate

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Add an aggregate job after `python-integration`**

Add:

```yaml
  python:
    name: lint + unit + integration
    runs-on: ubuntu-latest
    needs:
      - python-static-unit
      - python-integration
    if: ${{ always() }}
    steps:
      - name: Check Python quality gates
        run: |
          if [ "${{ needs.python-static-unit.result }}" != "success" ]; then
            echo "python-static-unit failed: ${{ needs.python-static-unit.result }}"
            exit 1
          fi
          if [ "${{ needs.python-integration.result }}" != "success" ]; then
            echo "python-integration failed: ${{ needs.python-integration.result }}"
            exit 1
          fi
          echo "Python lint, unit, and integration gates passed"
```

**Step 2: Preserve branch-protection compatibility**

Expected behavior:

- Existing required check context `lint + unit + integration` still appears.
- The aggregate gate fails if any static/unit job or any integration shard fails.
- The aggregate gate is cheap and does not rerun tests.

---

### Task 6: Keep the Web Job Semantically Unchanged

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Preserve current web check commands**

Keep:

```yaml
- name: Typecheck
  working-directory: web
  run: npm run typecheck

- name: Unit tests
  working-directory: web
  run: npm run test

- name: Lint
  working-directory: web
  run: npm run lint

- name: Build
  working-directory: web
  run: npm run build
```

**Step 2: Do not add path filtering yet**

Reason: this repository has API-generated types and shared product surfaces. Skipping web or Python checks based on file paths can lower merge confidence. Revisit after the sharded workflow has stable timing data.

---

### Task 7: Branch Protection / Required Checks Review

**Files:**
- No source files.
- GitHub repository settings may need update after PR lands.

**Step 1: Inspect current required checks**

Run:

```bash
gh api repos/moremeds/unusual-whales/branches/main/protection/required_status_checks --jq .
```

Expected:

```text
Current required status check contexts are printed, or GitHub reports branch protection is not configured
```

**Step 2: Confirm the old Python required check remains satisfied**

Required Python check:

```text
lint + unit + integration
```

Implementation detail checks:

```text
lint + unit
integration (1/4)
integration (2/4)
integration (3/4)
integration (4/4)
```

Branch protection should not need to require the implementation detail checks. It may continue requiring:

```text
lint + unit + integration
web typecheck + test + lint + build
```

Do not merge the workflow PR until the PR status panel confirms the aggregate `lint + unit + integration` check reports success after all split Python work completes. If required checks are managed through GitHub UI rather than API, record that in the PR body.

---

### Task 8: Local Verification Before PR

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Confirm only intended file changes**

Run:

```bash
git diff -- .github/workflows/ci.yml
git status --short
```

Expected:

```text
Only .github/workflows/ci.yml is part of this CI optimization change, unless this plan file is intentionally included too
```

Note: this worktree currently had unrelated local changes before this plan was written. Do not stage or modify unrelated files.

**Step 2: Validate YAML syntax**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml"); puts "ok"'
```

Expected:

```text
ok
```

**Step 3: Validate GitHub Actions semantics**

Run:

```bash
if command -v actionlint >/dev/null; then
  actionlint .github/workflows/ci.yml
else
  echo "actionlint not installed; install with 'brew install actionlint' for local Actions validation"
  exit 1
fi
```

Expected:

```text
No output and exit code 0
```

Reason: Ruby YAML parsing does not validate GitHub Actions expressions, matrix expansion, action inputs, or job graph semantics. If `actionlint` is not available locally, install it before treating local verification as complete. The PR workflow run remains the final semantic validation.

**Step 4: Verify Python static/unit lane locally**

Run:

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -q
```

Expected:

```text
All commands pass
```

**Step 5: Verify shard selection covers all integration files**

Run:

```bash
set -euo pipefail
for shard in 1 2 3 4; do
  find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) | sort | awk -v shard="$shard" -v total=4 'NR % total == shard % total { print }' > "/tmp/uw-ci-shard-$shard.txt"
done
cat /tmp/uw-ci-shard-*.txt | sort > /tmp/uw-ci-all-sharded.txt
find tests/integration -type f \( -name 'test_*.py' -o -name '*_test.py' \) | sort > /tmp/uw-ci-all-tests.txt
diff -u /tmp/uw-ci-all-tests.txt /tmp/uw-ci-all-sharded.txt
```

Expected:

```text
No diff output
```

**Step 6: Verify shard selection preserves pytest collection**

Run:

```bash
set -euo pipefail
uv run pytest --collect-only -q tests/integration/ | grep '^tests/' | sort > /tmp/uw-ci-collected-all.txt
: > /tmp/uw-ci-collected-sharded.txt
for shard in 1 2 3 4; do
  uv run pytest --collect-only -q $(cat "/tmp/uw-ci-shard-$shard.txt") | grep '^tests/' >> /tmp/uw-ci-collected-sharded.txt
done
sort /tmp/uw-ci-collected-sharded.txt > /tmp/uw-ci-collected-sharded-sorted.txt
diff -u /tmp/uw-ci-collected-all.txt /tmp/uw-ci-collected-sharded-sorted.txt
```

Expected:

```text
No diff output
```

---

### Task 9: GitHub Verification After PR

**Files:**
- No source files.

**Step 1: Push branch and open PR only after explicit user approval**

Use a branch name like:

```text
chore/ci-runtime-optimization
```

Do not push directly to `main` or `master`.

**Step 2: Watch the workflow**

Run:

```bash
gh run list --workflow ci.yml --branch chore/ci-runtime-optimization --limit 3
```

Then inspect the latest run:

```bash
gh run view <run-id> --json jobs,conclusion,status,url
```

Expected:

```text
lint + unit: success
integration (1/4): success
integration (2/4): success
integration (3/4): success
integration (4/4): success
lint + unit + integration: success
web typecheck + test + lint + build: success
```

**Step 3: Record timing evidence in PR**

Add a PR comment with:

```text
Before:
- Full CI wall time: ~21-25 minutes
- Integration step: ~20-24 minutes

After:
- Full CI wall time: <actual latest run duration>
- Slowest integration shard: <actual slowest shard duration>
- All previous checks preserved: yes
```

**Step 4: If one shard is much slower**

If one integration shard is more than 2x slower than another:

1. Inspect job durations by shard.
2. Move to an explicit bucket list in `.github/workflows/ci.yml`.
3. Keep all pytest-discovered `tests/integration/**/test_*.py` and `tests/integration/**/*_test.py` files covered exactly once.
4. Rerun CI.

---

### Task 10: Rollback Plan

**Files:**
- Modify: `.github/workflows/ci.yml`

If sharding introduces CI instability:

1. Keep `concurrency` and `uv` cache if they worked.
2. Revert only the Python job split and sharded integration job.
3. Restore the original single Python job:

```yaml
test:
  name: lint + unit + integration
```

4. Run the original command:

```yaml
- name: Integration tests (no live API)
  run: uv run pytest tests/integration/ -v
```

5. Open a follow-up issue documenting the failing shard behavior before attempting a second sharding pass.

---

## Implementation Notes

- The first version intentionally avoids path-based skipping because that is the easiest way to reduce CI time while reducing confidence.
- Matrix sharding increases total runner minutes but reduces PR wall-clock time. That is the right tradeoff if developer wait time is the current pain.
- `fail-fast: false` is important because it shows all failing shards in one run.
- The aggregate `lint + unit + integration` job keeps required-check identity stable while allowing the implementation jobs to change.
- Each integration shard must create its own `option_wizard` and `option_wizard_test` databases inside its own service container.
- If GitHub hosted runner concurrency becomes a bottleneck, reduce shards from 4 to 3 before considering lower-quality checks.
