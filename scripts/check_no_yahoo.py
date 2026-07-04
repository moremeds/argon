#!/usr/bin/env python3
"""CI guard: forbid Yahoo Finance as a data source.

CLAUDE.md bans Yahoo twice ("Never fall back to Yahoo", "Yahoo is banned");
this turns the standing rule into a CI invariant. The codebase has zero
Yahoo references as of guard introduction (2026-07-04) — any match fails.

Run locally:
    uv run python scripts/check_no_yahoo.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = re.compile(r"\byfinance\b|finance\.yahoo\.com")

SCAN_DIRS = ("src", "web", "scripts", "tests")
INCLUDE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
EXCLUDE_DIRS = {"node_modules", ".next", "__pycache__", ".venv"}
ALLOWLIST = {REPO_ROOT / "scripts/check_no_yahoo.py"}


def main() -> int:
    violations: list[str] = []
    for top in SCAN_DIRS:
        base = REPO_ROOT / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in INCLUDE_SUFFIXES:
                continue
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path in ALLOWLIST:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN.search(line):
                    violations.append(
                        f"  {path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()[:120]}"
                    )

    if not violations:
        print("OK: no Yahoo Finance references.")
        return 0

    print("FAIL: Yahoo Finance references found — CLAUDE.md: 'Yahoo is banned'.")
    print("      Use xenon/IB, UW, FMP, or massive instead.")
    print("\n".join(violations))
    return 1


if __name__ == "__main__":
    sys.exit(main())
