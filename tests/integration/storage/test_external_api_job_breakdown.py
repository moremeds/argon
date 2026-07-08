from datetime import UTC, datetime, timedelta

import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_job_breakdown_groups_by_job_name(repo):
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    for job in ("full_scan", "cockpit_daily_snapshot"):
        repo.insert_external_api_request(
            provider="uw",
            endpoint_key="iv_rank",
            method="GET",
            path_template="/api/stock/{ticker}/iv-rank",
            path="/api/stock/TSLA/iv-rank",
            ticker="TSLA",
            params={},
            status_code=200,
            status_family="2xx",
            started_at=now,
            finished_at=now,
            latency_ms=42,
            official_daily_count=10,
            official_daily_limit=1000,
            job_name=job,
        )
    repo.conn.commit()
    # positional (provider, start, end) — mirrors list_external_api_ticker_usage
    rows = repo.list_external_api_job_usage(
        "uw", now - timedelta(days=1), now + timedelta(days=1)
    )
    assert {r.key for r in rows} >= {"full_scan", "cockpit_daily_snapshot"}
