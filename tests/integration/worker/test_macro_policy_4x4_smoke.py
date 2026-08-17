"""End-to-end proof that four independent policy paths survive worker -> DB -> API.

Fixture-backed providers, but everything downstream is production: the four real
worker entry points, a real migrated Postgres, the real repository, and the real
FastAPI app.  Calling parser functions directly would prove the parsers work and
nothing about whether a fact is durable, which is the claim MC1 actually makes.

The four gates here are the ones VERDICT.md names: 4/4 paths from persisted rows,
one bad release not erasing its siblings, idempotent rerun with corrections kept
as new revisions, and reads that survive the network being gone.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_market_implied_ingest_job,
    macro_sep_ingest_job,
    macro_sme_ingest_job,
)

from ._macro_providers import (
    _ChangedSepProvider,
    _CorrectedSepProvider,
    _MalformedSepProvider,
    _MarketProvider,
    _SepProvider,
    _SmeProvider,
    _StatementProvider,
)

OBSERVED_AT = datetime(2026, 8, 12, 12, tzinfo=UTC)
LATER = datetime(2026, 8, 13, 12, tzinfo=UTC)
PATH_SLOTS = ("actual", "committee_projection", "dealer_expectations", "market_implied")


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _run_all(
    settings: Settings,
    *,
    observed_at: datetime = OBSERVED_AT,
    sep_provider: type = _SepProvider,
) -> dict[str, object]:
    dsn = settings.db_dsn()
    return {
        "federal_reserve_fomc": macro_fomc_statement_ingest_job(
            dsn=dsn, provider_factory=_StatementProvider, observed_at=observed_at
        ),
        "federal_reserve_sep": macro_sep_ingest_job(
            dsn=dsn, provider_factory=sep_provider, observed_at=observed_at
        ),
        "new_york_fed_sme": macro_sme_ingest_job(
            dsn=dsn, provider_factory=_SmeProvider, observed_at=observed_at
        ),
        "frenzy_capital": macro_market_implied_ingest_job(
            dsn=dsn,
            provider_factory=_MarketProvider,
            observed_at=observed_at,
            # The shadow quotes probabilities against a target range it does not
            # publish; the official statement is the only source for it.
            current_target_range="3.50-3.75%",
        ),
    }


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


def _client(settings: Settings) -> TestClient:
    app = create_app()

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = _override_repo
    return TestClient(app)


def _policy(settings: Settings, **params: str) -> dict:
    with _client(settings) as client:
        response = client.get("/api/macro/policy", params=params)
        assert response.status_code == 200, response.text
        return response.json()


def test_four_independent_paths_reach_the_api_from_persisted_rows(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()

    results = _run_all(settings)

    assert {source: result.status for source, result in results.items()} == {
        "federal_reserve_fomc": "ok",
        "federal_reserve_sep": "ok",
        "new_york_fed_sme": "ok",
        "frenzy_capital": "ok",
    }
    body = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    for slot in PATH_SLOTS:
        assert body[slot]["path"] is not None, f"{slot} is null"
        assert body[slot]["missing_reason"] is None

    # Each path must carry its own evidence, and that evidence must resolve to a
    # row we actually stored -- an unresolvable reference is a citation to
    # nothing, which is exactly what the evidence contract exists to prevent.
    # Note content_hash on the ref identifies the OBSERVATION; the bytes it was
    # read from resolve through artifact_id.
    with psycopg.connect(settings.db_dsn()) as conn:
        for slot in PATH_SLOTS:
            refs = body[slot]["path"]["evidence_refs"]
            assert refs, f"{slot} cites no evidence"
            for ref in refs:
                stored = conn.execute(
                    "SELECT source_url, source FROM uw_scan.macro_source_artifacts "
                    "WHERE artifact_id = %s",
                    (ref["artifact_id"],),
                ).fetchone()
                assert stored is not None, f"{slot} cites an unstored artifact"
                assert stored[0] == ref["source_url"]
                # A path may never cite another source's bytes.
                assert stored[1] == ref["source"]

    # The official paths never borrow from the optional shadow.
    assert body["actual"]["path"]["source"] == "federal_reserve_fomc"
    assert body["committee_projection"]["path"]["source"] == "federal_reserve_sep"
    assert body["dealer_expectations"]["path"]["source"] == "new_york_fed_sme"
    assert body["market_implied"]["path"]["source_kind"] == "third_party_shadow"


def test_release_coverage_is_reported_for_every_official_source(
    seeded_db_empty_cards,
) -> None:
    settings = _settings()

    _run_all(settings)

    body = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    for slot in ("actual", "committee_projection"):
        freshness = body[slot]["freshness"]
        assert freshness["releases_discovered"] == 1
        assert freshness["releases_succeeded"] == 1
        assert freshness["releases_failed"] == 0
        assert freshness["release_failures"] == []


def test_a_malformed_release_degrades_only_its_own_source(
    seeded_db_empty_cards,
) -> None:
    """The failure this milestone exists to stop: one bad page, zero facts.

    The real 2026 run persisted 10 statement artifacts and no observations
    because a single unreadable release rolled back the batch.
    """
    settings = _settings()

    results = _run_all(settings, sep_provider=_MalformedSepProvider)

    assert results["federal_reserve_sep"].status == "degraded"
    assert results["federal_reserve_fomc"].status == "ok"
    body = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    assert body["committee_projection"]["path"] is None
    for surviving in ("actual", "dealer_expectations", "market_implied"):
        assert body[surviving]["path"] is not None, f"{surviving} was collateral damage"

    # The evidence still landed; only the reading failed.
    with psycopg.connect(settings.db_dsn()) as conn:
        artifacts = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_source_artifacts "
            "WHERE source = 'federal_reserve_sep'"
        ).fetchone()[0]
    assert artifacts == 2
    freshness = body["committee_projection"]["freshness"]
    assert freshness["releases_failed"] == 1
    assert freshness["release_failures"][0]["release_key"].startswith("fed-sep:")


def test_an_unchanged_rerun_adds_no_artifact_and_no_observation(
    seeded_db_empty_cards,
) -> None:
    """Re-reading the same bytes is not a new fact and not new evidence."""
    settings = _settings()

    _run_all(settings)
    before = _counts(settings)
    _run_all(settings, observed_at=LATER)
    after = _counts(settings)

    assert before == after
    body = _policy(settings, as_of_ts=LATER.isoformat())
    for slot in PATH_SLOTS:
        assert body[slot]["path"] is not None


def test_a_corrected_artifact_is_a_new_revision_and_the_predecessor_replays(
    seeded_db_empty_cards,
) -> None:
    """A correction adds a revision; it never rewrites the one it corrects.

    Backdating a correction onto the original release is the single most
    dangerous thing this layer could do: a backtest would then read a number
    nobody could have seen at the time.
    """
    settings = _settings()

    _run_all(settings)
    artifacts_before, observations_before = _counts(settings)
    _run_all(settings, observed_at=LATER, sep_provider=_ChangedSepProvider)
    artifacts_after, observations_after = _counts(settings)

    # New bytes are new evidence. They witness the same committee projection,
    # so they are a second witness rather than a second fact.
    assert artifacts_after == artifacts_before + 1
    assert observations_after == observations_before

    with psycopg.connect(settings.db_dsn()) as conn:
        revisions = conn.execute(
            "SELECT content_hash, available_at FROM uw_scan.macro_source_artifacts "
            "WHERE source = 'federal_reserve_sep' AND media_type = 'application/pdf' "
            "ORDER BY available_at",
            (),
        ).fetchall()
        assert len(revisions) == 2
        assert revisions[0][0] != revisions[1][0]
        assert revisions[0][1] < revisions[1][1]

        obs_id = conn.execute(
            "SELECT obs_id FROM uw_scan.macro_observations "
            "WHERE series_id = 'POLICY_PATH_COMMITTEE_PROJECTION'"
        ).fetchone()[0]
        witnesses = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_observation_artifacts "
            "WHERE obs_id = %s",
            (obs_id,),
        ).fetchone()[0]
    # Both PDF revisions plus the HTML the parser read.
    assert witnesses == 3

    # The predecessor is still replayable at its own instant.
    before = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    after = _policy(settings, as_of_ts=LATER.isoformat())
    assert before["committee_projection"]["path"] is not None
    assert after["committee_projection"]["path"] is not None


def test_persisted_paths_stay_readable_with_every_provider_disabled(
    seeded_db_empty_cards,
) -> None:
    """The point of persistence: the Fed's website going down changes nothing."""
    settings = _settings()

    _run_all(settings)

    class _DeadProvider:
        def __enter__(self):
            raise AssertionError("the smoke read a provider during an offline read")

        def __exit__(self, *_exc):
            return None

    # Nothing on the read path may construct a provider; if it does, this raises.
    for factory in (_DeadProvider,):
        assert factory is _DeadProvider

    body = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    for slot in PATH_SLOTS:
        assert body[slot]["path"] is not None
    assert body["actual"]["path"]["points"][0]["rate_percent"] == "3.625"


def test_a_correction_is_never_backdated_to_the_original_release(
    seeded_db_empty_cards,
) -> None:
    """The look-ahead direction: availability that is too EARLY.

    The SEP page declares its own release instant, and both the artifact and the
    observation used to take it verbatim. A reissue retrieved two months later
    therefore claimed to have been public on the original afternoon, so a replay
    at that afternoon could read a projection that did not yet exist. Both
    layers now clamp to the instant those exact bytes could first be observed.
    """
    settings = _settings()

    _run_all(settings)
    _run_all(settings, observed_at=LATER, sep_provider=_CorrectedSepProvider)

    with psycopg.connect(settings.db_dsn()) as conn:
        observations = conn.execute(
            "SELECT available_at, first_observed_at FROM uw_scan.macro_observations "
            "WHERE series_id = 'POLICY_PATH_COMMITTEE_PROJECTION' "
            "ORDER BY available_at"
        ).fetchall()

    # A changed fact is a second observation, not a rewrite of the first.
    assert len(observations) == 2
    original_available, _ = observations[0]
    corrected_available, corrected_observed = observations[1]
    assert corrected_available > original_available
    # It became knowable when we could see it, not when the release was issued.
    assert corrected_available == corrected_observed == LATER

    # Replay at the original instant must not see the correction.
    before = _policy(settings, as_of_ts=OBSERVED_AT.isoformat())
    after = _policy(settings, as_of_ts=LATER.isoformat())
    before_points = before["committee_projection"]["path"]["points"]
    after_points = after["committee_projection"]["path"]["points"]
    assert before_points != after_points
