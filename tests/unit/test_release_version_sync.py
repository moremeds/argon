"""Tests for scripts/release/version_sync_check.py (run as a CLI)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "release"
    / "version_sync_check.py"
)


def _setup(root: Path, *, version="1.2.3", py="1.2.3", web="1.2.3") -> None:
    (root / "VERSION").write_text(version + "\n")
    (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{py}"\n')
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
