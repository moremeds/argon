"""Fail if VERSION, pyproject [project].version, web/package.json, or uv.lock disagree.

VERSION is the source of truth. Argon has no root package.json (all Node deps
live under web/), so web/package.json is the only tracked Node package; it
versions in lockstep with the Python package.

uv.lock pins the editable root package (`source = { editable = "." }`) at the
pyproject version. If the committed lock lags VERSION, the first `uv run` on any
host rewrites that one line, dirtying the working tree — which makes the mac-mini
deploy poller refuse to deploy (it never `reset --hard`s) and silently wedges
prod on the last-deployed release. cut.sh re-locks on every bump; this check is
the regression guard. It compares only the editable self-version string, so it
is immune to uv-version-dependent formatting drift elsewhere in the lock.

Run it against the *committed* lock — before any `uv sync`, which auto-repairs
the lock and would mask the drift.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def _editable_lock_version(lock_path: Path) -> str | None:
    """Version of the editable root package in uv.lock, or None if not uniquely found.

    The project itself is the single `[[package]]` whose source is the editable
    root (`source = { editable = "." }`). Returns None on zero or multiple such
    packages so the caller reports a loud mismatch rather than guessing.
    """
    data = tomllib.loads(lock_path.read_text())
    editable = [
        pkg
        for pkg in data.get("package", [])
        if isinstance(pkg.get("source"), dict) and pkg["source"].get("editable") == "."
    ]
    if len(editable) != 1:
        return None
    return editable[0].get("version", "")


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

    uv_lock = root / "uv.lock"
    if uv_lock.exists():
        lock_version = _editable_lock_version(uv_lock)
        if lock_version is None:
            mismatches.append(
                ("uv.lock editable root package (not uniquely found)", "<none>")
            )
        elif lock_version != version:
            mismatches.append(("uv.lock editable self-version", lock_version))

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
