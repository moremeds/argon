"""The evidence-to-state worker path, driven end to end through real published values.

Two seams are under test and neither is provable from a unit test.

The first is re-reading a series.  One ALFRED request returns the whole history, so the
night a new print lands the payload changes and a naive identity would re-write every
unchanged month in it.  That only shows up against a real database with a real second
fetch.

The second is the state job itself: it reads evidence back out of storage, computes, and
persists, and the observations have to come back carrying the ``obs_id`` the state table
demands.  Values here are real -- CPI vintages frozen from ALFRED on 2026-08-18, and the
preregistered disinflation scenario's sixteen months of eight series -- so the assertions
are about published facts, not about numbers invented to make a test pass.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_sep_ingest_job,
)
from uw_scan.worker.jobs.macro_series_ingest import macro_fred_series_ingest_job
from uw_scan.worker.jobs.macro_state_jobs import (
    macro_usd_state_job,
    macro_inflation_state_job,
    macro_rates_state_job,
)

from ._macro_providers import FIXTURES, _SepProvider, _StatementProvider

#: The scenario's own as_of, preregistered in the golden fixture before the engine existed.
DISINFLATION_AS_OF = datetime(2023, 7, 28, 12, tzinfo=UTC)
CPI_FIXTURE_AS_OF = datetime(2026, 8, 18, 12, tzinfo=UTC)
POLICY_AS_OF = datetime(2026, 8, 12, 12, tzinfo=UTC)


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


class _PayloadProvider:
    """Serves prepared ALFRED payloads; the job must never reach a network."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads
        self.requests: list[tuple[str, date | None, date | None]] = []

    def __enter__(self) -> "_PayloadProvider":
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
        self.requests.append((series_id, realtime_start, realtime_end))
        return (
            self._payloads[series_id],
            f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}",
        )


def _cpi_payload() -> bytes:
    return (FIXTURES / "fred_cpi_vintages.json").read_bytes()


def _golden_scenario() -> dict[str, object]:
    payload = json.loads((FIXTURES / "inflation_rates_golden.json").read_text())
    return next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["id"] == "disinflation_with_sticky_services"
    )


def _alfred_payloads(scenario: dict[str, object]) -> dict[str, bytes]:
    """Wrap the scenario's real values in the publisher's own envelope.

    The values, periods and publication days are ALFRED's; only the envelope is rebuilt,
    because the golden fixture stores the selected vintage rather than the raw response.
    Each period appears once, so every window runs open-ended.
    """
    payloads: dict[str, bytes] = {}
    for series_id, block in scenario["observation_history"].items():  # type: ignore[union-attr]
        payloads[series_id] = json.dumps(
            {
                "realtime_start": "1776-07-04",
                "realtime_end": "9999-12-31",
                "observations": [
                    {
                        "date": row["period_end"],
                        "value": row["value"],
                        "realtime_start": row["available_at"],
                        "realtime_end": "9999-12-31",
                    }
                    for row in block["observations"]
                ],
            }
        ).encode()
    return payloads


def _ingest_scenario(
    settings: Settings,
    scenario: dict[str, object],
    *,
    observed_at: datetime = DISINFLATION_AS_OF,
) -> None:
    """``observed_at`` is when we fetched, which bounds what the payload may claim.

    A vintage dated after the fetch that reported it is refused by the store, so a test
    that adds a later restatement has to move the fetch instant with it.
    """
    payloads = _alfred_payloads(scenario)
    result = macro_fred_series_ingest_job(
        dsn=settings.db_dsn(),
        api_key="unused-by-the-stub",
        series=tuple(payloads),
        observed_at=observed_at,
        provider_factory=lambda: _PayloadProvider(payloads),
    )
    assert result.status == "ok", result.error_message


def _repo(conn: psycopg.Connection) -> Repository:
    return Repository(conn, schema="uw_scan")


class TestRawEvidenceSurvivesAParseFailure:
    """The bytes that broke the parser are the bytes needed to fix it.

    Each series commits on its own, so with the artifact insert on the far side of
    ``parse_fred_series`` a FRED schema change rolled back the exact payload that caused
    the failure -- destroying the evidence on precisely the run where it is wanted, and
    leaving the parser fix unverifiable against what broke it.

    The payload below is a real CPIAUCSL vintage (January 2024, 309.685, first published
    2024-02-13) with ``realtime_start`` dropped from one row: the shape a publisher
    schema change actually takes, rather than corruption.
    """

    def _broken_payload(self) -> bytes:
        return json.dumps(
            {
                "observations": [
                    {
                        "date": "2024-01-01",
                        "value": "309.685",
                        "realtime_start": "2024-02-13",
                        "realtime_end": "2024-03-11",
                    },
                    {"date": "2024-02-01", "value": "310.326"},
                ]
            }
        ).encode()

    def test_the_artifact_is_committed_before_anything_is_parsed_from_it(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        raw = self._broken_payload()

        result = macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("CPIAUCSL",),
            observed_at=CPI_FIXTURE_AS_OF,
            provider_factory=lambda: _PayloadProvider({"CPIAUCSL": raw}),
        )

        assert result.failed_series == ("CPIAUCSL",)
        assert result.observations_created == 0

        expected_hash, expected_length = macro_artifact_content_identity(raw_bytes=raw)
        with psycopg.connect(settings.db_dsn()) as conn:
            row = conn.execute(
                """
                SELECT content_hash, content_length, raw_bytes, vintage_bearing
                FROM uw_scan.macro_source_artifacts
                WHERE source_record_id = 'fred-series:CPIAUCSL'
                """
            ).fetchone()
        assert row is not None, (
            "the payload that broke the parser was discarded; it is the only copy of "
            "what FRED actually sent"
        )
        assert row[0] == expected_hash
        assert row[1] == expected_length
        assert bytes(row[2]) == raw
        assert row[3] is True


class TestFredSeriesIngest:
    def test_each_vintage_lands_with_its_true_publication_date(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        payloads = {"CPIAUCSL": _cpi_payload()}
        provider = _PayloadProvider(payloads)

        result = macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("CPIAUCSL",),
            observed_at=CPI_FIXTURE_AS_OF,
            provider_factory=lambda: provider,
        )

        assert (result.status, result.observations_created) == ("ok", 9)
        # The request that makes the dates real. A bounded window would have been
        # clamped onto every row, stamping the fetch date on a 2024 publication.
        assert provider.requests == [("CPIAUCSL", date(1776, 7, 4), date(9999, 12, 31))]
        with psycopg.connect(settings.db_dsn()) as conn:
            rows = conn.execute(
                """
                SELECT period_end, available_at, value_numeric
                FROM uw_scan.macro_observations
                WHERE series_id = 'CPIAUCSL' AND period_end = '2024-01-01'
                ORDER BY available_at
                """
            ).fetchall()
        assert [(row[1].date(), row[2]) for row in rows] == [
            (date(2024, 2, 13), Decimal("309.685")),
            (date(2025, 2, 12), Decimal("309.794")),
            (date(2026, 2, 13), Decimal("309.698")),
        ]

    def test_reingesting_identical_bytes_writes_nothing_new(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        payloads = {"CPIAUCSL": _cpi_payload()}
        for _ in range(2):
            result = macro_fred_series_ingest_job(
                dsn=settings.db_dsn(),
                api_key="unused-by-the-stub",
                series=("CPIAUCSL",),
                observed_at=CPI_FIXTURE_AS_OF,
                provider_factory=lambda: _PayloadProvider(payloads),
            )
        assert (result.observations_created, result.observations_unchanged) == (0, 9)
        with psycopg.connect(settings.db_dsn()) as conn:
            counts = conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM uw_scan.macro_observations),
                  (SELECT count(*) FROM uw_scan.macro_source_artifacts)
                """
            ).fetchone()
        assert counts == (9, 1)

    def test_a_new_vintage_does_not_rewrite_the_history_that_carried_it(
        self, seeded_db_empty_cards
    ) -> None:
        """The regression the vintage identity exists for.

        One request returns the whole series, so a single new print changes the payload
        and mints a new artifact.  Under an identity that includes ``artifact_id`` every
        already-stored month in that payload would re-hash and be written a second time:
        nine facts would silently become eighteen.
        """
        settings = _settings()
        first = json.loads(_cpi_payload())
        macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("CPIAUCSL",),
            observed_at=CPI_FIXTURE_AS_OF,
            provider_factory=lambda: _PayloadProvider(
                {"CPIAUCSL": json.dumps(first).encode()}
            ),
        )

        # April 2024 CPI, published 2024-05-15. Real value, real release date.
        extended = {
            **first,
            "observations": [
                *first["observations"],
                {
                    "realtime_start": "2024-05-15",
                    "realtime_end": "9999-12-31",
                    "date": "2024-04-01",
                    "value": "313.548",
                },
            ],
        }
        second = macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("CPIAUCSL",),
            observed_at=CPI_FIXTURE_AS_OF,
            provider_factory=lambda: _PayloadProvider(
                {"CPIAUCSL": json.dumps(extended).encode()}
            ),
        )

        assert (second.observations_created, second.observations_unchanged) == (1, 9)
        with psycopg.connect(settings.db_dsn()) as conn:
            total, artifacts = conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM uw_scan.macro_observations),
                  (SELECT count(*) FROM uw_scan.macro_source_artifacts)
                """
            ).fetchone()
            witnesses = conn.execute(
                """
                SELECT count(*) FROM uw_scan.macro_observation_artifacts
                WHERE relation = 'corroborates'
                """
            ).fetchone()[0]
        assert (total, artifacts) == (10, 2)
        # The second payload really did carry the nine older facts; it is recorded as a
        # witness to them rather than as their source.
        assert witnesses == 9


class TestInflationStateJob:
    def test_a_state_is_computed_from_stored_evidence_alone(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        scenario = _golden_scenario()
        _ingest_scenario(settings, scenario)

        with psycopg.connect(settings.db_dsn()) as conn:
            result = macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)

        expected = scenario["expect"]
        assert result.status == "ok", result.error_message
        assert result.state == expected["state"]
        assert result.direction == expected["direction"]
        low, high = expected["confidence_band"]
        assert Decimal(str(low)) <= result.confidence <= Decimal(str(high))

    def test_recomputing_the_same_instant_is_idempotent(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        _ingest_scenario(settings, _golden_scenario())

        with psycopg.connect(settings.db_dsn()) as conn:
            first = macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)
            second = macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)

        assert first.state_id == second.state_id
        with psycopg.connect(settings.db_dsn()) as conn:
            rows = conn.execute(
                "SELECT count(*) FROM uw_scan.macro_domain_states WHERE domain = 'inflation'"
            ).fetchone()[0]
        assert rows == 1

    def test_every_evidence_row_points_at_a_stored_observation(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        _ingest_scenario(settings, _golden_scenario())

        with psycopg.connect(settings.db_dsn()) as conn:
            result = macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)
            evidence = _repo(conn).fetch_macro_domain_state_evidence(result.state_id)

        assert result.evidence_count == len(evidence) == 8 * 16
        assert all(row["obs_id"] is not None for row in evidence)
        # Nothing the engine stood on may postdate the instant it answers for.
        assert all(row["available_at"] <= DISINFLATION_AS_OF for row in evidence)

    def test_an_empty_evidence_store_abstains_instead_of_persisting(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        with psycopg.connect(settings.db_dsn()) as conn:
            result = macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)
            stored = conn.execute(
                "SELECT count(*) FROM uw_scan.macro_domain_states"
            ).fetchone()[0]

        assert (result.status, result.state) == ("abstained", "INDETERMINATE")
        assert result.state_id is None
        # An abstention citing nothing is not a record; the absence is the honest answer.
        assert stored == 0

    def test_a_revision_to_a_period_the_prior_state_used_is_recorded(
        self, seeded_db_empty_cards
    ) -> None:
        """Revision detection needs the previous answer, and only storage can supply it."""
        settings = _settings()
        scenario = _golden_scenario()
        _ingest_scenario(settings, scenario)
        with psycopg.connect(settings.db_dsn()) as conn:
            macro_inflation_state_job(_repo(conn), as_of=DISINFLATION_AS_OF)

        # The publisher restates the latest core PCE month the prior state stood on.
        history = scenario["observation_history"]["PCEPILFE"]["observations"]
        latest = max(history, key=lambda row: row["period_end"])
        revised = {
            **scenario,
            "observation_history": {
                **scenario["observation_history"],
                "PCEPILFE": {
                    **scenario["observation_history"]["PCEPILFE"],
                    "observations": [
                        *history,
                        {
                            "period_end": latest["period_end"],
                            "value": str(Decimal(latest["value"]) + Decimal("0.4")),
                            # After the prior state's as_of, or it is not a restatement
                            # of what that state saw -- it is an older vintage the
                            # point-in-time read would correctly ignore.
                            "available_at": "2023-07-29",
                        },
                    ],
                },
            },
        }
        _ingest_scenario(
            settings, revised, observed_at=datetime(2023, 7, 30, 12, tzinfo=UTC)
        )

        with psycopg.connect(settings.db_dsn()) as conn:
            later = macro_inflation_state_job(
                _repo(conn), as_of=datetime(2023, 7, 30, 12, tzinfo=UTC)
            )
            row = _repo(conn).fetch_macro_domain_state(later.state_id)

        reasons = {r["term"]: r["detail"] for r in row["confidence_reasons_jsonb"]}
        assert "load_bearing_input_revised_since_prior_state" in reasons
        assert "PCEPILFE" in reasons["load_bearing_input_revised_since_prior_state"]
        # The engine read the restatement, not the value the prior state stood on.
        factor = next(f for f in row["factors_jsonb"] if f["series_id"] == "PCEPILFE")
        assert Decimal(factor["value"]) == Decimal(latest["value"]) + Decimal("0.4")


class TestRatesStateJob:
    def test_the_state_cites_the_policy_release_it_read(
        self, seeded_db_empty_cards
    ) -> None:
        """``state`` comes off the FOMC target range, so the lineage must name it.

        Before this, ``evidence_refs`` carried only market series -- so a rates state with
        no DGS10 was unpersistable, and one with DGS10 cited everything except the release
        its answer actually turned on.
        """
        settings = _settings()
        macro_fomc_statement_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_StatementProvider,
            observed_at=POLICY_AS_OF,
        )
        macro_sep_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_SepProvider,
            observed_at=POLICY_AS_OF,
        )

        with psycopg.connect(settings.db_dsn()) as conn:
            result = macro_rates_state_job(_repo(conn), as_of=POLICY_AS_OF)
            evidence = _repo(conn).fetch_macro_domain_state_evidence(result.state_id)

        assert result.status == "ok", result.error_message
        roles = {row["causal_role"] for row in evidence}
        assert {"policy_actual", "policy_committee"} <= roles
        assert all(row["obs_id"] is not None for row in evidence)

    def test_an_absent_path_is_absent_rather_than_substituted(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        macro_fomc_statement_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_StatementProvider,
            observed_at=POLICY_AS_OF,
        )

        with psycopg.connect(settings.db_dsn()) as conn:
            result = macro_rates_state_job(_repo(conn), as_of=POLICY_AS_OF)
            evidence = _repo(conn).fetch_macro_domain_state_evidence(result.state_id)

        roles = {row["causal_role"] for row in evidence}
        assert "policy_actual" in roles
        # No dealer survey was ingested, so nothing may stand in for one.
        assert "policy_dealer" not in roles
        assert "policy_committee" not in roles
        assert result.confidence < Decimal("1")


def _usd_anchor_payload() -> bytes:
    """DTWEXBGS in ALFRED's envelope, from the frozen USD golden fixture.

    Real H.10 vintages -- both the original and the restatement where one exists -- so
    the ingest sees the same publication history the publisher actually had.
    """
    fixture = json.loads(
        (FIXTURES / "usd_gold_golden.json").read_text(encoding="utf-8")
    )
    # The REVISION scenario, not the momentum one. Its periods are days from the policy
    # release the rates state answers with, so both domains can be replayed at one
    # instant; the momentum scenario's are 2024 and fall outside the anchor's 400-day
    # evidence window at any as_of that also sees the 2026 FOMC statement.
    scenario = next(
        s
        for s in fixture["scenarios"]
        if s["id"] == "broad_dollar_revised_after_the_fact"
    )
    rows = [r for r in scenario["inputs"] if r["series_id"] == "DTWEXBGS"]
    return json.dumps(
        {
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "observations": [
                {
                    "date": r["period_end"],
                    "value": r["value"],
                    "realtime_start": r["available_at"],
                    "realtime_end": r["superseded_at"] or "9999-12-31",
                }
                for r in rows
            ],
        }
    ).encode()


class TestTheThreeDomainPass:
    """What the scheduler's ``_macro_state_compute`` closure produces.

    The closure is eight lines of glue that no test can import -- it is nested inside
    the scheduler's setup function. What it MEANS is testable, and that is what matters:
    three domains stamped with ONE as_of, and USD standing on the rates answer from that
    same instant.

    That equality is the interesting part. USD refuses an upstream answering for a later
    instant, so a guard written with ``>=`` instead of ``>`` would reject the normal case
    -- every scheduled run, every night -- and the symptom would be a USD state that
    silently never has lineage.
    """

    #: After the anchor's restatement (2026-08-17) so the ingest can carry both
    #: vintages, and after the policy release (2026-08-12) so rates has something to
    #: answer with.
    SHARED_AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)

    def _seed(self, settings: Settings) -> None:
        macro_fomc_statement_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_StatementProvider,
            observed_at=POLICY_AS_OF,
        )
        result = macro_fred_series_ingest_job(
            dsn=settings.db_dsn(),
            api_key="unused-by-the-stub",
            series=("DTWEXBGS",),
            observed_at=self.SHARED_AS_OF,
            provider_factory=lambda: _PayloadProvider(
                {"DTWEXBGS": _usd_anchor_payload()}
            ),
        )
        assert result.status == "ok", result.error_message

    def test_all_three_domains_answer_for_one_instant(
        self, seeded_db_empty_cards
    ) -> None:
        """Three separate now() calls make three slightly different questions.

        A reader comparing the inflation state against the rates state would then be
        comparing answers to two different moments, which is the exact comparison this
        pass exists to make safe.
        """
        settings = _settings()
        self._seed(settings)

        with psycopg.connect(settings.db_dsn()) as conn:
            repo = _repo(conn)
            results = [
                job(repo, as_of=self.SHARED_AS_OF)
                for job in (
                    macro_inflation_state_job,
                    macro_rates_state_job,
                    macro_usd_state_job,
                )
            ]

        assert {r.as_of for r in results} == {self.SHARED_AS_OF}

    def test_usd_records_the_rates_answer_it_stood_on(
        self, seeded_db_empty_cards
    ) -> None:
        settings = _settings()
        self._seed(settings)

        with psycopg.connect(settings.db_dsn()) as conn:
            repo = _repo(conn)
            rates = macro_rates_state_job(repo, as_of=self.SHARED_AS_OF)
            usd = macro_usd_state_job(repo, as_of=self.SHARED_AS_OF)
            deps = repo.fetch_macro_domain_state_dependencies(usd.state_id)

        assert rates.status == "ok", rates.error_message
        # ``ok`` with state UNKNOWN: five observations is short of the 63 the momentum
        # window needs, so there is no direction to report -- and the state persists
        # anyway, because it has evidence it can be reconstructed from. Absence of a
        # reading is not absence of a record.
        assert usd.status == "ok", usd.error_message
        assert len(deps) == 1
        assert deps[0]["upstream_state_id"] == rates.state_id
        assert deps[0]["causal_role"] == "policy_actual"
        # The boundary the guard must ADMIT: same instant, not an earlier one.
        assert deps[0]["upstream_as_of"] == self.SHARED_AS_OF
        assert deps[0]["upstream_state"] == rates.state

    def test_usd_still_answers_when_no_rates_state_exists(
        self, seeded_db_empty_cards
    ) -> None:
        """Order is a dependency, not a precondition.

        If rates failed or has never run, the dollar reading is still true. USD runs with
        no upstream and the policy contradiction simply does not fire -- rather than
        firing against a guess, or the whole domain going dark because a neighbour did.
        """
        settings = _settings()
        self._seed(settings)

        with psycopg.connect(settings.db_dsn()) as conn:
            repo = _repo(conn)
            usd = macro_usd_state_job(repo, as_of=self.SHARED_AS_OF)
            deps = repo.fetch_macro_domain_state_dependencies(usd.state_id)
            row = repo.fetch_macro_domain_state(usd.state_id)

        assert usd.status == "ok", usd.error_message
        assert deps == []
        assert not any(
            c["rule"] == "usd_against_relative_policy"
            for c in row["contradictions_jsonb"]
        )
