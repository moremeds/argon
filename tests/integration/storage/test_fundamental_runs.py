"""The run ledger (migration 137) — what was asked, not just what came back.

`fundamental_scores` records an ANSWER. Without this table, a run that produced
nothing leaves no trace, so "the panel was empty" and "the job never ran" are
indistinguishable afterwards — and the report product (M7) has no way to say
which computation an answer came from.
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.fundamental_runs import (
    MODE_COMPUTE,
    STAGE_SCORING,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    FundamentalRunsRepository,
    request_hash,
)

SCOPE = {"tier": "ranked"}


def _repo(seeded) -> FundamentalRunsRepository:
    return FundamentalRunsRepository(seeded.conn, schema=seeded._schema)


def _args(**over):
    base = dict(
        scope_kind="universe",
        scope=SCOPE,
        evidence_policy="true_pit_only",
        as_of=date(2024, 6, 30),
        engine_version="fundamentals-v2:77aea364",
    )
    base.update(over)
    return base


def test_the_request_hash_excludes_the_clock_but_not_the_contract():
    """A second later asking the same question is the SAME question."""
    a = request_hash(**_args())
    assert a == request_hash(**_args())
    for field, value in (
        ("as_of", date(2024, 9, 30)),
        ("evidence_policy", "capture_bounded"),
        ("engine_version", "fundamentals-v1:77aea364"),
        ("scope", {"tier": "core"}),
    ):
        assert request_hash(**_args(**{field: value})) != a, field


def test_a_second_request_while_one_is_active_returns_that_run(seeded_db_empty_cards):
    """Not an error: the caller asked something already being answered."""
    r = _repo(seeded_db_empty_cards)
    first, created_a = r.enqueue(**_args(), mode=MODE_COMPUTE)
    second, created_b = r.enqueue(**_args(), mode=MODE_COMPUTE)
    assert created_a is True
    assert created_b is False
    assert first == second


def test_a_finished_run_no_longer_blocks_the_next_one(seeded_db_empty_cards):
    """Otherwise the active-run index would make a question askable exactly once."""
    r = _repo(seeded_db_empty_cards)
    first, _ = r.enqueue(**_args())
    r.finish(first, status=STATUS_SUCCEEDED, counters={"scored": 10})
    second, created = r.enqueue(**_args())
    assert created is True
    assert second != first


def test_reuse_matches_the_contract_exactly_or_not_at_all(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    run_id, _ = r.enqueue(**_args())
    r.finish(run_id, status=STATUS_SUCCEEDED, counters={"scored": 10})

    assert r.latest_succeeded(**_args())["run_id"] == run_id
    # A different as-of is a different question; answering it with this run would
    # silently hand back someone else's answer.
    assert r.latest_succeeded(**_args(as_of=date(2023, 6, 30))) is None
    assert r.latest_succeeded(**_args(evidence_policy="capture_bounded")) is None


def test_a_failed_run_is_not_reused(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    run_id, _ = r.enqueue(**_args())
    r.finish(run_id, status=STATUS_FAILED, error="boom")
    assert r.latest_succeeded(**_args()) is None


def test_a_stage_retry_gets_its_own_attempt(seeded_db_empty_cards):
    """A status column can say 'failed'; it cannot say 'failed on attempt 2'."""
    r = _repo(seeded_db_empty_cards)
    run_id, _ = r.enqueue(**_args())
    first = r.stage_start(run_id, STAGE_SCORING)
    r.stage_finish(first, status=STATUS_FAILED, error="transient")
    second = r.stage_start(run_id, STAGE_SCORING)
    r.stage_finish(second, status=STATUS_SUCCEEDED, counters={"scored": 5})

    stages = r.stages(run_id)
    assert [s["attempt"] for s in stages] == [1, 2]
    assert [s["status"] for s in stages] == ["failed", "succeeded"]


def test_finish_refuses_a_non_terminal_status(seeded_db_empty_cards):
    import pytest

    r = _repo(seeded_db_empty_cards)
    run_id, _ = r.enqueue(**_args())
    with pytest.raises(ValueError, match="not terminal"):
        r.finish(run_id, status="running")


def test_a_heartbeat_corpse_is_cancellable_and_unblocks_the_request(
    seeded_db_empty_cards,
):
    """A wedged run holds its request_hash forever through the active index."""
    seeded = seeded_db_empty_cards
    r = _repo(seeded)
    run_id, _ = r.enqueue(**_args())
    r.start(run_id)
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"""UPDATE {seeded._schema}.fundamental_runs
                   SET heartbeat_at = now() - interval '2 hours',
                       requested_at = now() - interval '2 hours'
                 WHERE run_id = %s""",
            (run_id,),
        )
    seeded.conn.commit()

    assert r.queue_health()["stalled"] == 1
    assert r.cancel_stale() == 1
    assert r.get(run_id)["status"] == "cancelled"
    _, created = r.enqueue(**_args())
    assert created is True


def test_queue_health_separates_busy_from_wedged(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    run_id, _ = r.enqueue(**_args())
    r.start(run_id)
    health = r.queue_health()
    assert health["running"] == 1
    assert health["stalled"] == 0, "a fresh heartbeat is busy, not wedged"
