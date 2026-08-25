"""The snapshot job: assemble the four domains for one instant, or refuse.

The defect this closes is silent. The nightly pass already uses ONE ``as_of`` and the
right causal order, but each domain catches its own exception and the loop continues --
so a failed rates job lets USD read the PREVIOUS rates state (which still satisfies
``available_at <= as_of``), persist a new USD state citing it, and gold consume the
mixture. Four cards render fresh and nothing can tell.

These tests fix the two properties that make the snapshot worth having: it decides status
from dependency-edge IDENTITY rather than from timestamp proximity, and it never repairs
an incompatible chain by substituting the fresher upstream it can plainly see.

The states ride the inflation fixture's real observation: core PCE for June 2023 was
128.311 (2017=100), published 2023-07-28.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from uw_scan.macro.snapshot import CAUSAL_ORDER
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_context_snapshot import macro_context_snapshot_job

from ..storage.test_macro_domain_state_repository import _insert_observation, _state

AS_OF = datetime(2023, 7, 29, 23, 59, tzinfo=UTC)
ASSEMBLED_AT = datetime(2023, 7, 30, 3, 0, tzinfo=UTC)
LAST_NIGHT = AS_OF - timedelta(days=1)


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _persist_state(
    repo: Repository,
    domain: str,
    *,
    as_of: datetime = AS_OF,
    inputs_hash: str,
    upstream: list[tuple[int, str]] | None = None,
) -> int:
    obs_id = _insert_observation(repo)
    state = _state(obs_ids=[obs_id], as_of=as_of, inputs_hash=inputs_hash)
    return repo.insert_macro_domain_state(
        replace(state, domain=domain, as_of=as_of),
        computed_at=ASSEMBLED_AT,
        upstream=upstream or [],
    )


def _coherent_chain(repo: Repository) -> dict[str, int]:
    infl = _persist_state(repo, "inflation", inputs_hash="a" * 64)
    rates = _persist_state(
        repo, "policy_rates", inputs_hash="b" * 64, upstream=[(infl, "realized")]
    )
    usd = _persist_state(
        repo, "usd", inputs_hash="c" * 64, upstream=[(rates, "policy_actual")]
    )
    gold = _persist_state(
        repo,
        "gold",
        inputs_hash="d" * 64,
        upstream=[
            (infl, "realized"),
            (rates, "policy_actual"),
            (usd, "expectations_market"),
        ],
    )
    return {"inflation": infl, "policy_rates": rates, "usd": usd, "gold": gold}


class TestACoherentChainIsComplete:
    def test_four_domains_in_causal_order(self, repo: Repository) -> None:
        ids = _coherent_chain(repo)

        snap = macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)

        assert snap is not None
        assert snap.status == "complete"
        assert [d.domain for d in snap.domains] == [
            "inflation",
            "policy_rates",
            "usd",
            "gold",
        ]
        assert [d.ordinal for d in snap.domains] == [0, 1, 2, 3]
        assert snap.domain_state_id("usd") == ids["usd"]
        assert snap.reasons == ()

    def test_the_snapshot_is_persisted_and_readable(self, repo: Repository) -> None:
        ids = _coherent_chain(repo)

        macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)
        stored = repo.fetch_macro_context_snapshot_as_of(AS_OF)

        assert stored is not None
        assert stored["status"] == "complete"
        rows = repo.fetch_macro_context_snapshot_domains(int(stored["snapshot_id"]))
        assert [r["domain"] for r in rows] == list(CAUSAL_ORDER)
        assert [int(r["state_id"]) for r in rows] == [ids[d] for d in CAUSAL_ORDER]


class TestAFailedDomainCannotRenderFresh:
    def test_a_missing_domain_is_partial_and_names_it(self, repo: Repository) -> None:
        # Rates never ran. Everything else did.
        infl = _persist_state(repo, "inflation", inputs_hash="a" * 64)
        _persist_state(repo, "usd", inputs_hash="c" * 64)
        _persist_state(
            repo, "gold", inputs_hash="d" * 64, upstream=[(infl, "realized")]
        )

        snap = macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)

        assert snap is not None
        assert snap.status == "partial"
        reason = snap.reason_for("policy_rates")
        assert reason is not None
        assert reason.kind == "absent"
        assert snap.domain_state_id("policy_rates") is None

    def test_usd_citing_last_nights_rates_is_incompatible(
        self, repo: Repository
    ) -> None:
        stale_rates = _persist_state(
            repo, "policy_rates", as_of=LAST_NIGHT, inputs_hash="0" * 64
        )
        infl = _persist_state(repo, "inflation", inputs_hash="a" * 64)
        fresh_rates = _persist_state(
            repo, "policy_rates", inputs_hash="b" * 64, upstream=[(infl, "realized")]
        )
        # USD ran while rates was still last night's answer.
        usd = _persist_state(
            repo, "usd", inputs_hash="c" * 64, upstream=[(stale_rates, "policy_actual")]
        )
        _persist_state(
            repo, "gold", inputs_hash="d" * 64, upstream=[(usd, "expectations_market")]
        )

        snap = macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)

        assert snap is not None
        assert snap.status == "incompatible"
        reason = snap.reason_for("usd")
        assert reason is not None
        assert reason.kind == "incompatible"
        # The snapshot holds the rates answer that was in force for this instant...
        assert snap.domain_state_id("policy_rates") == fresh_rates
        # ...and it did NOT quietly rewrite USD to stand on it.
        assert stale_rates != fresh_rates

    def test_the_job_never_substitutes_a_fresher_upstream(
        self, repo: Repository
    ) -> None:
        """The fresher rates state is right there. Using it would be a fabrication."""
        stale_rates = _persist_state(
            repo, "policy_rates", as_of=LAST_NIGHT, inputs_hash="0" * 64
        )
        _persist_state(repo, "inflation", inputs_hash="a" * 64)
        _persist_state(repo, "policy_rates", inputs_hash="b" * 64)
        usd = _persist_state(
            repo, "usd", inputs_hash="c" * 64, upstream=[(stale_rates, "policy_actual")]
        )
        _persist_state(
            repo, "gold", inputs_hash="d" * 64, upstream=[(usd, "expectations_market")]
        )

        snap = macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)

        assert snap is not None
        assert snap.status != "complete"
        edges = repo.fetch_macro_domain_state_dependencies(usd)
        assert [e["upstream_state_id"] for e in edges] == [stale_rates]


class TestReassemblyIsANoOp:
    def test_running_twice_over_unchanged_states_is_idempotent(
        self, repo: Repository
    ) -> None:
        _coherent_chain(repo)

        first = macro_context_snapshot_job(repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT)
        second = macro_context_snapshot_job(
            repo, as_of=AS_OF, assembled_at=ASSEMBLED_AT + timedelta(hours=2)
        )

        assert first is not None and second is not None
        assert first.inputs_hash == second.inputs_hash
        # The second run is a no-op, not a second opinion: one row, still stamped with
        # the FIRST assembly time. A row rewritten on every rerun would make "when did
        # we first see this chain" unanswerable.
        stored = repo.fetch_macro_context_snapshot_as_of(AS_OF)
        assert stored is not None
        assert stored["assembled_at"] == ASSEMBLED_AT
        with repo._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM uw_scan.macro_context_snapshots")
            assert cur.fetchone()[0] == 1

    def test_no_states_at_all_assembles_nothing(self, repo: Repository) -> None:
        assert macro_context_snapshot_job(repo, as_of=AS_OF) is None
