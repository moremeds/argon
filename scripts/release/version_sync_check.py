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
