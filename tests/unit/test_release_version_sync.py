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


def _write_lock(root: Path, *, editable_version: str | None = "1.2.3") -> None:
    """Write a minimal uv.lock with one registry dep and (optionally) the editable root.

    Mirrors the real uv.lock shape: the project itself is the single package whose
    source is `{ editable = "." }`. `editable_version=None` omits the editable
    package entirely (simulates a malformed/unexpected lock).
    """
    blocks = [
        '[[package]]\nname = "apscheduler"\nversion = "3.10.4"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    ]
    if editable_version is not None:
        blocks.append(
            f'[[package]]\nname = "x"\nversion = "{editable_version}"\n'
            'source = { editable = "." }\n'
        )
    (root / "uv.lock").write_text("\n".join(blocks))


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


def test_uv_lock_match_passes(tmp_path):
    _setup(tmp_path)
    _write_lock(tmp_path, editable_version="1.2.3")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "OK: 1.2.3" in r.stdout


def test_uv_lock_mismatch_fails(tmp_path):
    # This is the prod-wedging case: lock self-version lags VERSION/pyproject.
    _setup(tmp_path)
    _write_lock(tmp_path, editable_version="1.2.2")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "uv.lock editable self-version" in r.stderr
    assert "1.2.2" in r.stderr


def test_uv_lock_no_editable_root_fails(tmp_path):
    # A lock with no editable root package is unexpected — fail loudly, don't pass.
    _setup(tmp_path)
    _write_lock(tmp_path, editable_version=None)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "uv.lock editable root package (not uniquely found)" in r.stderr


def test_uv_lock_absent_is_skipped(tmp_path):
    # No uv.lock present (e.g. a non-uv checkout) → lock check is skipped, others still run.
    _setup(tmp_path)
    assert not (tmp_path / "uv.lock").exists()
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
