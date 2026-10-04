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


def test_a_long_wait_turns_warning_and_stays_rate_limited(monkeypatch, caplog):
    """A migration that failed part-way never moves the marker: after ~10 min the
    wait must say so at WARNING instead of idling at INFO forever."""
    import logging

    import psycopg

    from uw_scan.worker import schema_gate

    def _unreachable(*_a, **_k):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(schema_gate.psycopg, "connect", _unreachable)
    now = [0.0]

    class _Stop(Exception):
        pass

    def _sleep(seconds: float) -> None:
        now[0] += seconds
        if now[0] > 900:
            raise _Stop

    caplog.set_level(logging.INFO, logger="uw_scan.worker.schema_gate")
    with pytest.raises(_Stop):
        schema_gate.wait_for_schema(
            "dsn", expected="158_x.sql", sleep=_sleep, clock=lambda: now[0]
        )

    levels = [r.levelno for r in caplog.records]
    # 15 s polls over 900 s, logged at most once a minute: 0,60,...,900 -> 16 lines.
    assert len(levels) <= 16
    assert set(levels[:10]) == {logging.INFO}  # first 10 min
    assert levels[-1] == logging.WARNING
    assert "migration may have failed; check api logs" in caplog.records[-1].message
