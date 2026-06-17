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
