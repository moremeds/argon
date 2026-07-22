#!/usr/bin/env python3
"""CI guard: runtime assets must ship inside the package.

The 2026-07-08 Docker cutover silently broke two runtime code paths because
docker/app.Dockerfile does not COPY docs/. Nothing caught it: every test runs
from a checkout, where docs/ exists. This guard encodes the rules that would.

Rule 1 — no `Path.home()` in src/ outside config.py. Path defaults belong in
         Settings, which is env-overridable and documented. A home-dir default
         resolves to /root inside the container, where nothing is mounted.
Rule 2 — no docs/ path construction in src/. docs/ is not in the image.
Rule 3 — no named RUNTIME ASSET may be reached through a docs/ path, in src/
         OR scripts/. scripts/ is COPYied into the image
         (docker/app.Dockerfile:50), but it also holds research tooling that
         legitimately reads and writes docs/ — 38 such lines today. Blanket-
         scanning scripts/ would therefore be pure noise. Rule 3 is the
         precise version: only files that touch a real runtime asset are
         judged, and they are judged file-wide so a path split across several
         lines is still caught.

Run locally:
    uv run python scripts/check_runtime_assets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
SCRIPTS = REPO_ROOT / "scripts"

# Matches `pathlib.Path.home()` too — same substring.
HOME_DEFAULT = re.compile(r"Path\.home\(\)")

# Both quote styles plus the two other ways to build the same path.
DOCS_PATH = re.compile(
    r"""(/\s*['"]docs['"])"""  # Path(...) / "docs"
    r"""|(['"]docs/)"""  # Path("docs/research/...")
    r"""|(joinpath\(\s*['"]docs['"])"""  # .joinpath("docs", ...)
)

# Files the app reads at runtime. Add to this list when a new one appears.
RUNTIME_ASSETS = (
    "canary-calibration-v1.json",
    "canary-calibration-v2.json",
    "guidance.md",
)

# config.py is the ONE place a home-dir default is allowed: it is the single
# env-overridable source of path configuration for the whole app.
HOME_ALLOWLIST = {SRC / "uw_scan" / "config.py"}

# data_gap_healer embeds its own regeneration command as help text, which
# WRITES docs/runbooks/... It never reads a doc at runtime.
DOCS_ALLOWLIST = {SRC / "uw_scan" / "reports" / "data_gap_healer.py"}

SELF = Path(__file__).resolve()
EXCLUDE_DIRS = {"__pycache__", ".venv", "node_modules"}


def _py_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        p
        for p in root.rglob("*.py")
        if not any(part in EXCLUDE_DIRS for part in p.parts) and p.resolve() != SELF
    ]


def main() -> int:
    violations: list[str] = []

    for path in _py_files(SRC):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            if HOME_DEFAULT.search(line) and path not in HOME_ALLOWLIST:
                violations.append(
                    f"  {rel}:{lineno}: Path.home() outside config.py — "
                    f"put the default in Settings: {line.strip()[:100]}"
                )
            if DOCS_PATH.search(line) and path not in DOCS_ALLOWLIST:
                violations.append(
                    f"  {rel}:{lineno}: runtime path into docs/ — docs/ is not "
                    f"shipped in the image: {line.strip()[:100]}"
                )

    for path in _py_files(SRC) + _py_files(SCRIPTS):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(asset in text for asset in RUNTIME_ASSETS) and DOCS_PATH.search(text):
            violations.append(
                f"  {path.relative_to(REPO_ROOT)}: references a runtime asset "
                f"({', '.join(a for a in RUNTIME_ASSETS if a in text)}) and "
                f"builds a docs/ path — resolve it via importlib.resources"
            )

    if not violations:
        print("OK: runtime assets resolve from the package, not from docs/.")
        return 0

    print("FAIL: runtime assets must ship inside the package.")
    print(
        "      See docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md"
    )
    print("\n".join(sorted(set(violations))))
    return 1


if __name__ == "__main__":
    sys.exit(main())
