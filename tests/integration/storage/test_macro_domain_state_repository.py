"""Persistence contract for macro domain states (migration 125).

A state is a claim about a moment: "core PCE was WELL_ABOVE_TARGET and falling on
2023-07-28, and here is how much of what we would need to know we actually had."  Storing
it is only worth doing if it can be argued with later, so these tests fix the two
properties that make that possible -- the answer cannot drift under a fixed method
identity, and the evidence it names cannot include anything published after the instant
the state answers for.

Values are real ALFRED vintages frozen in ``tests/fixtures/macro/inflation_rates_golden.json``:
core PCE for June 2023 was 128.311 (2017=100) and the University of Michigan year-ahead
expectation was 3.3 percent, both readable on 2023-07-28.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.macro.contracts import (
    ConfidenceTerm,
    Contradiction,
    Direction,
    DomainObservation,
    EvidenceRef,
    FactorState,
    MacroDomainState,
    MacroSubState,
    Velocity,
)
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)
from uw_scan.storage.macro_domain_state import macro_domain_state_from_row
from uw_scan.storage.repository import Repository

# The June 2023 core PCE release: BEA published it on 2023-07-28.
CORE_PCE_PERIOD = date(2023, 6, 1)
CORE_PCE_VALUE = Decimal("128.311")
PUBLISHED_AT = datetime(2023, 7, 28, tzinfo=UTC)
AS_OF = datetime(2023, 7, 28, 23, 59, tzinfo=UTC)
COMPUTED_AT = datetime(2023, 7, 29, 3, 0, tzinfo=UTC)


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _insert_observation(
    repo: Repository,
    *,
    series_id: str = "PCEPILFE",
    value: Decimal = CORE_PCE_VALUE,
    unit: str = "index_2017_100_sa",
    period_end: date = CORE_PCE_PERIOD,
    available_at: datetime = PUBLISHED_AT,
    quality_status: str = "valid",
) -> int:
    """Insert one real published value and return the obs_id an evidence row must cite."""
    raw_json = {
        "series": series_id,
        "value": str(value),
        "period": period_end.isoformat(),
    }
    content_hash, content_length = macro_artifact_content_identity(raw_json=raw_json)
    record_id = (
        f"{series_id}-{period_end.isoformat()}-{available_at.date().isoformat()}"
    )
    repo.insert_macro_artifact(
        source="fred",
        source_kind="first_party_publisher",
        source_record_id=record_id,
        source_url=f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}",
        published_at=available_at,
        available_at=available_at,
        retrieved_at=available_at,
        content_hash=content_hash,
        parser_version="fred_macro/1",
        quality_status="valid",
        cost_class="free_publisher",
        media_type="application/json",
        content_length=content_length,
        raw_json=raw_json,
    )
    artifact_id = _artifact_id(repo, record_id)
    row: dict[str, object] = {
        "artifact_id": artifact_id,
        "domain": "inflation",
        "series_id": series_id,
        "period_end": period_end,
        "frequency": "monthly",
        "unit": unit,
        "value_numeric": value,
        "value_text": None,
        "value_json": None,
        "source": "fred",
        "source_record_id": record_id,
        "published_at": available_at,
        "available_at": available_at,
        "parser_version": "fred_macro/1",
        "quality_status": quality_status,
        "cost_class": "free_publisher",
    }
    row["content_hash"] = macro_observation_content_hash(row)
    repo.insert_macro_observations([row], seen_at=available_at)
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT obs_id FROM uw_scan.macro_observations "
            "WHERE series_id = %s AND period_end = %s AND available_at = %s",
            (series_id, period_end, available_at),
        )
        return int(cur.fetchone()[0])


def _artifact_id(repo: Repository, source_record_id: str) -> int:
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT artifact_id FROM uw_scan.macro_source_artifacts "
            "WHERE source = 'fred' AND source_record_id = %s",
            (source_record_id,),
        )
        return int(cur.fetchone()[0])


def _state(
    *,
    obs_ids: list[int],
    as_of: datetime = AS_OF,
    state: str = "WELL_ABOVE_TARGET",
    direction: Direction = "FALLING",
    confidence: Decimal = Decimal("0.72"),
    inputs_hash: str = "a" * 64,
    engine_version: str = "inflation/1",
    notes: tuple[str, ...] = (),
    sub_states: tuple[MacroSubState, ...] = (),
) -> MacroDomainState:
    return MacroDomainState(
        domain="inflation",
        state=state,
        direction=direction,
        velocity=(
            Velocity(
                metric="core_pce_yoy_change",
                value=Decimal("-0.42"),
                unit="pp",
                window_months=3,
            ),
        ),
        confidence=confidence,
        confidence_reasons=(
            ConfidenceTerm(
                term="completeness",
                value=Decimal("0.875"),
                detail="7 of 8 required series present",
            ),
        ),
        contradictions=(
            Contradiction(
                rule="headline_core_divergence",
                detail="headline 3.0pp below core",
            ),
        ),
        factors=(
            FactorState(
                name="core_pce",
                causal_role="realized",
                series_id="PCEPILFE",
                period_end=CORE_PCE_PERIOD,
                value=CORE_PCE_VALUE,
                unit="index_2017_100_sa",
                direction="FALLING",
                change_over_window=Decimal("-0.42"),
                available_at=PUBLISHED_AT,
                age_days=0,
                freshness=Decimal("1"),
                quality_status="valid",
                source="fred",
                source_kind="first_party_publisher",
            ),
        ),
        evidence_refs=tuple(
            EvidenceRef(
                series_id="PCEPILFE" if index == 0 else "MICH",
                period_end=CORE_PCE_PERIOD,
                causal_role="realized" if index == 0 else "expectations_survey",
                available_at=PUBLISHED_AT,
                obs_id=obs_id,
            )
            for index, obs_id in enumerate(obs_ids)
        ),
        engine_version=engine_version,
        inputs_hash=inputs_hash,
        as_of=as_of,
        notes=notes,
        sub_states=sub_states,
    )


class TestRoundTrip:
    def test_a_state_can_be_reconstructed_from_its_evidence(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        survey = _insert_observation(
            repo, series_id="MICH", value=Decimal("3.3"), unit="percent"
        )

        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core, survey]), computed_at=COMPUTED_AT
        )

        evidence = repo.fetch_macro_domain_state_evidence(state_id)
        assert [row["series_id"] for row in evidence] == ["PCEPILFE", "MICH"]
        assert [row["causal_role"] for row in evidence] == [
            "realized",
            "expectations_survey",
        ]
        assert evidence[0]["value_numeric"] == CORE_PCE_VALUE
        assert evidence[1]["value_numeric"] == Decimal("3.3")

    def test_decimals_survive_the_json_round_trip_exactly(
        self, repo: Repository
    ) -> None:
        """A float round trip would move the last digits of a number whose whole point
        is being reproducible from an audit trail."""
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        stored = repo.fetch_macro_domain_state(state_id)
        assert stored is not None
        assert stored["confidence"] == Decimal("0.72")
        assert stored["confidence_reasons_jsonb"][0]["value"] == "0.875"
        assert stored["factors_jsonb"][0]["value"] == "128.311"
        assert stored["velocity_jsonb"][0]["value"] == "-0.42"

    def test_computed_at_stays_distinct_from_as_of(self, repo: Repository) -> None:
        """Collapsing them would make every backfilled replay look known in real time."""
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        stored = repo.fetch_macro_domain_state(state_id)
        assert stored is not None
        assert stored["as_of"] == AS_OF
        assert stored["computed_at"] == COMPUTED_AT


class TestMethodIdentity:
    def test_recomputing_an_unchanged_state_is_a_no_op(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        first = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )
        second = repo.insert_macro_domain_state(
            _state(obs_ids=[core]),
            computed_at=datetime(2023, 8, 1, 3, tzinfo=UTC),
        )

        assert first == second
        with repo._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM uw_scan.macro_domain_states")
            assert cur.fetchone()[0] == 1

    def test_the_same_inputs_producing_a_different_answer_is_refused(
        self, repo: Repository
    ) -> None:
        """If (domain, as_of, engine, inputs_hash) does not determine the answer, the
        identity is a lie and appending a second row would hide a nondeterministic
        engine behind two equally-authoritative rows."""
        core = _insert_observation(repo)
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        with pytest.raises(ValueError, match="different answer from identical inputs"):
            repo.insert_macro_domain_state(
                _state(obs_ids=[core], direction="RISING"), computed_at=COMPUTED_AT
            )

    def test_a_changed_threshold_makes_a_new_state_without_erasing_the_old(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        original = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )
        recalibrated = repo.insert_macro_domain_state(
            _state(obs_ids=[core], inputs_hash="b" * 64, state="ABOVE_TARGET"),
            computed_at=COMPUTED_AT,
        )

        assert original != recalibrated
        assert repo.fetch_macro_domain_state(original) is not None
        assert repo.fetch_macro_domain_state(recalibrated) is not None

    def test_the_same_identity_may_not_name_different_observations(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        survey = _insert_observation(
            repo, series_id="MICH", value=Decimal("3.3"), unit="percent"
        )
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        with pytest.raises(ValueError, match="different evidence set"):
            repo.insert_macro_domain_state(
                _state(obs_ids=[core, survey]), computed_at=COMPUTED_AT
            )


class TestLookaheadIsRefusedByTheDatabase:
    """The constraint the milestone exists for, enforced below the application."""

    def test_evidence_published_after_the_state_as_of_is_rejected(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        # BEA published this number on 2023-07-28; a state answering for the 27th
        # cannot have stood on it.
        premature = _state(obs_ids=[core], as_of=datetime(2023, 7, 27, tzinfo=UTC))

        with pytest.raises(
            psycopg.errors.CheckViolation, match="after the state as_of"
        ):
            repo.insert_macro_domain_state(premature, computed_at=COMPUTED_AT)

    def test_nothing_is_written_when_the_lookahead_guard_fires(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        with pytest.raises(psycopg.errors.CheckViolation):
            repo.insert_macro_domain_state(
                _state(obs_ids=[core], as_of=datetime(2023, 7, 27, tzinfo=UTC)),
                computed_at=COMPUTED_AT,
            )

        with repo._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM uw_scan.macro_domain_states")
            assert cur.fetchone()[0] == 0

    def test_a_quarantined_observation_may_not_support_a_state(
        self, repo: Repository
    ) -> None:
        bad = _insert_observation(repo, quality_status="quarantined")

        with pytest.raises(psycopg.errors.CheckViolation, match="quality_status"):
            repo.insert_macro_domain_state(
                _state(obs_ids=[bad]), computed_at=COMPUTED_AT
            )


class TestEvidenceIsMandatory:
    def test_a_state_without_persisted_observations_is_refused(
        self, repo: Repository
    ) -> None:
        with pytest.raises(ValueError, match="must name the observations"):
            repo.insert_macro_domain_state(_state(obs_ids=[]), computed_at=COMPUTED_AT)

    def test_an_in_memory_value_cannot_be_cited_as_evidence(
        self, repo: Repository
    ) -> None:
        """An evidence ref with no obs_id points at nothing; storing it would make the
        state an unfalsifiable claim."""
        state = _state(obs_ids=[1])
        detached = MacroDomainState(
            **{
                **state.__dict__,
                "evidence_refs": (
                    EvidenceRef(
                        series_id="PCEPILFE",
                        period_end=CORE_PCE_PERIOD,
                        causal_role="realized",
                        available_at=PUBLISHED_AT,
                        obs_id=None,
                    ),
                ),
            }
        )

        with pytest.raises(ValueError, match="carries no obs_id"):
            repo.insert_macro_domain_state(detached, computed_at=COMPUTED_AT)

    def test_a_state_cannot_be_computed_before_the_instant_it_answers_for(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        with pytest.raises(ValueError, match="precedes as_of"):
            repo.insert_macro_domain_state(
                _state(obs_ids=[core]), computed_at=datetime(2023, 7, 1, tzinfo=UTC)
            )


class TestReplay:
    def test_replay_returns_the_state_in_force_not_a_later_one(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        earlier = _insert_observation(
            repo,
            period_end=date(2023, 5, 1),
            value=Decimal("128.099"),
            available_at=datetime(2023, 6, 30, tzinfo=UTC),
        )
        june_state = repo.insert_macro_domain_state(
            _state(
                obs_ids=[earlier],
                as_of=datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
                inputs_hash="c" * 64,
            ),
            computed_at=datetime(2023, 7, 1, tzinfo=UTC),
        )
        july_state = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        mid_july = repo.fetch_macro_domain_state_as_of(
            "inflation", datetime(2023, 7, 15, tzinfo=UTC)
        )
        after_release = repo.fetch_macro_domain_state_as_of(
            "inflation", datetime(2023, 8, 15, tzinfo=UTC)
        )

        assert mid_july is not None and mid_july["state_id"] == june_state
        assert after_release is not None and after_release["state_id"] == july_state

    def test_replay_before_any_state_returns_nothing(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        assert (
            repo.fetch_macro_domain_state_as_of(
                "inflation", datetime(2023, 1, 1, tzinfo=UTC)
            )
            is None
        )

    def test_replay_is_scoped_to_one_domain(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        assert (
            repo.fetch_macro_domain_state_as_of(
                "policy_rates", datetime(2023, 8, 15, tzinfo=UTC)
            )
            is None
        )

    def test_replay_can_be_pinned_to_one_engine_version(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        assert (
            repo.fetch_macro_domain_state_as_of(
                "inflation",
                datetime(2023, 8, 15, tzinfo=UTC),
                engine_version="inflation/2",
            )
            is None
        )


class TestWithdrawalWithoutRewriting:
    def test_quarantine_removes_a_state_from_service_but_not_from_the_record(
        self, repo: Repository
    ) -> None:
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        assert repo.quarantine_macro_domain_state(
            state_id,
            reason="engine inflation/1 mislabelled the target basis",
            at=datetime(2023, 9, 1, tzinfo=UTC),
        )

        assert (
            repo.fetch_macro_domain_state_as_of(
                "inflation", datetime(2023, 8, 15, tzinfo=UTC)
            )
            is None
        )
        withdrawn = repo.fetch_macro_domain_state(state_id)
        assert withdrawn is not None
        assert withdrawn["status"] == "quarantined"
        assert withdrawn["state"] == "WELL_ABOVE_TARGET"

    def test_quarantine_is_one_way(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )
        repo.quarantine_macro_domain_state(
            state_id, reason="engine withdrawn", at=datetime(2023, 9, 1, tzinfo=UTC)
        )

        assert not repo.quarantine_macro_domain_state(
            state_id, reason="again", at=datetime(2023, 9, 2, tzinfo=UTC)
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="never rewritten"):
            with repo._conn.transaction():
                with repo._conn.cursor() as cur:
                    cur.execute(
                        "UPDATE uw_scan.macro_domain_states SET status = 'published', "
                        "quarantined_at = NULL, quarantine_reason = NULL "
                        "WHERE state_id = %s",
                        (state_id,),
                    )

    def test_a_stored_answer_cannot_be_edited(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        with pytest.raises(psycopg.errors.CheckViolation, match="never rewritten"):
            with repo._conn.transaction():
                with repo._conn.cursor() as cur:
                    cur.execute(
                        "UPDATE uw_scan.macro_domain_states SET direction = 'RISING' "
                        "WHERE state_id = %s",
                        (state_id,),
                    )

    def test_a_state_cannot_be_deleted(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
            with repo._conn.transaction():
                with repo._conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM uw_scan.macro_domain_states WHERE state_id = %s",
                        (state_id,),
                    )

    def test_evidence_cannot_be_detached_from_a_state(self, repo: Repository) -> None:
        core = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[core]), computed_at=COMPUTED_AT
        )

        with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
            with repo._conn.transaction():
                with repo._conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM uw_scan.macro_domain_state_evidence "
                        "WHERE state_id = %s",
                        (state_id,),
                    )

    def test_an_observation_backing_a_state_cannot_be_removed(
        self, repo: Repository
    ) -> None:
        """ON DELETE RESTRICT, so the trail cannot be cut from the far end either."""
        core = _insert_observation(repo)
        repo.insert_macro_domain_state(_state(obs_ids=[core]), computed_at=COMPUTED_AT)

        with pytest.raises(psycopg.errors.Error):
            with repo._conn.transaction():
                with repo._conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM uw_scan.macro_observations WHERE obs_id = %s",
                        (core,),
                    )


class TestTheEngineToStorageSeam:
    """The seam nothing else covers: a state the *engine* produced, persisted for real.

    Every test above hand-builds a ``MacroDomainState``, which proves the table works but
    not that anything can fill it.  The engines read ``DomainObservation`` objects whose
    ``obs_id`` is ``None`` when they come from a fixture, and this module refuses to
    persist a state whose evidence cannot be pointed at -- so if the observations do not
    come out of the evidence store carrying their identities, the two halves of this
    milestone never actually meet.

    Inputs are the preregistered disinflation scenario from
    ``tests/fixtures/macro/inflation_rates_golden.json``: 16 months of real ALFRED
    vintages for eight series, each stamped with the instant it was genuinely published.
    """

    @staticmethod
    def _load_scenario() -> dict[str, object]:
        fixture = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "macro"
            / "inflation_rates_golden.json"
        )
        payload = json.loads(fixture.read_text())
        return next(
            scenario
            for scenario in payload["scenarios"]
            if scenario["id"] == "disinflation_with_sticky_services"
        )

    def _seed_evidence_store(
        self, repo: Repository, scenario: dict[str, object]
    ) -> tuple[DomainObservation, ...]:
        roles = {row["series_id"]: row["causal_role"] for row in scenario["inputs"]}
        observations: list[DomainObservation] = []
        for series_id, block in scenario["observation_history"].items():
            for row in block["observations"]:
                available_at = datetime.fromisoformat(row["available_at"]).replace(
                    tzinfo=UTC
                )
                period_end = date.fromisoformat(row["period_end"])
                obs_id = _insert_observation(
                    repo,
                    series_id=series_id,
                    value=Decimal(row["value"]),
                    unit=block["unit"],
                    period_end=period_end,
                    available_at=available_at,
                )
                observations.append(
                    DomainObservation(
                        series_id=series_id,
                        causal_role=roles[series_id],
                        period_end=period_end,
                        value=Decimal(row["value"]),
                        unit=block["unit"],
                        publisher_transform=block["publisher_transform"],
                        available_at=available_at,
                        source="fred",
                        source_kind="first_party_publisher",
                        cost_class="free_publisher",
                        obs_id=obs_id,
                    )
                )
        return tuple(observations)

    def test_an_engine_computed_state_persists_and_replays(
        self, repo: Repository
    ) -> None:
        scenario = self._load_scenario()
        observations = self._seed_evidence_store(repo, scenario)
        as_of = datetime.fromisoformat(scenario["as_of"]).replace(tzinfo=UTC)

        computed = compute_inflation_state(observations, as_of=as_of)
        state_id = repo.insert_macro_domain_state(
            computed, computed_at=as_of + timedelta(hours=4)
        )

        stored = repo.fetch_macro_domain_state_as_of("inflation", as_of)
        assert stored is not None
        assert stored["state_id"] == state_id
        # The preregistered expectation for this scenario, now round-tripped through
        # Postgres rather than asserted in memory.
        assert stored["state"] == scenario["expect"]["state"]
        assert stored["direction"] == scenario["expect"]["direction"]
        assert stored["engine_version"] == computed.engine_version
        assert stored["inputs_hash"] == computed.inputs_hash
        low, high = scenario["expect"]["confidence_band"]
        assert Decimal(str(low)) <= stored["confidence"] <= Decimal(str(high))

    def test_every_input_the_engine_used_is_recoverable_from_the_database(
        self, repo: Repository
    ) -> None:
        scenario = self._load_scenario()
        observations = self._seed_evidence_store(repo, scenario)
        as_of = datetime.fromisoformat(scenario["as_of"]).replace(tzinfo=UTC)

        computed = compute_inflation_state(observations, as_of=as_of)
        state_id = repo.insert_macro_domain_state(
            computed, computed_at=as_of + timedelta(hours=4)
        )

        evidence = repo.fetch_macro_domain_state_evidence(state_id)
        assert len(evidence) == len(computed.evidence_refs)
        recovered = {
            (row["series_id"], row["period_end"], row["value_numeric"])
            for row in evidence
        }
        expected = {
            (ref.series_id, ref.period_end, obs.value)
            for ref in computed.evidence_refs
            for obs in observations
            if obs.obs_id == ref.obs_id
        }
        assert recovered == expected
        assert all(row["causal_role"] for row in evidence)

    def test_the_engine_never_cites_evidence_published_after_its_as_of(
        self, repo: Repository
    ) -> None:
        """Belt and braces: the engine filters by ``available_at``, and the database
        would reject the state anyway.  This asserts the two agree on the same fixture
        rather than trusting either alone."""
        scenario = self._load_scenario()
        observations = self._seed_evidence_store(repo, scenario)
        as_of = datetime.fromisoformat(scenario["as_of"]).replace(tzinfo=UTC)

        computed = compute_inflation_state(observations, as_of=as_of)
        state_id = repo.insert_macro_domain_state(
            computed, computed_at=as_of + timedelta(hours=4)
        )

        for row in repo.fetch_macro_domain_state_evidence(state_id):
            assert row["available_at"] <= as_of, row["series_id"]

    def test_recomputing_from_the_same_evidence_store_is_a_no_op(
        self, repo: Repository
    ) -> None:
        """Idempotence where it actually matters: two runs of the real engine over the
        same persisted evidence, not two copies of one hand-built object."""
        scenario = self._load_scenario()
        observations = self._seed_evidence_store(repo, scenario)
        as_of = datetime.fromisoformat(scenario["as_of"]).replace(tzinfo=UTC)

        first = repo.insert_macro_domain_state(
            compute_inflation_state(observations, as_of=as_of),
            computed_at=as_of + timedelta(hours=4),
        )
        second = repo.insert_macro_domain_state(
            compute_inflation_state(observations, as_of=as_of),
            computed_at=as_of + timedelta(days=3),
        )

        assert first == second
        with repo._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM uw_scan.macro_domain_states")
            assert cur.fetchone()[0] == 1


class TestSubStatesRoundTrip:
    """A sub-state carries its own confidence, and that must survive storage.

    Not a detail: the whole reason sub-states are separate rows rather than factors is
    that their confidence denominators differ from the domain's. A round trip that
    dropped or flattened the number would silently restore the substitution R2 forbids.
    """

    def _rates_sub_states(self) -> tuple[MacroSubState, ...]:
        return (
            MacroSubState(
                role="positioning",
                state="STRETCHED_LOW",
                direction="FALLING",
                velocity=(
                    Velocity(
                        metric="043602|lev_money_net_pct_oi_change_4w",
                        value=Decimal("-5.6103"),
                        unit="pct_open_interest",
                        window_months=1,
                    ),
                ),
                confidence=Decimal("0.6250"),
                confidence_reasons=(
                    ConfidenceTerm(
                        term="completeness",
                        value=Decimal("1"),
                        detail="1/1 load-bearing inputs present",
                    ),
                    ConfidenceTerm(
                        term="positioning_percentiles",
                        value=Decimal("1"),
                        detail="043602|lev_money_net_pct_oi at p10 (STRETCHED_LOW)",
                        kind="informational",
                    ),
                ),
                series_ids=("043602|lev_money_net_pct_oi",),
                latest_period_end=date(2025, 9, 9),
            ),
            MacroSubState(
                role="plumbing",
                state="UNKNOWN",
                direction="UNKNOWN",
                velocity=(),
                confidence=Decimal(0),
                confidence_reasons=(
                    ConfidenceTerm(
                        term="plumbing_unavailable",
                        value=Decimal(0),
                        detail="SOFR had no observation available at as_of",
                        kind="informational",
                    ),
                ),
                series_ids=(),
                unavailable_reason="SOFR had no observation available at as_of",
            ),
        )

    def test_a_sub_state_survives_with_its_own_confidence(
        self, repo: Repository
    ) -> None:
        obs_ids = [
            _insert_observation(repo),
            _insert_observation(
                repo, series_id="MICH", value=Decimal("3.3"), unit="percent"
            ),
        ]
        original = _state(obs_ids=obs_ids, sub_states=self._rates_sub_states())
        repo.insert_macro_domain_state(original, computed_at=COMPUTED_AT)

        row = repo.fetch_macro_domain_state_as_of("inflation", AS_OF)
        restored = macro_domain_state_from_row(
            row, repo.fetch_macro_domain_state_evidence(int(row["state_id"]))
        )
        assert restored.sub_states == original.sub_states

        positioning = restored.sub_state("positioning")
        assert positioning is not None
        # Exact, not approximate: a percentile band is decided at the fourth place.
        assert positioning.confidence == Decimal("0.6250")
        assert positioning.velocity[0].value == Decimal("-5.6103")
        assert positioning.confidence != restored.confidence

    def test_an_unknown_sub_state_keeps_its_reason(
        self, repo: Repository, seeded_db_empty_cards
    ) -> None:
        """UNKNOWN with no reason is indistinguishable from a role nobody declared."""
        obs_ids = [
            _insert_observation(repo),
            _insert_observation(
                repo, series_id="MICH", value=Decimal("3.3"), unit="percent"
            ),
        ]
        repo.insert_macro_domain_state(
            _state(obs_ids=obs_ids, sub_states=self._rates_sub_states()),
            computed_at=COMPUTED_AT,
        )
        row = repo.fetch_macro_domain_state_as_of("inflation", AS_OF)
        restored = macro_domain_state_from_row(
            row, repo.fetch_macro_domain_state_evidence(int(row["state_id"]))
        )
        plumbing = restored.sub_state("plumbing")
        assert plumbing is not None
        assert plumbing.state == "UNKNOWN"
        assert plumbing.unavailable_reason
        assert plumbing.series_ids == ()


class TestCrossDomainLineage:
    """One state standing on another's ANSWER (migration 128).

    USD is a transmission domain and gold reads three upstream answers. Both must
    reference those answers rather than re-read their inputs, and the reference has to be
    a row -- inside ``inputs_hash`` alone it is present in the identity and invisible in
    the record, so a reader could tell that a USD state changed when rates did and never
    ask what rates said.
    """

    def _upstream(
        self,
        repo: Repository,
        *,
        as_of: datetime = AS_OF,
        inputs_hash: str = "b" * 64,
        value: Decimal = CORE_PCE_VALUE,
        computed_at: datetime | None = None,
    ) -> int:
        # inputs_hash and value are parameters because _insert_observation is content
        # addressed: calling it twice with defaults returns the SAME obs_id, and the
        # state built on it would then collide on method identity and hand back the
        # first state's id. A test that needs two distinct upstreams has to make them
        # actually distinct.
        obs = _insert_observation(repo, value=value)
        return repo.insert_macro_domain_state(
            _state(obs_ids=[obs], as_of=as_of, inputs_hash=inputs_hash),
            # Must trail as_of: a state cannot be computed before the instant it answers
            # for, and a fixed COMPUTED_AT trips that rule before the lookahead check
            # this class is actually about ever runs.
            computed_at=computed_at or max(COMPUTED_AT, as_of),
        )

    def _downstream(
        self,
        repo: Repository,
        upstream: list[tuple[int, str]],
        *,
        as_of: datetime = AS_OF,
        inputs_hash: str = "c" * 64,
    ) -> int:
        obs = _insert_observation(repo, series_id="MICH", value=Decimal("3.3"))
        return repo.insert_macro_domain_state(
            _state(obs_ids=[obs], as_of=as_of, inputs_hash=inputs_hash),
            computed_at=COMPUTED_AT,
            upstream=upstream,
        )

    def test_the_edge_carries_what_the_upstream_actually_said(
        self, repo: Repository
    ) -> None:
        upstream_id = self._upstream(repo)
        downstream_id = self._downstream(repo, [(upstream_id, "policy_actual")])

        deps = repo.fetch_macro_domain_state_dependencies(downstream_id)
        assert len(deps) == 1
        assert deps[0]["upstream_state_id"] == upstream_id
        assert deps[0]["causal_role"] == "policy_actual"
        # The answer, not just the pointer: an edge you have to make a second query to
        # interpret is a foreign key, not lineage.
        assert deps[0]["upstream_state"] == "WELL_ABOVE_TARGET"
        assert deps[0]["upstream_direction"] == "FALLING"
        assert deps[0]["upstream_confidence"] == Decimal("0.72")

    def test_an_upstream_answering_for_a_later_instant_is_refused(
        self, repo: Repository
    ) -> None:
        """The same lookahead the evidence predicate refuses, one level up.

        A state that consulted an answer computed for a moment after the one it
        describes has read the future, and the fact that the future answer is about
        another domain does not make it knowable.
        """
        later = self._upstream(
            repo,
            as_of=AS_OF + timedelta(days=1),
            computed_at=COMPUTED_AT + timedelta(days=2),
        )
        with pytest.raises(ValueError, match="lookahead"):
            self._downstream(repo, [(later, "policy_actual")])

    def test_an_upstream_answering_for_the_same_instant_is_allowed(
        self, repo: Repository
    ) -> None:
        # Not a strict inequality: two domains computed for the same as_of is the normal
        # case, not a violation.
        same = self._upstream(repo, as_of=AS_OF)
        assert self._downstream(repo, [(same, "policy_actual")])

    def test_a_dependency_on_a_state_that_was_never_stored_is_refused(
        self, repo: Repository
    ) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            self._downstream(repo, [(9_999_999, "policy_actual")])

    def test_a_state_cannot_stand_on_itself(self, repo: Repository) -> None:
        obs = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[obs], inputs_hash="d" * 64), computed_at=COMPUTED_AT
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with repo._conn.transaction():
                repo._conn.execute(
                    "INSERT INTO uw_scan.macro_domain_state_dependencies "
                    "(downstream_state_id, upstream_state_id, causal_role, ordinal) "
                    "VALUES (%s, %s, 'curve', 0)",
                    (state_id, state_id),
                )

    def test_one_upstream_serves_two_downstreams_without_copying_observations(
        self, repo: Repository
    ) -> None:
        """USD and gold both read the rates answer. Neither copies its rows.

        The observation count is the assertion: if referencing an upstream duplicated
        its evidence, two consumers would double it.
        """
        upstream_id = self._upstream(repo)
        before = _count_observations(repo)

        first = self._downstream(
            repo, [(upstream_id, "policy_actual")], inputs_hash="e" * 64
        )
        second = self._downstream(repo, [(upstream_id, "curve")], inputs_hash="f" * 64)

        assert first != second
        # ONE new observation for two new downstream states: they share the same MICH row
        # because observations are content addressed, and the upstream's own PCEPILFE row
        # is reached through the edge rather than copied. Referencing an upstream costs
        # zero observations, which is the whole reason the edge exists.
        assert _count_observations(repo) == before + 1
        for state_id, role in ((first, "policy_actual"), (second, "curve")):
            deps = repo.fetch_macro_domain_state_dependencies(state_id)
            assert [(d["upstream_state_id"], d["causal_role"]) for d in deps] == [
                (upstream_id, role)
            ]

    def test_the_same_identity_cannot_name_a_different_upstream_set(
        self, repo: Repository
    ) -> None:
        first = self._upstream(repo, inputs_hash="a" * 63 + "1")
        second = self._upstream(
            repo, inputs_hash="a" * 63 + "2", value=Decimal("128.412")
        )
        assert first != second
        obs = _insert_observation(repo, series_id="MICH", value=Decimal("3.3"))
        state = _state(obs_ids=[obs], inputs_hash="1" * 64)
        repo.insert_macro_domain_state(
            state, computed_at=COMPUTED_AT, upstream=[(first, "policy_actual")]
        )
        with pytest.raises(ValueError, match="different upstream set"):
            repo.insert_macro_domain_state(
                state, computed_at=COMPUTED_AT, upstream=[(second, "policy_actual")]
            )

    def test_re_inserting_with_the_same_upstream_set_is_a_no_op(
        self, repo: Repository
    ) -> None:
        upstream_id = self._upstream(repo)
        obs = _insert_observation(repo, series_id="MICH", value=Decimal("3.3"))
        state = _state(obs_ids=[obs], inputs_hash="2" * 64)
        first = repo.insert_macro_domain_state(
            state, computed_at=COMPUTED_AT, upstream=[(upstream_id, "policy_actual")]
        )
        again = repo.insert_macro_domain_state(
            state, computed_at=COMPUTED_AT, upstream=[(upstream_id, "policy_actual")]
        )
        assert first == again
        assert len(repo.fetch_macro_domain_state_dependencies(first)) == 1

    def test_a_state_with_no_upstream_is_normal_not_a_gap(
        self, repo: Repository
    ) -> None:
        # Inflation and rates stand on observations alone. Only a transmission domain
        # has upstream answers, so silence here must not be treated as missing lineage.
        obs = _insert_observation(repo)
        state_id = repo.insert_macro_domain_state(
            _state(obs_ids=[obs], inputs_hash="3" * 64), computed_at=COMPUTED_AT
        )
        assert repo.fetch_macro_domain_state_dependencies(state_id) == []


def _count_observations(repo: Repository) -> int:
    with repo._conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.macro_observations")
        return int(cur.fetchone()[0])
