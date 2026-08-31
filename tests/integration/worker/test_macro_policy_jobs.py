from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesSourceBundle
from uw_scan.sources.fomc_statement import FomcStatementBundle
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_market_implied_ingest_job,
    macro_sep_ingest_job,
    macro_sme_ingest_job,
)

from ._macro_providers import (  # noqa: E402 - local helper, not a test module
    FIXTURES,
    _candidate,
    _ChangedSepProvider,
    _MalformedSepProvider,
    _MarketProvider,
    _outcome,
    _SepProvider,
    _SmeProvider,
    _StatementProvider,
)

OBSERVED_AT = datetime(2026, 8, 12, 12, tzinfo=UTC)


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


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


def test_unchanged_rerun_is_one_fact_and_changed_bytes_are_another_witness(
    seeded_db_empty_cards,
) -> None:
    """Changed BYTES are not a changed FACT.

    ``_ChangedSepProvider`` appends a byte to the PDF. That is a real new
    artifact and must be kept as exact evidence -- but the HTML the parser reads
    is identical and the committee's projections did not move, so it is the same
    published fact. Counting it as a new vintage invented a policy revision the
    Fed never issued.
    """
    settings = _settings()
    for _ in range(2):
        result = macro_sep_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_SepProvider,
            observed_at=OBSERVED_AT,
        )
        assert result.status == "ok"
        assert result.releases_discovered == 1
        assert result.releases_succeeded == 1
    assert _counts(settings) == (2, 1)

    changed = macro_sep_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_ChangedSepProvider,
        observed_at=OBSERVED_AT.replace(hour=13),
    )
    assert changed.status == "ok"
    # Three artifacts, still one fact.
    assert _counts(settings) == (3, 1)

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        row = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_COMMITTEE_PROJECTION",
            OBSERVED_AT.replace(hour=14),
            preferred_sources=["federal_reserve_sep"],
        )
        lineage = repo.fetch_macro_observation_artifacts(row["obs_id"])
        # The HTML the parser read, plus both PDF revisions as witnesses.
        assert sorted(item["relation"] for item in lineage) == [
            "corroborates",
            "corroborates",
            "parsed_from",
        ]
        parsed = [
            item for item in lineage if item["relation"] == "parsed_from"
        ]
        assert len(parsed) == 1
        artifact = repo.fetch_macro_artifact(parsed[0]["artifact_id"])
        assert artifact["media_type"] == "text/html"


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
        # The source-level error is a stable aggregate; the specific parse
        # failure and the release it belongs to live in the message and in the
        # per-release catalog.
        assert sep_status["error_type"] == "MacroReleaseFailures"
        assert "NormalizationError" in sep_status["error_message"]
        assert failed.failed_release_keys == ("fed-sep:fomcprojtabl20260617",)
        catalog = repo.fetch_macro_release_status(
            source="federal_reserve_sep",
            release_key="fed-sep:fomcprojtabl20260617",
        )
        assert catalog["status"] == "failed"
        assert catalog["error_type"] == "uw_scan.normalize.NormalizationError"
        assert catalog["latest_artifact_id"] is not None


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


def test_market_shadow_dynamic_html_is_another_witness_not_another_fact(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()

    class _ChangedMarketProvider(_MarketProvider):
        def fetch_bundle(self, *, retrieved_at):
            bundle = super().fetch_bundle(retrieved_at=retrieved_at)
            assert bundle.artifact.raw_bytes is not None
            return FedFundsFuturesSourceBundle.from_bytes(
                source_url=bundle.artifact.source_url or "",
                raw_bytes=bundle.artifact.raw_bytes + b"<!-- cloudflare-ray:changed -->",
                retrieved_at=retrieved_at,
            )

    first = macro_market_implied_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_MarketProvider,
        current_target_range="3.50-3.75%",
        observed_at=OBSERVED_AT,
    )
    second = macro_market_implied_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_ChangedMarketProvider,
        current_target_range="3.50-3.75%",
        observed_at=OBSERVED_AT.replace(hour=13),
    )

    assert first.observations_seen == 1
    assert second.observations_seen == 0
    assert _counts(settings) == (2, 1)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        row = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_MARKET_IMPLIED",
            OBSERVED_AT.replace(hour=14),
            preferred_sources=["frenzy_capital"],
        )
        lineage = repo.fetch_macro_observation_artifacts(row["obs_id"])
        assert [item["relation"] for item in lineage] == [
            "parsed_from",
            "parsed_from",
        ]


_2022_STATEMENT = "fomc-statement:monetary20220316a"
_2026_STATEMENT = "fomc-statement:monetary20260617a"
_2020_STATEMENT = "fomc-statement:monetary20200323a"


class _MixedStatementProvider:
    """Three releases: valid, malformed, valid -- in that order.

    The malformed one sits in the middle deliberately. Under batch persistence
    it took the release before it down as well, so ordering proves the isolation
    rather than just the last-writer surviving.
    """

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_outcomes(self, *, years, retrieved_at):
        good_2020 = FomcStatementBundle.from_bytes(
            meeting_date=date(2020, 3, 23),
            accessible_url=(
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20200323a.htm"
            ),
            accessible_bytes=(FIXTURES / "fomc_statement_2020_03_23.html").read_bytes(),
            pdf_url=(
                "https://www.federalreserve.gov/monetarypolicy/files/"
                "monetary20200323a1.pdf"
            ),
            pdf_bytes=b"%PDF-1.4 2020-03-23",
            retrieved_at=retrieved_at,
        )
        broken = FomcStatementBundle.from_bytes(
            meeting_date=date(2022, 3, 16),
            accessible_url=(
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20220316a.htm"
            ),
            accessible_bytes=b"<p>Release Date: March 16, 2022</p><p>nothing</p>",
            pdf_url=(
                "https://www.federalreserve.gov/monetarypolicy/files/"
                "monetary20220316a1.pdf"
            ),
            pdf_bytes=b"%PDF-1.4 2022-03-16",
            retrieved_at=retrieved_at,
        )
        good_2026 = _StatementProvider()._bundles(retrieved_at)[0]
        return [
            _outcome(
                _candidate(
                    _2020_STATEMENT, "statement", date(2020, 3, 23), "notation_vote"
                ),
                good_2020,
            ),
            _outcome(
                _candidate(
                    _2022_STATEMENT, "statement", date(2022, 3, 16), "scheduled_meeting"
                ),
                broken,
            ),
            _outcome(
                _candidate(
                    _2026_STATEMENT, "statement", date(2026, 6, 17), "scheduled_meeting"
                ),
                good_2026,
            ),
        ]


class _FetchOnlyStatementProvider(_StatementProvider):
    """Discovery found the release but only one of its two files came back."""

    def fetch_outcomes(self, *, years, retrieved_at):
        bundle = self._bundles(retrieved_at)[0]
        return [
            _outcome(
                _candidate(
                    _2026_STATEMENT, "statement", date(2026, 6, 17), "scheduled_meeting"
                ),
                None,
                artifacts=(bundle.accessible_artifact,),
                error=("httpx.HTTPStatusError", "503 fetching the PDF"),
            )
        ]


def test_one_bad_release_does_not_erase_the_good_ones(seeded_db_empty_cards) -> None:
    """The bug this milestone exists for: 10 artifacts, 0 facts.

    A single statement the parser could not read used to roll back every
    observation in the same run, so a night with one publisher oddity produced
    no policy data at all.
    """
    settings = _settings()

    result = macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_MixedStatementProvider,
        observed_at=OBSERVED_AT,
        years=(2020, 2022, 2026),
    )

    assert result.status == "degraded"
    assert result.releases_discovered == 3
    assert result.releases_succeeded == 2
    assert result.releases_failed == 1
    assert result.failed_release_keys == (_2022_STATEMENT,)
    # Every artifact survives, including the unreadable release's.
    assert result.artifacts_seen == 6
    assert result.observations_seen == 2

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        assert (
            conn.execute(
                "SELECT count(*) FROM uw_scan.macro_observations "
                "WHERE series_id = 'POLICY_PATH_ACTUAL'"
            ).fetchone()[0]
            == 2
        )
        statuses = {
            row["release_key"]: row["status"]
            for row in repo.fetch_macro_release_statuses(
                sources=["federal_reserve_fomc"]
            )
        }
        assert statuses == {
            _2020_STATEMENT: "ok",
            _2022_STATEMENT: "failed",
            _2026_STATEMENT: "ok",
        }


def test_release_isolation_is_idempotent_across_reruns(seeded_db_empty_cards) -> None:
    settings = _settings()
    for _ in range(2):
        result = macro_fomc_statement_ingest_job(
            dsn=settings.db_dsn(),
            provider_factory=_MixedStatementProvider,
            observed_at=OBSERVED_AT,
            years=(2020, 2022, 2026),
        )
        assert result.releases_failed == 1

    with psycopg.connect(settings.db_dsn()) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM uw_scan.macro_observations"
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM uw_scan.macro_source_artifacts"
            ).fetchone()[0]
            == 6
        )


def test_a_fetch_only_candidate_is_recorded_as_artifact_only(
    seeded_db_empty_cards,
) -> None:
    """Evidence that arrives incomplete is kept and labelled, never silently absent."""
    settings = _settings()

    result = macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_FetchOnlyStatementProvider,
        observed_at=OBSERVED_AT,
    )

    assert result.status == "degraded"
    assert result.releases_failed == 1
    assert result.artifacts_seen == 1
    assert result.observations_seen == 0

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        catalog = repo.fetch_macro_release_status(
            source="federal_reserve_fomc", release_key=_2026_STATEMENT
        )
        assert catalog["status"] == "artifact_only"
        assert catalog["error_type"] == "httpx.HTTPStatusError"


def test_observation_references_the_html_the_parser_actually_read(
    seeded_db_empty_cards,
) -> None:
    """The PDF is a sibling witness, not the source of the facts."""
    settings = _settings()
    macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_StatementProvider,
        observed_at=OBSERVED_AT,
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        row = repo.fetch_latest_macro_observation_as_of(
            "POLICY_PATH_ACTUAL",
            OBSERVED_AT,
            preferred_sources=["federal_reserve_fomc"],
        )
        parsed = repo.fetch_macro_artifact(row["artifact_id"])
        assert parsed["media_type"] == "text/html"

        lineage = repo.fetch_macro_observation_artifacts(row["obs_id"])
        relations = {item["relation"] for item in lineage}
        assert relations == {"parsed_from", "corroborates"}
        sibling = next(
            item for item in lineage if item["relation"] == "corroborates"
        )
        assert repo.fetch_macro_artifact(sibling["artifact_id"])["media_type"] == (
            "application/pdf"
        )
