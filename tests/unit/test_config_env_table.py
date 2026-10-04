"""The env table (D6 batch 2) keeps from_env's error order.

Before the table, ``from_env`` ran the host/DB tripwire before parsing any field, so a
wrong-tier pair was refused even when another value would also fail to parse.
"""

from pathlib import Path

import pytest

from uw_scan.config import Settings


def test_db_tripwire_runs_before_field_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    monkeypatch.delenv("UW_SCAN_ALLOW_DB_MISMATCH", raising=False)
    monkeypatch.delenv("UW_SCAN_DB_NAME", raising=False)
    monkeypatch.setenv("UW_SCAN_API_KEY", "k")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "100.66.147.98")  # mini host + local db name
    monkeypatch.setenv("UW_SCAN_DB_PORT", "not-a-port")
    with pytest.raises(RuntimeError, match="Refusing to start"):
        Settings.from_env(env_path=empty)
