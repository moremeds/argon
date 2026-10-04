"""``macro_fred_series_ingest_job`` failure boundary: the job FAILS (raises) only
when every series it tried failed — the all-failed case is a dead run that
job_failures must see, while one dead series among many is a degraded success.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.worker.jobs.macro_series_ingest import macro_fred_series_ingest_job

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "macro"


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


class _Provider:
    """Serves frozen payloads; a series id it does not hold raises like a dead feed."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads

    def __enter__(self) -> "_Provider":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def fetch_series_payload(
        self,
        series_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        realtime_start: date | None = None,
        realtime_end: date | None = None,
    ) -> tuple[bytes, str]:
        if series_id not in self._payloads:
            raise RuntimeError("fred 503")
        return (
            self._payloads[series_id],
            f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}",
        )


def _fred_status(settings: Settings) -> tuple:
    with psycopg.connect(settings.db_dsn()) as conn:
        row = conn.execute(
            "SELECT status FROM uw_scan.macro_source_status WHERE source = 'fred'"
        ).fetchone()
    assert row is not None, "the status upsert must be committed before any raise"
    return tuple(row)


def test_a_partial_failure_returns_degraded(seeded_db_empty_cards) -> None:
    """One dead series among interchangeable units is a degraded run, not a job
    failure: the job returns, the failed series is named, 'fred' is degraded."""
    settings = _settings()
    result = macro_fred_series_ingest_job(
        dsn=settings.db_dsn(),
        api_key="unused-by-the-stub",
        series=("CPIAUCSL", "DEAD_SERIES"),
        provider_factory=lambda: _Provider(
            {"CPIAUCSL": (FIXTURES / "fred_cpi_vintages.json").read_bytes()}
        ),
        max_attempts=1,
    )

    assert result.status == "degraded"
    assert result.series_succeeded == 1
    assert result.failed_series == ("DEAD_SERIES",)
    assert _fred_status(settings) == ("degraded",)


def test_every_series_failed_raises_after_status_commit(seeded_db_empty_cards) -> None:
    """Every series dead is a dead run: raise AFTER the status commit so the
    streak sees it while the 'degraded' row stays queryable as the reason."""
    settings = _settings()
    with pytest.raises(RuntimeError, match="2 of 2 series failed"):
        macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("DEAD_A", "DEAD_B"),
            provider_factory=lambda: _Provider({}),
            max_attempts=1,
        )

    assert _fred_status(settings) == ("degraded",)
