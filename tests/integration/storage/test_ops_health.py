import pytest
from uw_scan.storage.ops_health import JobFailuresRepository

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_streak_increments_then_resets(repo):
    jf = JobFailuresRepository(repo.conn)
    jf.record_failure("full_scan", "boom")
    jf.record_failure("full_scan", "boom again")
    repo.conn.commit()
    rows = {r.job_name: r for r in jf.list_streaks()}
    assert rows["full_scan"].consecutive == 2
    assert rows["full_scan"].last_error == "boom again"

    jf.record_success("full_scan")
    repo.conn.commit()
    assert jf.list_streaks(min_streak=1) == []
