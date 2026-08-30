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

  # Re-lock so uv.lock's editable self-version matches the bumped pyproject. Without
  # this the committed lock lags (lock says $current, pyproject says $next); the first
  # `uv run` then rewrites that one line and the frozen Docker build no longer reflects
  # the reviewed bytes. version_sync_check (below, and pre-sync in CI) enforces the
  # match. See docs/runbooks/release.md.
  uv lock

  uv run python scripts/release/version_sync_check.py || die "version_sync_check failed after bump"

  git add VERSION pyproject.toml web/package.json CHANGELOG.md uv.lock
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

# The release PR merge starts main-push CI asynchronously. Local/main SHA equality
# proves provenance but not that the exact commit passed every required gate, so wait
# for that immutable CI result before creating a tag. release.yml repeats this check
# as defense in depth for manually pushed tags.
release_sha="$(git rev-parse HEAD)"
say "Waiting for exact-SHA main CI success: $release_sha"
uv run python scripts/release/require_ci_success.py \
  --repo moremeds/argon \
  --sha "$release_sha" \
  --workflow ci.yml \
  --branch main \
  --timeout-seconds 1800 || die "exact-SHA main CI gate failed"

section="$(extract_changelog_section CHANGELOG.md "$version")"
say "Tagging v$version"
git tag -a "v$version" -m "v$version

$section"
git push origin "v$version"
say "Pushed tag v$version — release.yml builds the immutable image set, promotes final :latest tags, then publishes; Watchtower deployment is asynchronous."
