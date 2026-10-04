"""Schema gate decisions (I-05); the DB path is in tests/integration/worker/."""

from __future__ import annotations

from pathlib import Path

import pytest

from uw_scan.worker.schema_gate import expected_migration, schema_is_ready


def test_behind_waits_equal_and_ahead_proceed():
    assert not schema_is_ready("156_x.sql", "158_schema_version.sql")
    assert schema_is_ready("158_schema_version.sql", "158_schema_version.sql")
    # Rollback: an older image (expects 156) against a DB migrated to 158 must
    # proceed, not wait forever.
    assert schema_is_ready("158_schema_version.sql", "156_x.sql")


def test_no_marker_waits():
    # A fresh DB, or one where migration 158 has not run yet.
    assert not schema_is_ready(None, "158_schema_version.sql")


def test_the_shipped_chain_has_a_three_digit_newest_prefix():
    assert expected_migration()[:3].isdigit()


def test_a_four_digit_prefix_fails_loudly(tmp_path: Path):
    (tmp_path / "999_last.sql").write_text("")
    (tmp_path / "1000_next.sql").write_text("")  # sorts BEFORE 999_ as a string
    (tmp_path / "abc_bad.sql").write_text("")
    with pytest.raises(RuntimeError, match="3-digit prefix"):
        expected_migration(tmp_path)
