"""Regression test: Settings.from_env loads .env.local with override semantics.

.env.local is a gitignored per-machine override. Used on the MacBook to point
UW_SCAN_DB_HOST at the mini (100.66.147.98) without editing the committed
.env. Because _load_dotenv only sets keys NOT already present in os.environ,
loading .env.local FIRST means it wins on conflicts with .env.

Paired with the dev.sh tripwire (UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 required to
run dev.sh against the mini) — together they prevent MacBook/mini worker
queue races after Phase 4 cutover.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

from uw_scan.config import Settings


@pytest.fixture
def env_isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip every UW_SCAN_* env var so the test starts from a clean slate."""
    for key in list(os.environ):
        if key.startswith("UW_SCAN_"):
            monkeypatch.delenv(key, raising=False)
    yield


def _write_env(path: Path, **kwargs: str) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in kwargs.items()) + "\n")


def test_env_local_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_isolated: None
) -> None:
    """When .env.local sets UW_SCAN_DB_HOST, it wins over .env."""
    _write_env(
        tmp_path / ".env",
        UW_SCAN_API_KEY="from-env",
        UW_SCAN_DB_HOST="127.0.0.1",
        UW_SCAN_DB_NAME="local_db",
    )
    _write_env(
        tmp_path / ".env.local",
        UW_SCAN_DB_HOST="100.66.147.98",
    )

    # Re-root from_env at the temp dir by patching the file's resolution.
    monkeypatch.setattr(
        "uw_scan.config.__file__",
        str(tmp_path / "src" / "uw_scan" / "config.py"),
    )
    (tmp_path / "src" / "uw_scan").mkdir(parents=True, exist_ok=True)

    s = Settings.from_env()

    assert s.db_host == "100.66.147.98"  # .env.local wins
    assert s.db_name == "local_db"  # .env still supplies non-overridden keys
    assert s.api_key.get_secret_value() == "from-env"


def test_env_only_when_no_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_isolated: None
) -> None:
    """Missing .env.local is fine — .env values stand."""
    _write_env(
        tmp_path / ".env",
        UW_SCAN_API_KEY="from-env",
        UW_SCAN_DB_HOST="127.0.0.1",
    )

    monkeypatch.setattr(
        "uw_scan.config.__file__",
        str(tmp_path / "src" / "uw_scan" / "config.py"),
    )
    (tmp_path / "src" / "uw_scan").mkdir(parents=True, exist_ok=True)

    s = Settings.from_env()
    assert s.db_host == "127.0.0.1"


def test_existing_environ_wins_over_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_isolated: None
) -> None:
    """os.environ takes precedence over both .env.local and .env (loader
    semantics: only set if unset)."""
    monkeypatch.setenv("UW_SCAN_DB_HOST", "from-shell")
    monkeypatch.setenv("UW_SCAN_API_KEY", "from-shell-key")
    _write_env(
        tmp_path / ".env",
        UW_SCAN_API_KEY="from-env",
        UW_SCAN_DB_HOST="127.0.0.1",
    )
    _write_env(
        tmp_path / ".env.local",
        UW_SCAN_DB_HOST="100.66.147.98",
    )

    monkeypatch.setattr(
        "uw_scan.config.__file__",
        str(tmp_path / "src" / "uw_scan" / "config.py"),
    )
    (tmp_path / "src" / "uw_scan").mkdir(parents=True, exist_ok=True)

    s = Settings.from_env()
    assert s.db_host == "from-shell"
    assert s.api_key.get_secret_value() == "from-shell-key"
