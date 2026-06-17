"""The FastAPI app reports the version from the root VERSION file."""

from __future__ import annotations

from pathlib import Path

from uw_scan.api.server import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_app_version_matches_version_file():
    expected = (REPO_ROOT / "VERSION").read_text().strip()
    app = create_app()
    assert app.version == expected
