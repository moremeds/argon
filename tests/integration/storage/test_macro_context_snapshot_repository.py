"""Persistence contract for the macro context snapshot (migration 130).

The four domain states already exist and already record what they stood on. What did not
exist is a row that says "these four, together, are one answer" -- so the page composed
four independent latest reads and could render a partially-failed chain as four fresh
cards. The snapshot is the object that can refuse.

These tests fix the properties that make the refusal trustworthy: a snapshot names states
that exist, holds each domain at most once, cannot be assembled before the instant it
answers for, and re-assembling the same identity is a no-op rather than a second opinion.

The states are real: core PCE for June 2023 was 128.311 (2017=100), published 2023-07-28,
frozen in ``tests/fixtures/macro/inflation_rates_golden.json``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from uw_scan.macro.snapshot import MacroContextSnapshot, SnapshotDomain, SnapshotReason
from uw_scan.storage.repository import Repository

from .test_macro_domain_state_repository import _insert_observation, _state

AS_OF = datetime(2023, 7, 28, 23, 59, tzinfo=UTC)
ASSEMBLED_AT = datetime(2023, 7, 29, 3, 0, tzinfo=UTC)
ASSEMBLER = "snapshot/1"


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _state_id(repo: Repository, domain: str, *, inputs_hash: str) -> int:
    """Persist one domain state and return its id.

    Every domain rides the inflation fixture's observation: this file tests the SNAPSHOT's
    contract, and which series a state stood on is the state's own contract, already
    covered next door.
    """
    obs_id = _insert_observation(repo)
    state = _state(obs_ids=[obs_id], inputs_hash=inputs_hash)
    return repo.insert_macro_domain_state(
        replace(state, domain=domain), computed_at=ASSEMBLED_AT
    )


def _snapshot(
    *,
    domains: tuple[SnapshotDomain, ...],
    status: str = "complete",
    as_of: datetime = AS_OF,
    assembled_at: datetime = ASSEMBLED_AT,
    inputs_hash: str = "c" * 64,
    reasons: tuple[SnapshotReason, ...] = (),
) -> MacroContextSnapshot:
    return MacroContextSnapshot(
        as_of=as_of,
        assembled_at=assembled_at,
        status=status,
        reasons=reasons,
        domains=domains,
        inputs_hash=inputs_hash,
        assembler_version=ASSEMBLER,
    )


class TestASnapshotIsOneAnswer:
    def test_it_round_trips_with_its_domain_rows(self, repo: Repository) -> None:
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        rates = _state_id(repo, "policy_rates", inputs_hash="b" * 64)
        snap_id = repo.insert_macro_context_snapshot(
            _snapshot(
                domains=(
                    SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),
                    SnapshotDomain(domain="policy_rates", state_id=rates, ordinal=1),
                )
            )
        )

        row = repo.fetch_macro_context_snapshot(snap_id)
        assert row is not None
        assert row["status"] == "complete"
        assert row["as_of"] == AS_OF
        got = repo.fetch_macro_context_snapshot_domains(snap_id)
        assert [(d["domain"], d["state_id"]) for d in got] == [
            ("inflation", infl),
            ("policy_rates", rates),
        ]

    def test_the_reasons_survive_the_round_trip(self, repo: Repository) -> None:
        # A refusal nobody can read is not a refusal.
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        snap_id = repo.insert_macro_context_snapshot(
            _snapshot(
                domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),),
                status="partial",
                reasons=(
                    SnapshotReason(
                        domain="policy_rates", kind="absent", detail="job raised TimeoutError"
                    ),
                ),
            )
        )
        row = repo.fetch_macro_context_snapshot(snap_id)
        assert row["status"] == "partial"
        assert row["status_reasons_jsonb"] == [
            {"domain": "policy_rates", "kind": "absent", "detail": "job raised TimeoutError"}
        ]

    def test_a_partial_snapshot_holds_only_the_domains_that_answered(
        self, repo: Repository
    ) -> None:
        # Absence is the lack of a row, not a row carrying a null. A nullable state_id
        # would make every reader decide again what a null means.
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        snap_id = repo.insert_macro_context_snapshot(
            _snapshot(
                domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),),
                status="partial",
            )
        )
        assert len(repo.fetch_macro_context_snapshot_domains(snap_id)) == 1


class TestTheSnapshotCannotLie:
    def test_it_cannot_name_a_state_that_does_not_exist(self, repo: Repository) -> None:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repo.insert_macro_context_snapshot(
                _snapshot(
                    domains=(
                        SnapshotDomain(domain="inflation", state_id=9_999_999, ordinal=0),
                    )
                )
            )

    def test_one_domain_appears_at_most_once(self, repo: Repository) -> None:
        # Two answers for one domain in one snapshot is two snapshots.
        a = _state_id(repo, "inflation", inputs_hash="a" * 64)
        b = _state_id(repo, "inflation", inputs_hash="b" * 64)
        with pytest.raises(psycopg.errors.UniqueViolation):
            repo.insert_macro_context_snapshot(
                _snapshot(
                    domains=(
                        SnapshotDomain(domain="inflation", state_id=a, ordinal=0),
                        SnapshotDomain(domain="inflation", state_id=b, ordinal=1),
                    )
                )
            )

    def test_an_unknown_status_is_refused(self, repo: Repository) -> None:
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        with pytest.raises(psycopg.errors.CheckViolation):
            repo.insert_macro_context_snapshot(
                _snapshot(
                    domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),),
                    status="probably_fine",
                )
            )

    def test_it_cannot_be_assembled_before_the_instant_it_answers_for(
        self, repo: Repository
    ) -> None:
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        with pytest.raises(psycopg.errors.CheckViolation):
            repo.insert_macro_context_snapshot(
                _snapshot(
                    domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),),
                    assembled_at=AS_OF - timedelta(seconds=1),
                )
            )


class TestReassemblyIsNotASecondOpinion:
    def test_the_same_identity_returns_the_same_row(self, repo: Repository) -> None:
        # Same instant, same assembler, same inputs -> one snapshot. Otherwise every
        # nightly rerun would manufacture a new "answer" identical to the last.
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        args = _snapshot(
            domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),)
        )
        first = repo.insert_macro_context_snapshot(args)
        second = repo.insert_macro_context_snapshot(args)
        assert first == second

    def test_a_different_inputs_hash_is_a_different_snapshot(
        self, repo: Repository
    ) -> None:
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        domains = (SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),)
        first = repo.insert_macro_context_snapshot(_snapshot(domains=domains))
        second = repo.insert_macro_context_snapshot(
            _snapshot(domains=domains, inputs_hash="d" * 64)
        )
        assert first != second

    def test_the_newest_snapshot_at_or_before_an_instant_is_readable(
        self, repo: Repository
    ) -> None:
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        domains = (SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),)
        older = repo.insert_macro_context_snapshot(
            _snapshot(domains=domains, as_of=AS_OF - timedelta(days=1))
        )
        newer = repo.insert_macro_context_snapshot(_snapshot(domains=domains))

        assert repo.fetch_macro_context_snapshot_as_of(AS_OF)["snapshot_id"] == newer
        at_older = repo.fetch_macro_context_snapshot_as_of(AS_OF - timedelta(hours=1))
        assert at_older["snapshot_id"] == older

    def test_replaying_before_any_snapshot_existed_returns_nothing(
        self, repo: Repository
    ) -> None:
        # Not an empty snapshot -- an invented "we knew nothing" row is a claim we never made.
        infl = _state_id(repo, "inflation", inputs_hash="a" * 64)
        repo.insert_macro_context_snapshot(
            _snapshot(domains=(SnapshotDomain(domain="inflation", state_id=infl, ordinal=0),))
        )
        assert repo.fetch_macro_context_snapshot_as_of(AS_OF - timedelta(days=365)) is None
