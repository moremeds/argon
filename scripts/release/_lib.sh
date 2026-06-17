# shellcheck shell=bash
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
