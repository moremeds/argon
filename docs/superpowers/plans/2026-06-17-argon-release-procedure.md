# Argon Release Procedure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give argon xenon's tag-driven release automation — merge → cut tag → `release.yml` verifies + publishes a GitHub Release → a launchd poller on the mini auto-runs the existing `macmini-prod.sh` — without adopting Docker.

**Architecture:** Pull-based, Watchtower-style. `release.yml` fires only on `v*` tag push: a `verify` job re-runs argon's full CI gates on the tagged commit, then a `publish` job cuts a GitHub Release from the matching `CHANGELOG` section (prerelease-aware). On the mini, `com.argon.deploy-poller` (launchd `StartInterval=120`) polls `gh api .../releases/latest`; when the latest *published, non-prerelease* Release tag differs from `logs/deployed_tag.txt`, it runs `macmini-prod.sh <tag>` under a non-blocking `lockf` lock. A prerequisite tree-cleanliness fix (untrack `next-env.d.ts`, switch deploy to `npm ci`) keeps the mini's tree clean so the poller's dirty-guard never trips.

**Tech Stack:** GitHub Actions, bash, launchd (plist), Python 3.13 (`tomllib`, stdlib), `gh` CLI, `/usr/bin/lockf`, pytest (subprocess-style tests).

**Design doc:** `docs/superpowers/specs/2026-06-17-argon-release-procedure-design.md`

**Conventions for this plan:**
- All Python invoked via `uv run python` (guarantees 3.13 + `tomllib`; honors "uv only").
- Tests shell out to the real scripts (argon runs these as scripts in CI, and `scripts/` is not an importable package) — this tests the actual CLI contract.
- Commits happen on the execution branch/worktree; the branch opens a PR (never a direct push to `main`).

---

## File Structure

**Create:**
- `VERSION` — single source of truth for the release version
- `CHANGELOG.md` — Keep-a-Changelog, `[Unreleased]` + `[0.1.0]` baseline
- `scripts/release/_lib.sh` — `bump_semver` + `extract_changelog_section`
- `scripts/release/version_sync_check.py` — asserts VERSION == pyproject == web/package.json
- `scripts/release/cut.sh` — two-phase release cutter (`prepare` → PR; `tag` → push tag)
- `.github/workflows/release.yml` — tag-triggered verify + publish
- `scripts/deploy/macmini-deploy-poller.sh` — the mini poller
- `config/templates/com.argon.deploy-poller.plist.template` — launchd agent
- `docs/runbooks/release.md` — operator runbook
- `tests/unit/test_release_version_sync.py` — version_sync_check tests
- `tests/unit/test_release_lib.py` — _lib.sh tests
- `tests/unit/api/test_app_version.py` — FastAPI version wiring test

**Modify:**
- `web/.gitignore` — add `next-env.d.ts`
- `web/next-env.d.ts` — `git rm --cached` (untrack; build regenerates it)
- `scripts/deploy/macmini-prod.sh` — `npm install` → `npm ci`; record deployed tag
- `scripts/deploy/macmini-deploy-branch.sh` — `npm install` → `npm ci`
- `scripts/deploy/macmini-bootstrap.sh` — render + load the poller plist
- `.github/workflows/ci.yml` — add `version_sync_check` step
- `src/uw_scan/api/server.py` — read `VERSION` into `FastAPI(version=...)`
- `CLAUDE.md` — Release procedure section + "Where to look first" rows
- `AGENTS.md` — keep in sync with CLAUDE.md policy
- `MEMORY.md` + a memory file — record the automated deploy path

---

## Task 1: Tree-cleanliness prerequisite (Component 0)

Without this, the poller's first deploy dies on the mini's self-dirtied tree.

**Files:**
- Modify: `web/.gitignore`
- Untrack: `web/next-env.d.ts`
- Modify: `scripts/deploy/macmini-prod.sh:53`
- Modify: `scripts/deploy/macmini-deploy-branch.sh:70`

- [ ] **Step 1: Add `next-env.d.ts` to `web/.gitignore`**

Append to `web/.gitignore` (after `*.tsbuildinfo`):

```
# Next.js generates this on every build; never commit it.
next-env.d.ts
```

- [ ] **Step 2: Untrack the generated file**

Run:
```bash
git rm --cached web/next-env.d.ts
```
Expected: `rm 'web/next-env.d.ts'` (file stays on disk; now ignored).

- [ ] **Step 3: Switch `macmini-prod.sh` to `npm ci`**

In `scripts/deploy/macmini-prod.sh`, line ~53, replace:
```bash
  (cd web && npm install --no-audit --no-fund --legacy-peer-deps)
```
with:
```bash
  # npm ci: reproducible install from the committed lock; never rewrites
  # package-lock.json (npm install does, which self-dirties the tree and
  # blocks the next deploy's dirty-guard). ci.yml already uses npm ci.
  (cd web && npm ci --no-audit --no-fund --legacy-peer-deps)
```

- [ ] **Step 4: Switch `macmini-deploy-branch.sh` to `npm ci`**

In `scripts/deploy/macmini-deploy-branch.sh`, line ~70, replace:
```bash
cd web && npm install --legacy-peer-deps --no-audit --no-fund && npm run build && cd .."
```
with:
```bash
cd web && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build && cd .."
```

- [ ] **Step 5: Verify**

Run:
```bash
git status --porcelain web/next-env.d.ts   # expect a 'D ' (staged delete of cached entry)
grep -n "npm ci" scripts/deploy/macmini-prod.sh scripts/deploy/macmini-deploy-branch.sh
bash -n scripts/deploy/macmini-prod.sh && bash -n scripts/deploy/macmini-deploy-branch.sh && echo "syntax OK"
```
Expected: both files show `npm ci`; syntax OK.

- [ ] **Step 6: Commit**

```bash
git add web/.gitignore scripts/deploy/macmini-prod.sh scripts/deploy/macmini-deploy-branch.sh
git rm --cached --ignore-unmatch web/next-env.d.ts
git commit -m "chore(deploy): untrack next-env.d.ts + use npm ci so the tree stays clean across deploys"
```

---

## Task 2: VERSION, CHANGELOG, and version_sync_check

**Files:**
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `scripts/release/version_sync_check.py`
- Test: `tests/unit/test_release_version_sync.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `VERSION`**

```
0.1.0
```
(single line, trailing newline)

- [ ] **Step 2: Create `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
```

- [ ] **Step 3: Write the failing test**

Create `tests/unit/test_release_version_sync.py`:

```python
"""Tests for scripts/release/version_sync_check.py (run as a CLI)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release" / "version_sync_check.py"


def _setup(root: Path, *, version="1.2.3", py="1.2.3", web="1.2.3") -> None:
    (root / "VERSION").write_text(version + "\n")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{py}"\n'
    )
    web_dir = root / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text(json.dumps({"name": "w", "version": web}))


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_all_match_passes(tmp_path):
    _setup(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "OK: 1.2.3" in r.stdout


def test_pyproject_mismatch_fails(tmp_path):
    _setup(tmp_path, py="9.9.9")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "pyproject.toml" in r.stderr


def test_web_package_mismatch_fails(tmp_path):
    _setup(tmp_path, web="0.0.1")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "web/package.json" in r.stderr
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_release_version_sync.py -v`
Expected: FAIL (script does not exist yet — non-zero exit / FileNotFound).

- [ ] **Step 5: Create `scripts/release/version_sync_check.py`**

```python
"""Fail if VERSION, pyproject [project].version, and web/package.json disagree.

VERSION is the source of truth. Argon has no root package.json (all Node deps
live under web/), so web/package.json is the only tracked Node package; it
versions in lockstep with the Python package.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def check(root: Path) -> list[tuple[str, str]]:
    """Return [(label, actual_version)] for every file that disagrees with VERSION."""
    version = (root / "VERSION").read_text().strip()
    mismatches: list[tuple[str, str]] = []

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    py_version = pyproject.get("project", {}).get("version", "")
    if py_version != version:
        mismatches.append(("pyproject.toml [project].version", py_version))

    web_pkg = root / "web" / "package.json"
    if web_pkg.exists():
        pkg_version = json.loads(web_pkg.read_text()).get("version", "")
        if pkg_version != version:
            mismatches.append(("web/package.json", pkg_version))

    return mismatches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", type=Path)
    args = ap.parse_args(argv)

    version = (args.root / "VERSION").read_text().strip()
    mismatches = check(args.root)
    if mismatches:
        for label, got in mismatches:
            print(
                f"version mismatch: VERSION={version!r} {label}={got!r}",
                file=sys.stderr,
            )
        return 1
    print(f"OK: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_release_version_sync.py -v`
Expected: 3 passed.

- [ ] **Step 7: Confirm the real repo is in sync**

Run: `uv run python scripts/release/version_sync_check.py`
Expected: `OK: 0.1.0` (VERSION, pyproject, and web/package.json are all `0.1.0`).

- [ ] **Step 8: Add the check to `ci.yml`**

In `.github/workflows/ci.yml`, in the `python-static-unit` job, immediately after the `Sync deps` step (line ~30-31), insert:

```yaml
      - name: Version sync check
        run: uv run python scripts/release/version_sync_check.py
```

- [ ] **Step 9: Commit**

```bash
git add VERSION CHANGELOG.md scripts/release/version_sync_check.py tests/unit/test_release_version_sync.py .github/workflows/ci.yml
git commit -m "feat(release): VERSION + CHANGELOG + version_sync_check, wired into CI"
```

---

## Task 3: scripts/release/_lib.sh

**Files:**
- Create: `scripts/release/_lib.sh`
- Test: `tests/unit/test_release_lib.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_release_lib.py`:

```python
"""Tests for scripts/release/_lib.sh helpers (sourced in bash)."""
from __future__ import annotations

import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scripts" / "release" / "_lib.sh"


def _bash(snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{LIB}"; {snippet}'],
        capture_output=True,
        text=True,
    )


def test_bump_patch():
    r = _bash("bump_semver 1.2.3 patch")
    assert r.stdout.strip() == "1.2.4", r.stderr


def test_bump_minor():
    r = _bash("bump_semver 1.2.3 minor")
    assert r.stdout.strip() == "1.3.0", r.stderr


def test_bump_major():
    r = _bash("bump_semver 1.2.3 major")
    assert r.stdout.strip() == "2.0.0", r.stderr


def test_extract_changelog_section(tmp_path):
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [1.2.0] — 2026-06-17\n\n"
        "### Added\n\n- Thing one\n- Thing two\n\n"
        "## [1.1.0] — 2026-06-01\n\n- old thing\n"
    )
    r = _bash(f'extract_changelog_section "{cl}" 1.2.0')
    assert "Thing one" in r.stdout
    assert "Thing two" in r.stdout
    assert "old thing" not in r.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_release_lib.py -v`
Expected: FAIL (`_lib.sh` does not exist — source error).

- [ ] **Step 3: Create `scripts/release/_lib.sh`** (ported verbatim from xenon — repo-agnostic)

```bash
# Reusable helpers for release scripts. Source, don't execute.

bump_semver() {
  local version="$1" kind="$2"
  local IFS=.
  read -r major minor patch <<<"$version"
  case "$kind" in
    patch) patch=$((patch + 1)) ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    major) major=$((major + 1)); minor=0; patch=0 ;;
    *) echo "unknown bump kind: $kind" >&2; return 1 ;;
  esac
  echo "${major}.${minor}.${patch}"
}

# extract_changelog_section <file> <version>
# Prints the body of `## [<version>] — …` up to (but not including) the next `## [` heading.
# Patterns anchored at line start (^## \[) so in-body text that happens to contain
# "## [" (e.g. inside a fenced code block) cannot terminate the section early.
extract_changelog_section() {
  local file="$1" version="$2"
  awk -v v="$version" '
    BEGIN { in_section = 0 }
    /^## \[/ {
      if (in_section) { exit }
      if ($0 ~ "^## \\[" v "\\]") { in_section = 1; next }
    }
    in_section { print }
  ' "$file" | sed -e '/./,$!d' | sed -e ':a' -e '/^$/{$d;N;ba' -e '}'
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_release_lib.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/release/_lib.sh tests/unit/test_release_lib.py
git commit -m "feat(release): _lib.sh (bump_semver + extract_changelog_section) with tests"
```

---

## Task 4: scripts/release/cut.sh (two-phase)

`prepare` opens a release PR (bump + CHANGELOG promotion); `tag` tags the merged
main commit and pushes the tag. Never pushes `main` (argon policy).

**Files:**
- Create: `scripts/release/cut.sh`

- [ ] **Step 1: Create `scripts/release/cut.sh`**

```bash
#!/usr/bin/env bash
# scripts/release/cut.sh — two-phase release cutter for argon.
#
#   cut.sh prepare [patch|minor|major]   # from main: open a release PR (bump + CHANGELOG)
#   cut.sh tag                           # from main, after the PR merged: tag v$VERSION + push the tag
#
# argon policy: `git push origin main` is forbidden. The version bump lands via a
# PR (prepare); the tag is cut from the already-merged, CI-green main commit (tag).
# The tag push is what fires .github/workflows/release.yml.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/release/_lib.sh
. "$ROOT/scripts/release/_lib.sh"

say()  { printf '\033[1;34m> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

cmd="${1:-}"
case "$cmd" in
  prepare|tag) ;;
  *) die "usage: cut.sh {prepare [patch|minor|major] | tag}" ;;
esac

[[ "$(git symbolic-ref --short HEAD)" == "main" ]] || die "not on main"
git diff --quiet && git diff --cached --quiet || die "working tree dirty"
git fetch origin main >/dev/null
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || die "local main not synced with origin/main"

if [[ "$cmd" == "prepare" ]]; then
  bump_kind="${2:-}"
  case "$bump_kind" in patch|minor|major) ;; *) die "usage: cut.sh prepare [patch|minor|major]" ;; esac

  grep -q '^## \[Unreleased\]' CHANGELOG.md || die "CHANGELOG missing [Unreleased]"
  unreleased_body="$(awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md | sed '/^$/d')"
  [[ -n "$unreleased_body" ]] || die "CHANGELOG [Unreleased] is empty — nothing to release"

  current="$(cat VERSION)"
  next="$(bump_semver "$current" "$bump_kind")"
  git rev-parse "v$next" >/dev/null 2>&1 && die "tag v$next already exists"
  today="$(date +%Y-%m-%d)"
  branch="release/v$next"

  say "Prepare $current -> $next on $branch"
  git switch -c "$branch"

  echo "$next" > VERSION

  # pyproject.toml [project].version (surgical single-line replace)
  uv run python - "$current" "$next" <<'PY'
import sys
current, nxt = sys.argv[1], sys.argv[2]
path = "pyproject.toml"
text = open(path).read()
old, new = f'version = "{current}"', f'version = "{nxt}"'
# Exactly one match expected — argon's pyproject has a single `version = "x"`
# (the [project] version). Failing loudly on ambiguity beats silently editing the
# wrong line.
assert text.count(old) == 1, f"{path}: expected exactly one {old!r}, found {text.count(old)}"
open(path, "w").write(text.replace(old, new))
PY

  # web/package.json version (surgical; keeps the dep-heavy file byte-stable)
  uv run python - "$current" "$next" <<'PY'
import sys
current, nxt = sys.argv[1], sys.argv[2]
path = "web/package.json"
text = open(path).read()
old, new = f'"version": "{current}"', f'"version": "{nxt}"'
assert text.count(old) == 1, f"{path}: expected one {old!r}, found {text.count(old)}"
open(path, "w").write(text.replace(old, new))
PY

  # CHANGELOG: move the [Unreleased] body under a new [next] — DATE heading.
  uv run python - "$next" "$today" <<'PY'
import re, sys
nxt, today = sys.argv[1], sys.argv[2]
path = "CHANGELOG.md"
text = open(path).read()
m = re.search(r"^(## \[Unreleased\]\s*?\n)(.*?)(?=^## \[|\Z)", text, flags=re.MULTILINE | re.DOTALL)
assert m, "CHANGELOG missing [Unreleased]"
body = m.group(2).rstrip() + "\n" if m.group(2).strip() else ""
new_section = f"## [Unreleased]\n\n## [{nxt}] — {today}\n\n{body}"
updated = text[:m.start()] + new_section + text[m.end():]
assert updated != text, "CHANGELOG rewrite produced no change"
open(path, "w").write(updated)
PY

  uv run python scripts/release/version_sync_check.py || die "version_sync_check failed after bump"

  git add VERSION pyproject.toml web/package.json CHANGELOG.md
  git commit -m "release: v$next"
  git push -u origin "$branch"
  gh pr create --base main --head "$branch" \
    --title "release: v$next" \
    --body "Release v$next. Merge after CI is green, then run \`scripts/release/cut.sh tag\` on main to publish."
  say "Release PR opened for v$next. Merge it (CI green), then run: scripts/release/cut.sh tag"
  exit 0
fi

# cmd == tag (run on main after the release PR merged)
uv run python scripts/release/version_sync_check.py || die "version_sync_check failed"
version="$(cat VERSION)"
git rev-parse "v$version" >/dev/null 2>&1 && die "tag v$version already exists"
grep -q "^## \[$version\]" CHANGELOG.md || die "CHANGELOG has no section for $version"

section="$(extract_changelog_section CHANGELOG.md "$version")"
say "Tagging v$version"
git tag -a "v$version" -m "v$version

$section"
git push origin "v$version"
say "Pushed tag v$version — release.yml verifies + publishes; the mini poller deploys after publish."
```

- [ ] **Step 2: Make executable + syntax check**

Run:
```bash
chmod +x scripts/release/cut.sh
bash -n scripts/release/cut.sh && echo "syntax OK"
scripts/release/cut.sh 2>&1 | head -1   # expect usage line
```
Expected: `syntax OK`; usage `FAIL: usage: cut.sh {prepare [patch|minor|major] | tag}`.

- [ ] **Step 3: Optional shellcheck (if installed)**

Run: `command -v shellcheck >/dev/null && shellcheck scripts/release/cut.sh scripts/release/_lib.sh || echo "shellcheck not installed — skip"`
Expected: no errors (warnings acceptable), or skip.

- [ ] **Step 4: Commit**

```bash
git add scripts/release/cut.sh
git commit -m "feat(release): cut.sh two-phase release cutter (prepare PR + tag)"
```

---

## Task 5: Wire VERSION into the FastAPI app

**Files:**
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/unit/api/test_app_version.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_app_version.py`:

```python
"""The FastAPI app reports the version from the root VERSION file."""
from __future__ import annotations

from pathlib import Path

from uw_scan.api.server import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_app_version_matches_version_file():
    expected = (REPO_ROOT / "VERSION").read_text().strip()
    app = create_app()
    assert app.version == expected
```

- [ ] **Step 2: Run the test (note: not strict red-first)**

Run: `uv run pytest tests/unit/api/test_app_version.py -v`
Expected: this test PASSES today even before the change, because the hardcoded
`version="0.1.0"` coincidentally equals VERSION's `0.1.0` — strict red-first
isn't achievable without bumping VERSION. Treat this as a **regression guard**,
not TDD: Step 3 makes it correct-by-construction (reads the file), so a future
`VERSION` bump can't silently leave the API reporting a stale version. Proceed to
Step 3 regardless of the green result here.

- [ ] **Step 3: Read VERSION in `server.py`**

In `src/uw_scan/api/server.py`, replace the top imports block (lines 1-6) — add `Path`:

```python
"""FastAPI app factory + ASGI entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
```

Then add a helper just above `def create_app()` (line ~28):

```python
def _app_version() -> str:
    """Read the release version from the repo-root VERSION file.

    server.py lives at src/uw_scan/api/server.py → repo root is parents[3].
    Falls back to a sentinel if the file is missing (e.g. an odd packaging).
    """
    try:
        return (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0+unknown"
```

And change the `FastAPI(...)` line (was line 29):

```python
    app = FastAPI(title="UW Watchlist API", version=_app_version())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/api/test_app_version.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/server.py tests/unit/api/test_app_version.py
git commit -m "feat(api): report release version from VERSION file in FastAPI app"
```

---

## Task 6: macmini-prod.sh — fix health path + record the deployed tag

Two changes to the script the poller drives: (a) **fix a latent health-check
bug** that would make every poller deploy roll back, and (b) record the deployed
tag so the poller has authoritative "what's live" state.

**Why (a) is load-bearing:** `macmini-prod.sh` health-checks
`http://127.0.0.1:8400/health`, which returns **404** — the health router is
mounted under `prefix="/api"`, so the real path is `/api/health` (verified 200
on the live mini 2026-06-17). The current mini deploy survives only because it
was last deployed via `macmini-deploy-branch.sh` (which probes `/api/health`).
The first poller-driven `macmini-prod.sh` deploy would 404 → fail health →
auto-rollback → poller marks the tag failed → the release never deploys. Fix the
path before wiring the poller.

**Files:**
- Modify: `scripts/deploy/macmini-prod.sh`

- [ ] **Step 1: Fix the health-check path (`/health` → `/api/health`)**

In `scripts/deploy/macmini-prod.sh`, fix both occurrences. Line ~87 (primary
check), replace:
```bash
if check_url "http://127.0.0.1:8400/health" "api" \
```
with:
```bash
if check_url "http://127.0.0.1:8400/api/health" "api" \
```
And line ~103 (rollback check), replace:
```bash
check_url "http://127.0.0.1:8400/health" "api(rollback)" || die "rollback ALSO failed — manual intervention required"
```
with:
```bash
check_url "http://127.0.0.1:8400/api/health" "api(rollback)" || die "rollback ALSO failed — manual intervention required"
```

- [ ] **Step 2: Assert the checkout's VERSION matches the tag**

In `scripts/deploy/macmini-prod.sh`, right after the checkout block (after
`COMMIT="$(git rev-parse --short HEAD)"` / `say "HEAD now $COMMIT"`, ~line 45,
before `build_release`), add a guard. `release.yml`'s verify enforces tag↔VERSION
in CI, but the poller and manual runs call this script directly — this is the
deploy-side complement so a mistagged invocation can't deploy and desync
`deployed_tag.txt`:

```bash
# The tag must match the checked-out VERSION (allow a -prerelease suffix, e.g.
# v0.1.0-rc1 on a VERSION=0.1.0 commit). Placed in the forward path only — the
# rollback path below checks out PREV_TAG (which may be a bare SHA) and must not
# trip this guard.
FILE_VERSION="$(cat VERSION)"
if [[ "$TAG" != "v$FILE_VERSION" && "$TAG" != "v$FILE_VERSION"-* ]]; then
  die "tag $TAG does not match checked-out VERSION (v$FILE_VERSION)"
fi
say "tag/VERSION OK: $TAG (v$FILE_VERSION)"
```

- [ ] **Step 3: Record the tag on successful deploy**

In `scripts/deploy/macmini-prod.sh`, in the success branch (the block after
`step "Deploy OK: $TAG ($COMMIT)"`, around lines 89-91), add a line that writes
the deployed tag. Replace:

```bash
  step "Deploy OK: $TAG ($COMMIT)"
  printf '%s  %s  %s  OK\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" >> "$REPO_ROOT/logs/deploy.log"
  exit 0
```

with:

```bash
  step "Deploy OK: $TAG ($COMMIT)"
  printf '%s  %s  %s  OK\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" >> "$REPO_ROOT/logs/deploy.log"
  # Authoritative "what's live" marker the deploy poller reads to decide whether
  # a newer release needs deploying. Only advanced on a *successful* deploy; a
  # rollback leaves it pointing at the last good release.
  printf '%s\n' "$TAG" > "$REPO_ROOT/logs/deployed_tag.txt"
  exit 0
```

- [ ] **Step 4: Verify**

Run:
```bash
bash -n scripts/deploy/macmini-prod.sh && echo "syntax OK"
grep -n "deployed_tag.txt\|/api/health\|tag/VERSION OK" scripts/deploy/macmini-prod.sh
```
Expected: syntax OK; one `deployed_tag.txt` match on the success path; both
health checks now use `/api/health` (two matches); the tag/VERSION guard present;
no bare `/health` remaining:
```bash
! grep -n '8400/health"' scripts/deploy/macmini-prod.sh && echo "no bare /health left"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy/macmini-prod.sh
git commit -m "fix(deploy): macmini-prod.sh health /health->/api/health, tag<->VERSION guard, record deployed_tag"
```

---

## Task 7: .github/workflows/release.yml

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  verify:
    name: verify (tagged commit)
    runs-on: ubuntu-latest
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
      UW_SCAN_DB_NAME: option_wizard_local
      UW_SCAN_DB_SCHEMA: uw_scan
      UW_SCAN_DB_USER: postgres
      UW_SCAN_DB_PASSWORD: postgres
      UW_SCAN_TEST_DB_NAME: option_wizard_test
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
          enable-cache: true
          cache-dependency-glob: uv.lock

      - name: Sync deps
        run: uv sync --extra postgres

      - name: Version sync check
        run: uv run python scripts/release/version_sync_check.py

      - name: Assert tag matches VERSION (allow prerelease suffix)
        # Catches a hand-pushed mistag (e.g. v0.5.0 on a VERSION=0.1.0 commit),
        # which would otherwise publish an empty-notes release and make the poller
        # deploy a tag whose checked-out VERSION disagrees. cut.sh tags v$(cat
        # VERSION) so the sanctioned path always matches; prerelease tags
        # (v0.1.0-rc1) are allowed as VERSION + "-<suffix>".
        run: |
          TAGVER="${GITHUB_REF_NAME#v}"
          FILEVER="$(cat VERSION)"
          if [[ "$TAGVER" != "$FILEVER" && "$TAGVER" != "$FILEVER"-* ]]; then
            echo "tag $GITHUB_REF_NAME does not match VERSION=$FILEVER (expected v$FILEVER or v$FILEVER-<pre>)" >&2
            exit 1
          fi
          echo "tag/VERSION OK: $GITHUB_REF_NAME vs $FILEVER"

      - name: Ruff
        run: uv run ruff check src/ tests/ scripts/

      - name: AST except handler check (Guardrail 2)
        run: uv run python scripts/_lint_except.py src

      - name: Guardrail greps (3, 5, 9)
        run: |
          set -e
          ! grep -rE 'class _Fake(Cursor|Connection)' tests/integration/ || (echo "Guardrail 5 violation"; exit 1)
          ! grep -rE '"\|".join\(' src/ || (echo "Guardrail 9 violation"; exit 1)
          ! grep -rE 'from tests' src/ || (echo "Guardrail 3 violation"; exit 1)
          ! grep -rE 'from uw_scan\.fixtures' src/ || (echo "Guardrail 3 violation"; exit 1)
          echo "guardrail greps clean"

      - name: Migration prefix guard
        run: uv run python scripts/check_migration_prefixes.py

      - name: Create option_wizard_local + option_wizard_test DBs
        run: |
          PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE option_wizard_local"
          PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE option_wizard_test"

      - name: Unit tests
        run: uv run pytest tests/unit/ -v

      - name: Integration tests (no live API)
        run: uv run pytest tests/integration/ -v

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json

      - name: Install web deps
        working-directory: web
        run: npm ci

      - name: Typecheck
        working-directory: web
        run: npm run typecheck

      - name: Web unit tests
        working-directory: web
        run: npm run test

      - name: Lint
        working-directory: web
        run: npm run lint

      - name: Build
        working-directory: web
        run: npm run build

  publish:
    name: publish GitHub Release
    needs: verify
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Extract CHANGELOG section
        id: changelog
        run: |
          # Strip any prerelease suffix (v0.1.0-rc1 -> 0.1.0) so a prerelease
          # release carries its base version's CHANGELOG notes rather than empty
          # notes (CHANGELOG headers track final versions only).
          RAW="${GITHUB_REF_NAME#v}"
          VERSION="${RAW%%-*}"
          source scripts/release/_lib.sh
          {
            echo 'body<<EOF'
            extract_changelog_section CHANGELOG.md "$VERSION"
            echo 'EOF'
          } >> "$GITHUB_OUTPUT"

      - name: Classify release
        id: rel
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          if [[ "$VERSION" == *-* ]]; then
            echo "prerelease=true" >> "$GITHUB_OUTPUT"
          else
            echo "prerelease=false" >> "$GITHUB_OUTPUT"
          fi

      - uses: softprops/action-gh-release@v3
        with:
          name: ${{ github.ref_name }}
          body: ${{ steps.changelog.outputs.body }}
          draft: false
          prerelease: ${{ steps.rel.outputs.prerelease }}
          make_latest: ${{ steps.rel.outputs.prerelease == 'false' }}
```

- [ ] **Step 2: Validate the YAML**

Run:
```bash
uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml OK')"
command -v actionlint >/dev/null && actionlint .github/workflows/release.yml || echo "actionlint not installed — skip"
```
Expected: `yaml OK`; actionlint clean or skipped.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(release): release.yml — tag-triggered verify + GitHub Release publish"
```

---

## Task 8: The mini deploy poller

**Files:**
- Create: `scripts/deploy/macmini-deploy-poller.sh`

- [ ] **Step 1: Create `scripts/deploy/macmini-deploy-poller.sh`**

```bash
#!/usr/bin/env bash
# macmini-deploy-poller.sh — RUN ON THE MAC MINI (launchd com.argon.deploy-poller).
#
# Pull-based deploy trigger — the launchd equivalent of xenon's Watchtower. Poll
# the latest *published, non-prerelease* GitHub Release; if its tag differs from
# what's deployed (logs/deployed_tag.txt), run macmini-prod.sh to deploy it.
#
# Gating on the Release (not the raw tag) means we only ever deploy a version
# that release.yml's verify job already proved green — the Release is created in
# the publish job, after verify passes. Prereleases are excluded by the API.
#
# Flags:
#   --dry-run    print the decision, deploy nothing
#   --once       single pass (default; launchd re-invokes on StartInterval)

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

REPO="moremeds/argon"
DEPLOYED_FILE="$REPO_ROOT/logs/deployed_tag.txt"
FAILED_FILE="$REPO_ROOT/logs/deploy-poller.failed_tag"
LOCK="$REPO_ROOT/logs/deploy-poller.lock"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --once) ;;  # default; accepted for clarity
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s [poller] %s\n' "$(date -u +%FT%TZ)" "$*"; }

mkdir -p "$REPO_ROOT/logs"

# 1. Latest published non-prerelease Release tag. Distinguish "no release yet"
#    (404 — normal, quiet) from a real gh auth/network failure (loud WARN, so a
#    silently-expired gh token doesn't make the mini stop deploying unnoticed).
gh_err="$(mktemp)"
latest="$(gtimeout 30 gh api "repos/${REPO}/releases/latest" --jq '.tag_name' 2>"$gh_err")" || latest=""
if [[ -z "$latest" ]]; then
  if grep -qi 'not found\|404' "$gh_err"; then
    say "no published release yet — skip"
  else
    say "WARN: gh api failed (auth/network?) — NOT deploying. stderr: $(tr '\n' ' ' < "$gh_err" | head -c 200)"
  fi
  rm -f "$gh_err"
  exit 0
fi
rm -f "$gh_err"

deployed=""
[[ -f "$DEPLOYED_FILE" ]] && deployed="$(cat "$DEPLOYED_FILE")"
if [[ "$latest" == "$deployed" ]]; then
  say "up to date ($deployed)"
  exit 0
fi

failed=""
[[ -f "$FAILED_FILE" ]] && failed="$(cat "$FAILED_FILE")"
if [[ "$latest" == "$failed" ]]; then
  say "release $latest previously FAILED to deploy — skipping until a newer release (manual intervention needed)"
  exit 0
fi

# Dirty-tree guard: never destructively clean (CLAUDE.md bans reset --hard /
# checkout -f). After the Component 0 fix the tree stays clean, so a dirty tree
# here is a genuine anomaly — alert and skip.
if ! git diff --quiet || ! git diff --cached --quiet; then
  say "ALERT: working tree dirty — refusing to auto-deploy $latest. Resolve on the mini, then it deploys next tick."
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  say "[dry-run] would deploy $latest (deployed=${deployed:-none})"
  exit 0
fi

say "deploying $latest (was ${deployed:-none})"
# gtimeout 1800 bounds a hung deploy (e.g. uv sync / npm ci stalling on the
# network) so a stuck build can't hold the lock forever — a timeout surfaces as
# rc=124 and is treated as a failed deploy below. lockf -t 0 is the lock: it
# AUTO-RELEASES if this process dies (crash-safe, unlike a mkdir-based lock that
# would leave a stale dir), and returns EX_TEMPFAIL=75 only when the lock is
# held. macmini-prod.sh itself only ever exits 0/1/2 (verified), so 75 is an
# unambiguous "lock held" signal and cannot be confused with a real failure.
set +e
gtimeout 1800 /usr/bin/lockf -t 0 "$LOCK" bash "$REPO_ROOT/scripts/deploy/macmini-prod.sh" "$latest"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  say "deploy of $latest OK"
  rm -f "$FAILED_FILE"
  exit 0
fi
if [[ $rc -eq 75 ]]; then
  # lockf EX_TEMPFAIL: a deploy is already running. Try again next tick.
  say "another deploy in progress (lock held) — retry next tick"
  exit 0
fi
say "deploy of $latest FAILED (rc=$rc) — macmini-prod.sh self-rolled-back (rc=124 = timed out); marking failed"
echo "$latest" > "$FAILED_FILE"
exit 1
```

- [ ] **Step 2: Make executable + syntax check**

Run:
```bash
chmod +x scripts/deploy/macmini-deploy-poller.sh
bash -n scripts/deploy/macmini-deploy-poller.sh && echo "syntax OK"
```
Expected: `syntax OK`.

- [ ] **Step 3: Local dry-run decision test (no deploy)**

This exercises the comparison logic on the MacBook. `gh` may 404 (no release
yet) → "no published release yet" path, or return a tag → "[dry-run] would
deploy" / "up to date".

Run:
```bash
scripts/deploy/macmini-deploy-poller.sh --dry-run --once
```
Expected: one `[poller]` log line — either "no published release yet", "up to
date (...)", or "[dry-run] would deploy ...". No deploy occurs. (Authoritative
validation happens on the mini in Task 11.)

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy/macmini-deploy-poller.sh
git commit -m "feat(deploy): macmini-deploy-poller.sh — Release-gated auto-deploy trigger"
```

---

## Task 9: Poller launchd plist + bootstrap registration

**Files:**
- Create: `config/templates/com.argon.deploy-poller.plist.template`
- Modify: `scripts/deploy/macmini-bootstrap.sh`

- [ ] **Step 1: Create the plist template**

Create `config/templates/com.argon.deploy-poller.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.deploy-poller</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>__PROJECT_DIR__/scripts/deploy/macmini-deploy-poller.sh</string>
        <string>--once</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <!-- Same PATH as com.argon.worker.plist.template. __BREW_PREFIX__/bin
             resolves every tool macmini-prod.sh and the poller invoke: git, gh,
             gtimeout, uv, npm, node, curl, brew. Migrations run in-process via
             psycopg (scripts/migrate.sh -> uv run python -m ...migrate_runner),
             so NO psql CLI / postgresql-version bin is needed on PATH. -->
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>USER</key>
        <string>__USER__</string>
    </dict>

    <!-- StartInterval (not KeepAlive): launchd re-runs this short-lived script
         every 120s. KeepAlive would busy-loop (relaunch instantly on exit). -->
    <key>StartInterval</key>
    <integer>120</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/deploy-poller.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/deploy-poller.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Render the poller plist + install coreutils in bootstrap**

In `scripts/deploy/macmini-bootstrap.sh`, after the static-plist renders (after
`render_static_plist "com.argon.backup"`, line ~363), add:

```bash
render_static_plist "com.argon.deploy-poller"
```

And in the brew-install block (after `brew_install "gh"`, line ~112), add
`coreutils` — the poller calls `gtimeout` (a coreutils binary) to bound its
`gh api` call. The live mini already has it, but a fresh provision would fail
`gtimeout: command not found` on the first poll without this:

```bash
brew_install "coreutils"
```

- [ ] **Step 3: Load the poller plist (outside services.list)**

In `scripts/deploy/macmini-bootstrap.sh`, after the services.list load loop ends
(after the `done < "${ARGON_HOME}/config/services.list"` line ~394, and after
the existing `# Backup plist is rendered but NOT loaded here` comment, line ~396),
add:

```bash
# Deploy poller: rendered + loaded but kept OUT of services.list. It is the
# thing that PERFORMS deploys (runs macmini-prod.sh), so it must never be
# kickstarted as part of an app deploy — same exclusion rationale as the backup
# plist. StartInterval drives it; it polls GitHub for new Releases every 120s.
poller_plist="$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist"
launchctl unload "$poller_plist" >/dev/null 2>&1 || true
launchctl load "$poller_plist"
ok "loaded com.argon.deploy-poller"
```

- [ ] **Step 4: Verify**

Run:
```bash
bash -n scripts/deploy/macmini-bootstrap.sh && echo "syntax OK"
grep -n "deploy-poller" scripts/deploy/macmini-bootstrap.sh
# Render a sample plist with the placeholders filled and lint it:
sed -e "s|__PROJECT_DIR__|/tmp/argon|g" -e "s|__USER__|moremeds|g" -e "s|__BREW_PREFIX__|/opt/homebrew|g" \
  config/templates/com.argon.deploy-poller.plist.template > /tmp/poller.plist
plutil -lint /tmp/poller.plist
```
Expected: syntax OK; two `deploy-poller` matches (render + load); `/tmp/poller.plist: OK`.

- [ ] **Step 5: Commit**

```bash
git add config/templates/com.argon.deploy-poller.plist.template scripts/deploy/macmini-bootstrap.sh
git commit -m "feat(deploy): com.argon.deploy-poller launchd plist + bootstrap wiring"
```

---

## Task 10: Docs + memory

**Files:**
- Create: `docs/runbooks/release.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `~/.claude/projects/-Users-chenxi-projects-argon/memory/MEMORY.md` + a memory file

- [ ] **Step 1: Create the runbook `docs/runbooks/release.md`**

```markdown
# Release runbook

Argon ships to the Mac mini via a tag-driven pipeline (no Docker; launchd stack).

## Cut a release

1. Land your feature PRs to `main` with CHANGELOG entries under `## [Unreleased]`.
2. `scripts/release/cut.sh prepare [patch|minor|major]` — opens a `release/vX.Y.Z`
   PR that bumps `VERSION` + `pyproject.toml` + `web/package.json` and promotes
   the `[Unreleased]` block to `[X.Y.Z]`.
3. Merge that PR after CI is green.
4. `scripts/release/cut.sh tag` (on `main`) — tags `vX.Y.Z` and pushes the tag.

The tag push fires `.github/workflows/release.yml`:
- **verify** re-runs the full suite (ruff, guardrails, unit + integration, web
  build, `version_sync_check`) on the tagged commit.
- **publish** cuts a GitHub Release from the matching CHANGELOG section.

## Auto-deploy (the mini)

`com.argon.deploy-poller` (launchd, every 120s) polls
`gh api repos/moremeds/argon/releases/latest`. When the latest published,
non-prerelease Release tag differs from `logs/deployed_tag.txt`, it runs
`scripts/deploy/macmini-prod.sh <tag>` (checkout → build → migrate → kickstart →
health-check → auto-rollback). Prereleases (`vX.Y.Z-rc1`) verify + publish a
GitHub prerelease but are **never** auto-deployed.

Logs: `logs/deploy-poller.{out,err}.log`, `logs/deploy.log`.
State: `logs/deployed_tag.txt` (last good deploy), `logs/deploy-poller.failed_tag`
(a release whose deploy failed + rolled back — the poller skips it until a newer
release; clear it manually once fixed: `rm logs/deploy-poller.failed_tag`).

## Manual deploys — pause the poller first

The poller serializes its own ticks with `lockf`, but a hand-run
`macmini-prod.sh` does **not** take that lock — running one while the poller fires
could race two `git checkout`s on the same tree. Before any manual deploy, pause
the poller, then resume it after:

```bash
launchctl unload ~/Library/LaunchAgents/com.argon.deploy-poller.plist   # pause
scripts/deploy/macmini-prod.sh <tag>                                    # manual deploy
launchctl load   ~/Library/LaunchAgents/com.argon.deploy-poller.plist   # resume
```

## Roll back

The poller and `macmini-prod.sh` auto-roll-back on a failed health check. To
force a rollback to a known-good release, **pause the poller** (above), then run
on the mini: `scripts/deploy/macmini-prod.sh <previous-good-tag>` (it records that
tag as deployed; the poller then stays put until a newer Release is published).
Resume the poller when done.

## First-time / dirty-tree note

`web/next-env.d.ts` is untracked and the deploy uses `npm ci`, so the tree stays
clean across deploys. If the poller logs `ALERT: working tree dirty`, inspect
`git status` on the mini and resolve (e.g. `git checkout -- <file>`) — never
`git reset --hard`.
```

- [ ] **Step 2: Add a Release procedure section + look-up rows to `CLAUDE.md`**

In `CLAUDE.md`, under "## Daily commands", after the code block, add:

```markdown
## Release procedure

Tag-driven, launchd-native (no Docker). Cut a release with
`scripts/release/cut.sh prepare [patch|minor|major]` (opens a release PR) → merge
→ `scripts/release/cut.sh tag` (pushes `vX.Y.Z`). The tag fires
`.github/workflows/release.yml` (verify → publish GitHub Release). The mini's
`com.argon.deploy-poller` (every 120s) deploys the latest **published,
non-prerelease** Release via `scripts/deploy/macmini-prod.sh`. Prereleases
(`vX.Y.Z-rc1`) verify + publish but never auto-deploy. See
`docs/runbooks/release.md`.
```

And in the "## Where to look first" table, add these rows:

```markdown
| Release pipeline (versioning + workflow) | `VERSION` + `CHANGELOG.md` + `scripts/release/{_lib.sh,version_sync_check.py,cut.sh}` + `.github/workflows/release.yml` |
| Auto-deploy to the mini | `scripts/deploy/macmini-deploy-poller.sh` + `config/templates/com.argon.deploy-poller.plist.template` + `scripts/deploy/macmini-prod.sh`; runbook `docs/runbooks/release.md` |
```

- [ ] **Step 3: Mirror the policy into `AGENTS.md`**

Add the same "## Release procedure" section to `AGENTS.md` (find the equivalent
location — after its daily-commands / quickstart block). Keep wording identical
to the CLAUDE.md section so the two stay in sync (per the project rule "keep both
files in sync when policy changes").

- [ ] **Step 4: Verify docs render / links resolve**

Run:
```bash
test -f docs/runbooks/release.md && echo "runbook present"
grep -q "Release procedure" CLAUDE.md AGENTS.md && echo "both files updated"
```
Expected: both lines print.

- [ ] **Step 5: Update memory**

Create `~/.claude/projects/-Users-chenxi-projects-argon/memory/project_release_pipeline.md`:

```markdown
---
name: project_release_pipeline
description: argon tag-driven release — cut.sh → release.yml → mini deploy-poller runs macmini-prod.sh; launchd, no Docker
metadata:
  type: project
---

Argon's release procedure (shipped 2026-06-17, mirrors xenon's automation but
launchd-native, NOT Docker):

- Cut: `scripts/release/cut.sh prepare [patch|minor|major]` opens a release PR
  (bumps VERSION + pyproject + web/package.json, promotes CHANGELOG); merge; then
  `cut.sh tag` pushes `vX.Y.Z`. argon never pushes main, so the bump is a PR and
  the tag is cut from green main (two-phase, unlike xenon's single-phase cut.sh).
- `.github/workflows/release.yml`: tag `v*` → verify (full CI gates +
  version_sync_check on the tagged SHA) → publish GitHub Release from the
  CHANGELOG section (prerelease if the tag has a `-suffix`).
- Mini: `com.argon.deploy-poller` (launchd StartInterval=120, NOT in
  services.list — same exclusion as com.argon.backup) polls
  `gh api .../releases/latest` and runs `macmini-prod.sh <tag>` under
  `/usr/bin/lockf -t 0` (macOS has no flock). Gates on the published Release, so
  only verify-passed versions deploy; prereleases never auto-deploy.
- State on the mini: `logs/deployed_tag.txt` (written by macmini-prod.sh on
  success), `logs/deploy-poller.failed_tag` (skip-marker for a rolled-back tag).
- Prereq that made it work: untracked `web/next-env.d.ts` + switched deploy to
  `npm ci` so the tree stays clean (otherwise the dirty-guard blocks every deploy).
  See [[reference_macmini_deploy_gotchas]].
```

Then add to `MEMORY.md` (under the project entries):

```markdown
- [argon release pipeline](project_release_pipeline.md) — cut.sh → release.yml → mini deploy-poller runs macmini-prod.sh; launchd not Docker; lockf not flock; npm ci + untracked next-env.d.ts keep the tree clean
```

- [ ] **Step 6: Commit**

```bash
git add docs/runbooks/release.md CLAUDE.md AGENTS.md
git commit -m "docs(release): runbook + CLAUDE.md/AGENTS.md release procedure"
```
(Memory files live outside the repo — they are not committed here.)

---

## Task 11: Live rollout & validation (mini-side)

Runs after the PR merges to `main`. Parts execute on the mini over SSH
(`moremeds@100.66.147.98`). This is the real end-to-end proof.

- [ ] **Step 1: Merge the implementation PR to `main`** (via `gh pr merge` after CI green — never a direct push).

- [ ] **Step 2: Clean the mini tree + pull the gitignore change**

```bash
ssh moremeds@100.66.147.98 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; set -e
cd ~/projects/argon
git fetch origin
git checkout -- web/next-env.d.ts web/package-lock.json 2>/dev/null || true
git checkout main && git pull --ff-only origin main
git rm --cached --ignore-unmatch web/next-env.d.ts >/dev/null 2>&1 || true
git status --porcelain'
```
Expected: clean (empty) `git status --porcelain`, or only untracked `data/backups/`.

- [ ] **Step 3: Install + load the poller plist on the mini**

```bash
ssh moremeds@100.66.147.98 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; set -e
cd ~/projects/argon
BREW_PREFIX=/opt/homebrew
sed -e "s|__PROJECT_DIR__|$HOME/projects/argon|g" -e "s|__USER__|moremeds|g" -e "s|__BREW_PREFIX__|$BREW_PREFIX|g" \
  config/templates/com.argon.deploy-poller.plist.template > "$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist"
plutil -lint "$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist"
launchctl list | grep deploy-poller'
```
Expected: `OK`; a `com.argon.deploy-poller` line in `launchctl list`.

- [ ] **Step 4: Seed deployed_tag so the poller starts from a known state**

Set the deployed marker to the currently-live commit's eventual tag baseline so
the first real release is what triggers a deploy:

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/argon && [ -f logs/deployed_tag.txt ] && cat logs/deployed_tag.txt || echo "(no deployed_tag yet — first release will deploy)"'
```
Expected: prints the file or the "(no deployed_tag yet …)" note. (No release
exists yet, so the poller is currently a 404 no-op — confirm in Step 5.)

- [ ] **Step 5: Confirm the poller no-ops cleanly with zero releases**

```bash
ssh moremeds@100.66.147.98 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; cd ~/projects/argon && bash scripts/deploy/macmini-deploy-poller.sh --dry-run --once'
```
Expected: `... [poller] no published release yet (or gh/network error) — skip`.

- [ ] **Step 6: Validate the PRERELEASE path (verify + publish, NO deploy)**

From the MacBook on `main`:
```bash
# Manually create a prerelease tag to exercise the gate (cut.sh tag is for finals;
# for the rc, tag by hand from green main):
git fetch origin main && git checkout main && git pull --ff-only
git tag -a v0.1.0-rc1 -m "v0.1.0-rc1 (pipeline validation)" && git push origin v0.1.0-rc1
```
Then watch the workflow and confirm the mini does NOT deploy:
```bash
gh run watch "$(gh run list --workflow Release --limit 1 --json databaseId --jq '.[0].databaseId')"
gh release view v0.1.0-rc1 --json isPrerelease --jq .isPrerelease   # expect true
ssh moremeds@100.66.147.98 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; cd ~/projects/argon && bash scripts/deploy/macmini-deploy-poller.sh --dry-run --once'
```
Expected: Release run succeeds; `isPrerelease=true`; poller logs "no published
release yet" (releases/latest excludes prereleases) → no deploy.

- [ ] **Step 7: Validate the FINAL release path (full auto-deploy)**

```bash
scripts/release/cut.sh tag   # tags v0.1.0 (VERSION=0.1.0), pushes the tag
gh run watch "$(gh run list --workflow Release --limit 1 --json databaseId --jq '.[0].databaseId')"
gh release view v0.1.0 --json isPrerelease --jq .isPrerelease   # expect false
```
Within ~2 min the mini poller should deploy. Confirm:
```bash
ssh moremeds@100.66.147.98 'cd ~/projects/argon && tail -5 logs/deploy-poller.out.log && echo "---deployed_tag---" && cat logs/deployed_tag.txt && echo "---deploy.log---" && tail -2 logs/deploy.log'
curl -fsS --max-time 5 http://100.66.147.98:8400/api/health | head -c 200; echo
```
Expected: poller log shows "deploy of v0.1.0 OK"; `deployed_tag.txt` = `v0.1.0`;
`deploy.log` shows an `OK` line; `/api/health` reachable. (Optionally confirm
the API reports version 0.1.0 once the version field is surfaced in health.)

- [ ] **Step 8: Final summary**

Report: which tags were cut, the Release URLs, the poller log proving the
deploy, and the health-check result. No commit (rollout is operational).

---

## Self-Review (completed during planning)

**Spec coverage** — every spec component maps to a task:
- Component 0 (tree cleanliness) → Task 1
- Component 1 (VERSION/CHANGELOG/sync/runtime version) → Tasks 2, 5
- Component 2 (scripts/release/) → Tasks 2, 3, 4
- Component 3 (release.yml) → Task 7
- Component 4 (poller + plist + bootstrap) → Tasks 8, 9
- Component 5 (macmini-prod.sh deployed_tag) → Task 6
- Failure handling (prerelease/lockf/failed-marker/dirty-guard) → Tasks 8, 11
- Testing → Tasks 2, 3, 5, 8, 11
- Docs → Task 10

**Type/name consistency** — `logs/deployed_tag.txt`, `logs/deploy-poller.failed_tag`,
`logs/deploy-poller.lock`, `com.argon.deploy-poller`, `version_sync_check.py::check`,
`_app_version()` are used identically across the tasks that reference them.

**Placeholder scan** — no TBD/TODO; every code step shows complete content.

**Reviewed (Gemini bilateral, 2026-06-17) — findings deliberately NOT applied, with rationale:**
- **Serial integration tests in `release.yml` (vs ci.yml's 4 shards).** A conscious
  tradeoff (spec: "slower but identical coverage"). Releases are infrequent; the
  shard-selector + collection-match machinery would duplicate ~40 lines of ci.yml
  for a path that runs a handful of times. A `workflow_call` reusable workflow is
  the noted future DRY cleanup (out of scope for v1). Coverage is identical; only
  wall-clock differs.
- **`lockf` rc=75 collision.** Kept `lockf` (not a mkdir-lock) because it
  auto-releases on process death (crash-safe). The 75-ambiguity is real only if
  `macmini-prod.sh` could exit 75 — it exits exclusively 0/1/2 (verified), so the
  collision cannot occur. Documented inline in the poller.

**Known execution-time confirmations** (not blockers):
- `softprops/action-gh-release@v3` pinned to match xenon; if the tag publish step
  errors on the action version, check the action's current major and adjust.
- `/usr/bin/lockf -t 0` EX_TEMPFAIL = exit **75** — verified empirically on this
  macOS (lock-held → 75; wrapped success → 0; wrapped failure rc=1 → passes
  through 1). `macmini-prod.sh` only ever exits 0/1/2, so it cannot collide with
  75 — the poller's `rc==75 ⇒ lock held` branch is unambiguous.
