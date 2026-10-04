"""Migration 159's widened ``external_api_requests_provider_check``, on real Postgres.

- every provider the source telemetry path emits inserts a row;
- an unknown provider still raises ``CheckViolation``;
- re-applying the full migration chain (what every API boot does) leaves
  ``pg_get_constraintdef`` byte-identical and ``convalidated`` false — the
  LIKE-ALL guard makes the second apply a catalog lookup, not a rebuild.

Uses ``seeded_db_empty_cards`` (session migrate + per-test TRUNCATE+COPY
baseline), so the assertions run against the post-migration schema production
boots into.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.migrate_runner import MIGRATIONS_DIR, apply_migrations

pytestmark = pytest.mark.integration

MIGRATION_159 = MIGRATIONS_DIR / "159_external_api_requests_provider_check.sql"


def _allowed_providers() -> list[str]:
    """Provider literals straight from migration 159's CHECK list — the test
    covers exactly what the file permits, so it cannot drift from the SQL."""
    sql = MIGRATION_159.read_text()
    m = re.search(r"provider\s+IN\s*\(([^)]*)\)", sql)
    assert m, "migration 159 lost its CHECK (provider IN (...)) list"
    return sorted(set(re.findall(r"'([a-z_0-9]+)'", m.group(1))))


ALLOWED_PROVIDERS = _allowed_providers()


def _test_settings() -> Settings:
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _run_migrations(settings: Settings) -> None:
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        apply_migrations(conn, log=lambda _msg: None)


def _insert_request(repo, provider: str) -> int:
    now = datetime.now(timezone.utc)
    return repo.insert_external_api_request(
        provider=provider,
        endpoint_key="provider-check-test",
        method="GET",
        path="/provider-check",
        status_family="2xx",
        started_at=now - timedelta(milliseconds=5),
        finished_at=now,
        latency_ms=5,
        job_name="provider_check_test",
    )


def _provider_check_state(conn) -> tuple[int, str, bool]:
    row = conn.execute(
        "SELECT oid, pg_get_constraintdef(oid), convalidated "
        "FROM pg_constraint "
        "WHERE conname = 'external_api_requests_provider_check' "
        "  AND conrelid = 'uw_scan.external_api_requests'::regclass"
    ).fetchone()
    assert row is not None, "external_api_requests_provider_check missing"
    return int(row[0]), str(row[1]), bool(row[2])


@pytest.mark.parametrize("provider", ALLOWED_PROVIDERS)
def test_every_telemetry_provider_inserts(seeded_db_empty_cards, provider: str):
    repo = seeded_db_empty_cards
    request_id = _insert_request(repo, provider)
    assert request_id > 0


def test_unknown_provider_still_rejected(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with pytest.raises(psycopg.errors.CheckViolation):
        with repo.conn.transaction():
            _insert_request(repo, "bogus")


def test_reapply_leaves_provider_check_unchanged(seeded_db_empty_cards):
    """Second boot's replay is a no-op: same constraint (oid), same def, still
    NOT VALID. A drop + re-add would keep the def but change the oid."""
    repo = seeded_db_empty_cards
    before_oid, before_def, before_validated = _provider_check_state(repo.conn)
    assert before_validated is False

    _run_migrations(_test_settings())

    after_oid, after_def, after_validated = _provider_check_state(repo.conn)
    assert after_oid == before_oid
    assert after_def == before_def
    assert after_validated is False
