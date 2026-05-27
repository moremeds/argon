from __future__ import annotations

import importlib.util
import sys
from unittest.mock import patch

import psycopg
import pytest


def _import_backfill_module():
    spec = importlib.util.spec_from_file_location(
        "backfill_vcg_v2", "scripts/backfill_vcg_v2.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_check_fails_when_constant_is_not_two() -> None:
    mod = _import_backfill_module()
    with (
        patch.object(sys, "argv", ["backfill_vcg_v2.py"]),
        patch.object(mod, "COMPOSITE_VERSION", 1),
    ):
        with pytest.raises(RuntimeError, match="COMPOSITE_VERSION == 2"):
            mod.main()


def test_idempotent_when_v2_row_exists_and_no_force(seeded_db_empty_cards) -> None:
    mod = _import_backfill_module()
    conn = seeded_db_empty_cards.conn
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
              (indicator, composite_version, start_date, end_date,
               window_days, n_days, params, summary, note,
               run_scope, composite_method, credit_proxy,
               created_at, completed_at)
            VALUES ('vcg', '2', '2007-01-03', '2024-12-31',
                    252, 4500, '{}'::jsonb, '{}'::jsonb, 'test',
                    'production', 'single_proxy', 'HYG',
                    NOW(), NOW())
            """
        )
    conn.commit()

    info = conn.info
    env = {
        "UW_SCAN_DB_HOST": str(info.host or "127.0.0.1"),
        "UW_SCAN_DB_PORT": str(info.port or 5432),
        "UW_SCAN_DB_NAME": str(info.dbname),
        "UW_SCAN_DB_USER": str(info.user),
        "UW_SCAN_API_KEY": "test-dummy-not-used-by-db-tests",
    }
    if info.password:
        env["UW_SCAN_DB_PASSWORD"] = str(info.password)

    with (
        patch.object(sys, "argv", ["backfill_vcg_v2.py"]),
        patch.dict("os.environ", env, clear=False),
        patch.object(mod.subprocess, "run") as mock_run,
    ):
        rc = mod.main()

    assert rc == 0
    mock_run.assert_not_called()


def test_argv_has_no_composite_version_cli_override() -> None:
    mod = _import_backfill_module()
    argv = mod._build_backtest_argv()
    assert argv == ["uv", "run", "scripts/backtest_vcg.py"]
    assert not any("composite-version" in arg for arg in argv)


def test_subprocess_env_whitelist_blocks_unrelated_secrets() -> None:
    mod = _import_backfill_module()
    leak_env = {
        "UW_SCAN_DB_NAME": "testdb",
        "UW_SCAN_DB_HOST": "localhost",
        "UW_SCAN_DB_USER": "tester",
        "UW_SCAN_API_KEY": "real-key-must-not-pass-through",
        "FMP_API_KEY": "fmp-secret-leak",
        "MASSIVE_API_KEY": "massive-secret-leak",
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
    }
    with patch.dict("os.environ", leak_env, clear=True):
        env = mod._subprocess_env()

    assert env["UW_SCAN_DB_NAME"] == "testdb"
    assert env["UW_SCAN_DB_HOST"] == "localhost"
    assert env["PATH"] == "/usr/bin"
    assert "FMP_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert env["UW_SCAN_API_KEY"] != "real-key-must-not-pass-through"


def test_advisory_lock_serialises_concurrent_invocations(seeded_db_empty_cards) -> None:
    mod = _import_backfill_module()
    repo_conn = seeded_db_empty_cards.conn
    info = repo_conn.info
    dsn_parts = [
        f"host={info.host}" if info.host else "",
        f"port={info.port}" if info.port else "",
        f"dbname={info.dbname}",
        f"user={info.user}",
    ]
    if info.password:
        dsn_parts.append(f"password={info.password}")
    dsn = " ".join(part for part in dsn_parts if part)

    with psycopg.connect(dsn) as holder:
        with holder.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
            assert cur.fetchone()[0] is True

        with repo_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
            assert cur.fetchone()[0] is False

        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (mod._LOCK_KEY,))
        holder.commit()

    with repo_conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (mod._LOCK_KEY,))
