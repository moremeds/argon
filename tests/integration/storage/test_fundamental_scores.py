"""Method versioning and immutable score storage (migration 115).

Two contracts under test: exactly one active method version can ever be resolved,
and a score row is never rewritten.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.fundamentals.features import FEATURES
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

ENGINE = "test-v1:aaaaaaaa"
OTHER = "test-v1:bbbbbbbb"


def _repo(seeded) -> FundamentalScoresRepository:
    return FundamentalScoresRepository(seeded.conn, schema=seeded._schema)


def _register(repo: FundamentalScoresRepository, engine: str, w: float = 1.0) -> None:
    repo.register_version(
        engine_version=engine,
        code_version="test-v1",
        param_hash=engine.split(":")[1],
        params=dict.fromkeys(FEATURES, w),
        note="test",
    )


def _row(ticker: str = "NVDA", engine: str = ENGINE, ihash: str = "h1") -> dict:
    return {
        "ticker": ticker,
        "as_of": date(2026, 6, 22),
        "engine_version": engine,
        "inputs_hash": ihash,
        "period_end": date(2026, 4, 30),
        "knowledge_date": date(2026, 5, 21),
        "filing_date_known": True,
        "composite": 0.2881,
        **dict.fromkeys(FEATURES, 1.0),
        "features_present": 7,
        "source_obs_ids": [1, 2, 3],
    }


def test_active_version_is_none_before_seeding(seeded_db_empty_cards):
    """The scoring job gates on this: no active version must read as 'refuse to
    score', not as a crash or a silent default method."""
    assert _repo(seeded_db_empty_cards).active_version() is None


def test_register_and_activate(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    repo.activate(ENGINE)
    assert repo.active_version() == ENGINE
    assert repo.params(ENGINE) == dict.fromkeys(FEATURES, 1.0)


def test_activation_replaces_rather_than_accumulates(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    _register(repo, OTHER, w=2.0)
    repo.activate(ENGINE)
    repo.activate(OTHER)
    assert repo.active_version() == OTHER
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {seeded_db_empty_cards._schema}.fundamental_method_state"
        )
        assert cur.fetchone()[0] == 1


def test_method_state_refuses_delete(seeded_db_empty_cards):
    """`CHECK (singleton_id = 1)` constrains the row's VALUE, not its EXISTENCE —
    it permits DELETE, which would leave every computation method-less. The
    trigger is what closes that hole."""
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    repo.activate(ENGINE)
    with pytest.raises(psycopg.errors.RaiseException):
        with seeded_db_empty_cards.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {seeded_db_empty_cards._schema}.fundamental_method_state"
            )
    seeded_db_empty_cards.conn.rollback()
    assert repo.active_version() == ENGINE


def test_params_are_immutable_under_a_live_version(seeded_db_empty_cards):
    """Re-registering must not edit parameters: that would silently reinterpret
    every score already computed under the version."""
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE, w=1.0)
    _register(repo, ENGINE, w=99.0)
    assert repo.params(ENGINE) == dict.fromkeys(FEATURES, 1.0)


def test_scores_are_immutable_and_insert_is_idempotent(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    repo.activate(ENGINE)

    assert repo.insert_scores([_row()]) == 1
    # Same identity, different composite — the ORIGINAL must survive untouched.
    assert repo.insert_scores([dict(_row(), composite=99.0)]) == 0
    got = repo.latest_for_ticker("NVDA")
    assert float(got["composite"]) == pytest.approx(0.2881)


def test_a_different_inputs_hash_is_a_different_result(seeded_db_empty_cards):
    """A restatement changes the inputs while as_of and engine_version stay put;
    without inputs_hash in the key the second result would be lost."""
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    repo.activate(ENGINE)
    assert repo.insert_scores([_row(ihash="h1")]) == 1
    assert repo.insert_scores([dict(_row(ihash="h2"), composite=0.5)]) == 1


def test_empty_insert_is_a_noop(seeded_db_empty_cards):
    assert _repo(seeded_db_empty_cards).insert_scores([]) == 0


def test_ranking_orders_by_composite_and_ignores_other_versions(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    _register(repo, OTHER, w=2.0)
    repo.activate(ENGINE)
    repo.insert_scores(
        [
            dict(_row("AAA", ihash="a"), composite=1.0),
            dict(_row("BBB", ihash="b"), composite=3.0),
            dict(_row("CCC", ihash="c"), composite=2.0),
            # Same names under an inactive version must not leak into the ranking.
            dict(_row("ZZZ", engine=OTHER, ihash="z"), composite=99.0),
        ]
    )
    assert [r["ticker"] for r in repo.ranking()] == ["BBB", "CCC", "AAA"]


def test_ranking_puts_unscored_names_last(seeded_db_empty_cards):
    """A name with too few features has a NULL composite; it must sort to the end
    rather than to the top on a NULL comparison."""
    repo = _repo(seeded_db_empty_cards)
    _register(repo, ENGINE)
    repo.activate(ENGINE)
    repo.insert_scores(
        [
            dict(_row("AAA", ihash="a"), composite=1.0),
            dict(_row("NUL", ihash="n"), composite=None, features_present=2),
        ]
    )
    assert [r["ticker"] for r in repo.ranking()] == ["AAA", "NUL"]


def test_latest_for_ticker_returns_none_without_an_active_version(
    seeded_db_empty_cards,
):
    assert _repo(seeded_db_empty_cards).latest_for_ticker("NVDA") is None
