from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesSourceBundle
from uw_scan.sources.fed_sep import SepSourceBundle
from uw_scan.sources.fomc_statement import FomcStatementBundle
from uw_scan.sources.nyfed_sme import SmeSourceBundle
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_market_implied_ingest_job,
    macro_sep_ingest_job,
    macro_sme_ingest_job,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
OBSERVED_AT = datetime(2026, 8, 12, 12, tzinfo=UTC)


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


class _StatementProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_bundles(self, *, years, retrieved_at):
        assert 2026 in years
        return [
            FomcStatementBundle.from_bytes(
                meeting_date=date(2026, 6, 17),
                accessible_url=(
                    "https://www.federalreserve.gov/newsevents/pressreleases/"
                    "monetary20260617a.htm"
                ),
                accessible_bytes=(
                    FIXTURES / "fomc_statement_2026_06.html"
                ).read_bytes(),
                pdf_url=(
                    "https://www.federalreserve.gov/monetarypolicy/files/"
                    "monetary20260617a1.pdf"
                ),
                pdf_bytes=(FIXTURES / "fomc_statement_2026_06.pdf").read_bytes(),
                retrieved_at=retrieved_at,
            )
        ]


class _SepProvider:
    pdf_suffix = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_bundles(self, *, years, retrieved_at):
        assert 2026 in years
        return [
            SepSourceBundle.from_bytes(
                meeting_date=date(2026, 6, 17),
                accessible_url=(
                    "https://www.federalreserve.gov/monetarypolicy/"
                    "fomcprojtabl20260617.htm"
                ),
                accessible_bytes=(FIXTURES / "fed_sep_2026_06.html").read_bytes(),
                pdf_url=(
                    "https://www.federalreserve.gov/monetarypolicy/files/"
                    "fomcprojtabl20260617.pdf"
                ),
                pdf_bytes=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes()
                + self.pdf_suffix,
                retrieved_at=retrieved_at,
            )
        ]


class _ChangedSepProvider(_SepProvider):
    pdf_suffix = b"publisher-correction"


class _MalformedSepProvider(_SepProvider):
    def fetch_bundles(self, *, years, retrieved_at):
        bundle = super().fetch_bundles(years=years, retrieved_at=retrieved_at)[0]
        return [
            SepSourceBundle.from_bytes(
                meeting_date=bundle.meeting_date,
                accessible_url=bundle.accessible_artifact.source_url or "",
                accessible_bytes=(
                    b"<p>For release at 2:00 p.m., EDT, June 17, 2026</p>"
                ),
                pdf_url=bundle.primary_artifact.source_url or "",
                pdf_bytes=bundle.primary_artifact.raw_bytes or b"",
                retrieved_at=retrieved_at,
            )
        ]


class _SmeProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_latest_bundle(self, *, retrieved_at):
        return SmeSourceBundle.from_bytes(
            survey_month=date(2026, 6, 1),
            data_url=(
                "https://www.newyorkfed.org/medialibrary/media/markets/survey/"
                "2026/jun-2026-data.xlsx"
            ),
            data_bytes=(FIXTURES / "nyfed_sme_2026_06.xlsx").read_bytes(),
            report_url=(
                "https://www.newyorkfed.org/medialibrary/media/markets/survey/"
                "2026/jun-2026-sme-results.pdf"
            ),
            report_bytes=(FIXTURES / "nyfed_sme_2026_06.pdf").read_bytes(),
            retrieved_at=retrieved_at,
        )


class _MarketProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_bundle(self, *, retrieved_at):
        raw = b"""
        <script>window.__SSR_DATA__ = {
          "current_effr": 3.67,
          "current_rate": 3.75,
          "meetings": [{
            "meeting_date": "2026-09-16",
            "post_rate": 3.42,
            "probabilities": {
              "cut_25": 0.70, "cut_gt25": 0.10, "hold": 0.20,
              "hike_25": 0.0, "hike_gt25": 0.0
            }
          }],
          "next_meeting": "2026-09-16"
        };</script>
        """
        return FedFundsFuturesSourceBundle.from_bytes(
            source_url="https://www.frenzycap.com/fedwatch",
            raw_bytes=raw,
            retrieved_at=retrieved_at,
        )


def _counts(settings: Settings) -> tuple[int, int]:
    with psycopg.connect(settings.db_dsn()) as conn:
        return (
            conn.execute(
                "SELECT count(*) FROM uw_scan.macro_source_artifacts"
            ).fetchone()[0],
            conn.execute("SELECT count(*) FROM uw_scan.macro_observations").fetchone()[
                0
            ],
        )


def test_independent_jobs_persist_exact_artifacts_and_typed_paths(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()

    statement = macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_StatementProvider,
        observed_at=OBSERVED_AT,
    )
    sep = macro_sep_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_SepProvider,
        observed_at=OBSERVED_AT,
    )
    sme = macro_sme_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_SmeProvider,
        observed_at=OBSERVED_AT,
    )

    assert (statement.status, sep.status, sme.status) == ("ok", "ok", "ok")
    assert _counts(settings) == (6, 3)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        actual = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_ACTUAL",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_fomc"],
        )
        committee = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_COMMITTEE_PROJECTION",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_sep"],
        )
        dealer = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_DEALER_EXPECTATIONS",
            OBSERVED_AT,
            preferred_sources=["new_york_fed_sme"],
        )
        assert actual["value_jsonb"]["kind"] == "actual"
        assert actual["value_jsonb"]["points"][0]["rate_percent"] == "3.625"
        assert committee["value_jsonb"]["points"][0]["participant_distribution"]
        assert dealer["value_jsonb"]["points"][0]["median"] == "3.63"
        comparison = build_policy_comparison(repo, as_of=OBSERVED_AT)
        actual_point = comparison.actual.path.points[0]
        assert actual_point.action == "Hold"
        assert actual_point.vote_split == "12-0"
        assert actual_point.target_range_lower_percent == Decimal("3.5")
        assert actual_point.target_range_upper_percent == Decimal("3.75")
        committee_2026 = next(
            point
            for point in comparison.committee_projection.path.points
            if point.horizon == "2026"
        )
        assert (
            sum(
                point.participant_count
                for point in committee_2026.participant_distribution
            )
            == 18
        )
        dealer_june = next(
            point
            for point in comparison.dealer_expectations.path.points
            if point.horizon_date == date(2026, 6, 17)
        )
        assert dealer_june.respondent_count == 26
        assert comparison.market_implied.path is None


def test_observations_record_the_semantic_parser_that_read_them(
    seeded_db_empty_cards,
) -> None:
    """A corrected reparse must be distinguishable from the row it corrects.

    Acquisition and semantics version independently: the artifact records the
    code that fetched the bytes, the observation records the code that read
    them.  If an observation inherits the artifact's version, a reparse that
    fixes a parsing bug lands beside the wrong row wearing the same stamp and
    nothing tells them apart.
    """
    settings = _settings()

    macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_StatementProvider,
        observed_at=OBSERVED_AT,
    )
    macro_sep_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_SepProvider,
        observed_at=OBSERVED_AT,
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        actual = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_ACTUAL",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_fomc"],
        )
        committee = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_COMMITTEE_PROJECTION",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_sep"],
        )
        assert actual["parser_version"] == "fomc_statement.v2"
        assert committee["parser_version"] == "fed_sep.v2"

        artifacts = conn.execute(
            "SELECT DISTINCT parser_version FROM uw_scan.macro_source_artifacts "
            "WHERE source = 'federal_reserve_sep'"
        ).fetchall()
        assert [row[0] for row in artifacts] == ["fed_sep.v1"]

        # The publisher's own timezone label is retained even when it disagrees
        # with the calendar, so a December EDT/EST drift leaves a durable trace.
        assert committee["value_jsonb"]["calendar_timezone"] == "EDT"
        assert committee["value_jsonb"]["declared_timezone"] == "EDT"


def test_unchanged_rerun_is_one_fact_and_changed_bytes_create_new_vintage(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()
    for _ in range(2):
        result = macro_sep_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_SepProvider,
            observed_at=OBSERVED_AT,
        )
        assert result.status == "ok"
    assert _counts(settings) == (2, 1)

    changed = macro_sep_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_ChangedSepProvider,
        observed_at=OBSERVED_AT.replace(hour=13),
    )
    assert changed.status == "ok"
    assert _counts(settings) == (3, 2)


def test_parser_drift_retains_artifacts_and_degrades_only_failed_source(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()
    actual = macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_StatementProvider,
        observed_at=OBSERVED_AT,
    )
    failed = macro_sep_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_MalformedSepProvider,
        observed_at=OBSERVED_AT,
    )

    assert actual.status == "ok"
    assert failed.status == "degraded"
    assert failed.artifacts_seen == 2
    assert failed.observations_seen == 0
    assert _counts(settings) == (4, 1)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        actual_row = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_ACTUAL",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_fomc"],
        )
        actual_status = repo.fetch_macro_source_status("federal_reserve_fomc")
        sep_status = repo.fetch_macro_source_status("federal_reserve_sep")
        assert actual_row is not None
        assert actual_status["status"] == "ok"
        assert sep_status["status"] == "degraded"
        assert sep_status["consecutive_failures"] == 1
        assert "NormalizationError" in sep_status["error_type"]


def test_unpublished_sme_rerun_keeps_first_retrieval_as_availability(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()
    first = macro_sme_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_SmeProvider,
        observed_at=OBSERVED_AT,
    )
    second = macro_sme_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_SmeProvider,
        observed_at=OBSERVED_AT.replace(hour=13),
    )

    assert (first.status, second.status) == ("ok", "ok")
    assert _counts(settings) == (2, 1)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        row = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_DEALER_EXPECTATIONS",
            OBSERVED_AT.replace(hour=14),
            preferred_sources=["new_york_fed_sme"],
        )
        assert row["available_at"] == OBSERVED_AT


def test_market_shadow_persists_exact_html_unknown_delay_and_distribution(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()

    result = macro_market_implied_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_MarketProvider,
        current_target_range="3.50-3.75%",
        observed_at=OBSERVED_AT,
    )

    assert result.status == "ok"
    assert result.artifacts_seen == 1
    assert result.observations_seen == 1
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        comparison = build_policy_comparison(repo, as_of=OBSERVED_AT)
        market = comparison.market_implied.path
        assert market is not None
        assert market.source == "frenzy_capital"
        assert market.cost_class == "free_third_party_shadow"
        assert market.delay_status == "unknown"
        assert market.delay_minutes is None
        assert market.points[0].rate_percent == Decimal("3.42")
        buckets = market.points[0].probability_distribution
        assert sum(bucket.probability_percent for bucket in buckets) == Decimal("100")
        assert {bucket.label for bucket in buckets} == {
            "Cut 25 bp",
            "Cut 50 bp",
            "Hold",
            "Hike 25 bp",
            "Hike 50 bp",
        }
        artifact = repo.fetch_macro_artifact(market.evidence_refs[0].artifact_id)
        assert artifact["raw_bytes"].startswith(b"\n        <script>")
