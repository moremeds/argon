from __future__ import annotations

import logging
import os
from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.provider_usage import (
    ExternalApiRequestEvent,
    ExternalApiRequestRecorder,
)
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )


@pytest.fixture
def settings(seeded_db_empty_cards) -> Settings:
    # seeded_db_empty_cards triggers the session migration + per-test baseline
    # restore. This fixture only needs the resolved Settings — the recorder
    # opens its own connection from the DSN, distinct from the fixture's repo.
    return _test_settings()


def _event() -> ExternalApiRequestEvent:
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    return ExternalApiRequestEvent(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=42,
        official_daily_count=15,
    )


def test_recorder_keeps_run_id_when_scan_run_is_uncommitted(settings: Settings):
    main_conn = psycopg.connect(settings.db_dsn())
    try:
        main_repo = Repository(main_conn)
        run_id = main_repo.insert_scan_run("TSLA")

        with ExternalApiRequestRecorder(
            settings.db_dsn(), schema=settings.db_schema
        ) as recorder:
            recorder.record(replace(_event(), run_id=run_id))

        main_conn.rollback()
    finally:
        main_conn.close()

    with psycopg.connect(settings.db_dsn()) as conn:
        rows = Repository(conn).list_external_api_requests(
            provider="uw",
            start=datetime(2026, 5, 14, 0, 0, tzinfo=UTC),
            end=datetime(2026, 5, 15, 0, 0, tzinfo=UTC),
        )

    assert len(rows) == 1
    assert rows[0].run_id == run_id


def test_recorder_inserts_through_autocommit_connection(settings: Settings):
    with ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema) as recorder:
        recorder.record(_event())

    with psycopg.connect(settings.db_dsn()) as conn:
        count = Repository(conn).get_external_api_usage_summary(
            "uw",
            datetime(2026, 5, 14, 0, 0, tzinfo=UTC),
            datetime(2026, 5, 15, 0, 0, tzinfo=UTC),
        ).total_requests

    assert count == 1


def test_recorder_row_survives_main_connection_rollback(settings: Settings):
    main_conn = psycopg.connect(settings.db_dsn())
    try:
        main_repo = Repository(main_conn)
        main_repo.insert_scan_run("TSLA")
        with ExternalApiRequestRecorder(
            settings.db_dsn(), schema=settings.db_schema
        ) as recorder:
            recorder.record(_event())
        main_conn.rollback()
    finally:
        main_conn.close()

    with psycopg.connect(settings.db_dsn()) as conn:
        count = Repository(conn).get_external_api_usage_summary(
            "uw",
            datetime(2026, 5, 14, 0, 0, tzinfo=UTC),
            datetime(2026, 5, 15, 0, 0, tzinfo=UTC),
        ).total_requests

    assert count == 1


def test_recorder_logs_and_swallows_insert_failures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    with ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema) as recorder:

        def _boom(**_kwargs):
            raise RuntimeError("telemetry insert failed")

        monkeypatch.setattr(recorder._repo, "insert_external_api_request", _boom)
        caplog.set_level(logging.ERROR, logger="uw_scan.storage.provider_usage")

        recorder.record(_event())

    assert "failed to record external API request telemetry" in caplog.text
