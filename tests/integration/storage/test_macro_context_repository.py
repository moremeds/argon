from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)
from uw_scan.storage.repository import Repository

RAW_CPI = {"series": "CPIAUCSL", "value": "319.1"}


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _insert_artifact(
    repo: Repository,
    *,
    source: str = "BLS",
    source_kind: str = "official",
    source_record_id: str = "cpi-2026-02-12",
    cost_class: str = "free_official",
    quality_status: str = "valid",
    available_at: datetime = datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
    retrieved_at: datetime = datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
    raw_json: dict[str, object] | None = None,
    content_hash: str | None = None,
    content_length: int | None = None,
) -> int:
    raw_json = raw_json or RAW_CPI
    actual_hash, actual_length = macro_artifact_content_identity(raw_json=raw_json)
    return repo.insert_macro_artifact(
        source=source,
        source_kind=source_kind,
        source_record_id=source_record_id,
        source_url="https://example.test/release",
        published_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        available_at=available_at,
        retrieved_at=retrieved_at,
        content_hash=content_hash or actual_hash,
        parser_version="bls-cpi-v1",
        quality_status=quality_status,
        cost_class=cost_class,
        media_type="application/json",
        content_length=actual_length if content_length is None else content_length,
        raw_json=raw_json,
    )


def _observation(
    artifact_id: int,
    *,
    source: str = "BLS",
    source_record_id: str = "cpi-2026-02-12",
    available_at: datetime = datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
    value: Decimal = Decimal("319.1"),
    domain: str = "inflation",
    series_id: str = "CPI_ALL_ITEMS",
    quality_status: str = "valid",
    cost_class: str = "free_official",
    content_hash: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "artifact_id": artifact_id,
        "domain": domain,
        "series_id": series_id,
        "period_end": date(2026, 1, 31),
        "frequency": "monthly",
        "unit": "index_1982_1984_100",
        "value_numeric": value,
        "value_text": None,
        "value_json": None,
        "source": source,
        "source_record_id": source_record_id,
        "published_at": available_at,
        "available_at": available_at,
        "parser_version": "bls-cpi-v1",
        "quality_status": quality_status,
        "cost_class": cost_class,
    }
    row["content_hash"] = content_hash or macro_observation_content_hash(row)
    return row


def test_identical_observation_updates_only_last_seen(repo: Repository) -> None:
    artifact_id = _insert_artifact(repo)
    first_seen = datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
    later_seen = datetime(2026, 2, 13, 9, tzinfo=UTC)

    assert (
        repo.insert_macro_observations([_observation(artifact_id)], seen_at=first_seen)
        == 1
    )
    assert (
        repo.insert_macro_observations([_observation(artifact_id)], seen_at=later_seen)
        == 1
    )

    rows = repo.fetch_macro_observation_history("CPI_ALL_ITEMS", date(2026, 1, 31))
    assert len(rows) == 1
    assert rows[0]["value_numeric"] == Decimal("319.1")
    assert rows[0]["first_observed_at"] == first_seen
    assert rows[0]["last_seen_at"] == later_seen


def test_restatement_preserves_predecessor_for_as_of_replay(repo: Repository) -> None:
    first_artifact = _insert_artifact(repo)
    revised_artifact = _insert_artifact(
        repo,
        source_record_id="cpi-2026-03-01-correction",
        raw_json={"series": "CPIAUCSL", "value": "319.3"},
    )
    first_available = datetime(2026, 2, 12, 13, 30, tzinfo=UTC)
    revised_available = datetime(2026, 3, 1, 15, tzinfo=UTC)

    repo.insert_macro_observations(
        [_observation(first_artifact, available_at=first_available)],
        seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
    )
    repo.insert_macro_observations(
        [
            _observation(
                revised_artifact,
                source_record_id="cpi-2026-03-01-correction",
                available_at=revised_available,
                value=Decimal("319.3"),
            )
        ],
        seen_at=datetime(2026, 3, 1, 15, 1, tzinfo=UTC),
    )

    before_revision = repo.fetch_macro_observation_as_of(
        "CPI_ALL_ITEMS",
        date(2026, 1, 31),
        datetime(2026, 2, 20, tzinfo=UTC),
        preferred_sources=["BLS"],
    )
    after_revision = repo.fetch_macro_observation_as_of(
        "CPI_ALL_ITEMS",
        date(2026, 1, 31),
        datetime(2026, 3, 2, tzinfo=UTC),
        preferred_sources=["BLS"],
    )

    assert before_revision is not None
    assert before_revision["value_numeric"] == Decimal("319.1")
    assert after_revision is not None
    assert after_revision["value_numeric"] == Decimal("319.3")
    assert (
        len(repo.fetch_macro_observation_history("CPI_ALL_ITEMS", date(2026, 1, 31)))
        == 2
    )


def test_source_precedence_selects_official_without_deleting_shadow(
    repo: Repository,
) -> None:
    official_artifact = _insert_artifact(repo)
    shadow_artifact = _insert_artifact(
        repo,
        source="SHADOW",
        source_kind="third_party_shadow",
        source_record_id="shadow-cpi-2026-02-13",
        cost_class="free_third_party_shadow",
    )
    repo.insert_macro_observations(
        [_observation(official_artifact)],
        seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
    )
    repo.insert_macro_observations(
        [
            {
                **_observation(
                    shadow_artifact,
                    source="SHADOW",
                    source_record_id="shadow-cpi-2026-02-13",
                    available_at=datetime(2026, 2, 13, 13, 30, tzinfo=UTC),
                    value=Decimal("319.8"),
                    cost_class="free_third_party_shadow",
                ),
            }
        ],
        seen_at=datetime(2026, 2, 13, 13, 31, tzinfo=UTC),
    )

    selected = repo.fetch_macro_observation_as_of(
        "CPI_ALL_ITEMS",
        date(2026, 1, 31),
        datetime(2026, 2, 14, tzinfo=UTC),
        preferred_sources=["BLS", "SHADOW"],
    )
    history = repo.fetch_macro_observation_history("CPI_ALL_ITEMS", date(2026, 1, 31))
    series = repo.fetch_macro_series_as_of(
        "CPI_ALL_ITEMS",
        datetime(2026, 2, 14, tzinfo=UTC),
        preferred_sources=["BLS", "SHADOW"],
    )

    assert selected is not None
    assert selected["source"] == "BLS"
    assert [row["source"] for row in series] == ["BLS"]
    assert {row["source"] for row in history} == {"BLS", "SHADOW"}


def test_artifact_hash_identity_rejects_conflicting_immutable_metadata(
    repo: Repository,
) -> None:
    artifact_id = _insert_artifact(repo)

    with pytest.raises(ValueError, match="artifact identity collision"):
        repo.insert_macro_artifact(
            source="BLS",
            source_kind="official",
            source_record_id="cpi-2026-02-12",
            source_url="https://example.test/different-release",
            published_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
            available_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
            retrieved_at=datetime(2026, 2, 13, 13, 31, tzinfo=UTC),
            content_hash=macro_artifact_content_identity(raw_json=RAW_CPI)[0],
            parser_version="bls-cpi-v2",
            quality_status="valid",
            cost_class="free_official",
            media_type="application/json",
            content_length=macro_artifact_content_identity(raw_json=RAW_CPI)[1],
            raw_json=RAW_CPI,
        )

    assert artifact_id == _insert_artifact(repo)


def test_observation_hash_identity_rejects_conflicting_immutable_value(
    repo: Repository,
) -> None:
    artifact_id = _insert_artifact(repo)
    row = _observation(artifact_id)
    seen_at = datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
    repo.insert_macro_observations([row], seen_at=seen_at)

    with pytest.raises(ValueError, match="observation content_hash does not match"):
        repo.insert_macro_observations(
            [{**row, "value_numeric": Decimal("999.9")}],
            seen_at=datetime(2026, 2, 13, 13, 31, tzinfo=UTC),
        )

    history = repo.fetch_macro_observation_history("CPI_ALL_ITEMS", date(2026, 1, 31))
    assert len(history) == 1
    assert history[0]["value_numeric"] == Decimal("319.1")


def test_invalid_and_quarantined_observations_are_not_pit_eligible(
    repo: Repository,
) -> None:
    artifact_id = _insert_artifact(repo)
    for quality, value, suffix in (
        ("invalid", Decimal("999.0"), "invalid"),
        ("quarantined", Decimal("998.0"), "quarantined"),
    ):
        repo.insert_macro_observations(
            [
                {
                    **_observation(
                        artifact_id,
                        value=value,
                        quality_status=quality,
                    ),
                }
            ],
            seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        )

    assert (
        repo.fetch_macro_observation_as_of(
            "CPI_ALL_ITEMS",
            date(2026, 1, 31),
            datetime(2026, 2, 20, tzinfo=UTC),
            preferred_sources=["BLS"],
        )
        is None
    )


def test_conservative_availability_may_follow_first_observation(
    repo: Repository,
) -> None:
    artifact_id = _insert_artifact(repo)
    seen_at = datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
    safe_at = datetime(2026, 2, 17, 13, 30, tzinfo=UTC)
    row = {
        **_observation(artifact_id, available_at=safe_at),
        "published_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
    }
    row["content_hash"] = macro_observation_content_hash(row)

    repo.insert_macro_observations([row], seen_at=seen_at)

    assert (
        repo.fetch_macro_observation_as_of(
            "CPI_ALL_ITEMS",
            date(2026, 1, 31),
            datetime(2026, 2, 16, tzinfo=UTC),
            preferred_sources=["BLS"],
        )
        is None
    )
    after_lag = repo.fetch_macro_observation_as_of(
        "CPI_ALL_ITEMS",
        date(2026, 1, 31),
        datetime(2026, 2, 18, tzinfo=UTC),
        preferred_sources=["BLS"],
    )
    assert after_lag is not None
    assert after_lag["first_observed_at"] == seen_at
    assert after_lag["available_at"] == safe_at


def test_repository_rejects_naive_time_and_non_sha256_hash(repo: Repository) -> None:
    with pytest.raises(ValueError, match="retrieved_at must be timezone-aware"):
        repo.insert_macro_artifact(
            source="BLS",
            source_kind="official",
            source_record_id="naive-time",
            source_url=None,
            published_at=None,
            available_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
            retrieved_at=datetime(2026, 2, 12, 13, 31),
            content_hash=macro_artifact_content_identity(raw_json={})[0],
            parser_version="bls-cpi-v1",
            quality_status="valid",
            cost_class="free_official",
            media_type="application/json",
            content_length=2,
            raw_json={},
        )

    with pytest.raises(ValueError, match="content_hash must be lowercase SHA-256"):
        repo.insert_macro_artifact(
            source="BLS",
            source_kind="official",
            source_record_id="bad-hash",
            source_url=None,
            published_at=None,
            available_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
            retrieved_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
            content_hash="not-a-sha256",
            parser_version="bls-cpi-v1",
            quality_status="valid",
            cost_class="free_official",
            media_type="application/json",
            content_length=2,
            raw_json={},
        )


def test_artifact_hash_length_and_sighting_are_content_derived(
    repo: Repository,
) -> None:
    with pytest.raises(ValueError, match="artifact content_hash does not match"):
        _insert_artifact(repo, source_record_id="wrong-hash", content_hash="a" * 64)

    with pytest.raises(ValueError, match="artifact content_length does not match"):
        _insert_artifact(repo, source_record_id="wrong-length", content_length=999)

    first = datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
    later = datetime(2026, 2, 13, 13, 31, tzinfo=UTC)
    artifact_id = _insert_artifact(repo, retrieved_at=first)
    assert artifact_id == _insert_artifact(repo, retrieved_at=later)

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT retrieved_at, last_seen_at FROM uw_scan.macro_source_artifacts "
            "WHERE artifact_id = %s",
            (artifact_id,),
        )
        assert cur.fetchone() == (first, later)


def test_one_artifact_can_supply_multiple_macro_domains(repo: Repository) -> None:
    artifact_id = _insert_artifact(
        repo,
        source="FED",
        source_record_id="fomc-2026-06-17-sep",
    )
    rows = [
        _observation(
            artifact_id,
            source="FED",
            source_record_id="fomc-2026-06-17-sep",
            domain="inflation",
            series_id="SEP_PCE_MEDIAN",
            value=Decimal("2.2"),
        ),
        _observation(
            artifact_id,
            source="FED",
            source_record_id="fomc-2026-06-17-sep",
            domain="policy_rates",
            series_id="SEP_FED_FUNDS_MEDIAN",
            value=Decimal("3.4"),
        ),
    ]

    assert (
        repo.insert_macro_observations(
            rows, seen_at=datetime(2026, 6, 17, 18, 1, tzinfo=UTC)
        )
        == 2
    )


def test_artifact_bounds_observation_availability_and_quality(
    repo: Repository,
) -> None:
    artifact_available = datetime(2026, 2, 12, 13, 30, tzinfo=UTC)
    artifact_id = _insert_artifact(repo, available_at=artifact_available)
    early = _observation(
        artifact_id,
        available_at=datetime(2026, 2, 12, 13, 29, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="precedes artifact available_at"):
        repo.insert_macro_observations(
            [early], seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
        )

    quarantined_artifact = _insert_artifact(
        repo,
        source_record_id="quarantined-artifact",
        quality_status="quarantined",
    )
    with pytest.raises(ValueError, match="quality exceeds artifact quality"):
        repo.insert_macro_observations(
            [
                _observation(
                    quarantined_artifact,
                    source_record_id="quarantined-artifact",
                )
            ],
            seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        )

    partial_artifact = _insert_artifact(
        repo,
        source_record_id="partial-artifact",
        quality_status="partial",
    )
    with pytest.raises(ValueError, match="quality exceeds artifact quality"):
        repo.insert_macro_observations(
            [
                _observation(
                    partial_artifact,
                    source_record_id="partial-artifact",
                )
            ],
            seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        )


def test_database_triggers_prevent_historical_rewrites(repo: Repository) -> None:
    artifact_id = _insert_artifact(repo)
    repo.insert_macro_observations(
        [_observation(artifact_id)],
        seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        with repo.conn.transaction():
            repo.conn.execute(
                "UPDATE uw_scan.macro_source_artifacts "
                "SET quality_status = 'quarantined' WHERE artifact_id = %s",
                (artifact_id,),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with repo.conn.transaction():
            repo.conn.execute(
                "DELETE FROM uw_scan.macro_observations WHERE artifact_id = %s",
                (artifact_id,),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with repo.conn.transaction():
            repo.conn.execute(
                "UPDATE uw_scan.macro_observations "
                "SET value_numeric = 999 WHERE artifact_id = %s",
                (artifact_id,),
            )


def test_database_triggers_recompute_artifact_identity(repo: Repository) -> None:
    params = (
        "BLS",
        "official",
        "direct-sql-invalid-hash",
        datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        "a" * 64,
        "direct-v1",
        "valid",
        "free_official",
        "application/json",
        2,
        Jsonb({}),
    )
    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="content_hash does not match",
    ):
        with repo.conn.transaction():
            repo.conn.execute(
                """
                INSERT INTO uw_scan.macro_source_artifacts (
                  source, source_kind, source_record_id,
                  available_at, retrieved_at, last_seen_at,
                  content_hash, parser_version, quality_status, cost_class,
                  media_type, content_length, raw_jsonb
                ) VALUES (
                  %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (*params[:5], params[4], *params[5:]),
            )


def test_database_json_canonicalization_matches_python(repo: Repository) -> None:
    raw_json = {
        "a": 1,
        "B": 2,
        "é": 3,
        "黄金": {"Z": 6, "a": 1},
    }
    artifact_id = _insert_artifact(
        repo,
        source_record_id="mixed-json-keys",
        raw_json=raw_json,
    )
    row = _observation(
        artifact_id,
        source_record_id="mixed-json-keys",
        series_id="MIXED_JSON_VALUE",
    )
    row.update(
        value_numeric=None,
        value_json={"黄金": "x", "a": 1, "B": 2},
    )
    row["content_hash"] = macro_observation_content_hash(row)

    assert (
        repo.insert_macro_observations(
            [row], seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
        )
        == 1
    )


def test_database_rejects_nonfinite_numeric_observation(repo: Repository) -> None:
    artifact_id = _insert_artifact(repo, source_record_id="direct-sql-nan")
    with pytest.raises(
        psycopg.errors.NumericValueOutOfRange,
        match="macro numeric values must be finite",
    ):
        with repo.conn.transaction():
            repo.conn.execute(
                """
                INSERT INTO uw_scan.macro_observations (
                  artifact_id, domain, series_id, period_end, frequency, unit,
                  value_numeric, source, source_record_id,
                  available_at, first_observed_at, last_seen_at,
                  content_hash, parser_version, quality_status, cost_class
                ) VALUES (
                  %s, 'inflation', 'DIRECT_SQL_NAN', '2026-01-31',
                  'monthly', 'index', 'NaN'::numeric,
                  'BLS', 'direct-sql-nan',
                  '2026-02-12 13:30:00+00', '2026-02-12 13:31:00+00',
                  '2026-02-12 13:31:00+00', %s,
                  'direct-v1', 'valid', 'free_official'
                )
                """,
                (artifact_id, "a" * 64),
            )


def test_pit_reads_require_aware_as_of_and_explicit_source_order(
    repo: Repository,
) -> None:
    with pytest.raises(ValueError, match="preferred_sources must not be empty"):
        repo.fetch_macro_observation_as_of(
            "CPI_ALL_ITEMS",
            date(2026, 1, 31),
            datetime(2026, 2, 20, tzinfo=UTC),
            preferred_sources=[],
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        repo.fetch_macro_series_as_of(
            "CPI_ALL_ITEMS",
            datetime(2026, 2, 20, tzinfo=UTC),
            preferred_sources=["BLS", "BLS"],
        )
    with pytest.raises(ValueError, match="preferred_sources must not be empty"):
        repo.fetch_macro_series_as_of(
            "CPI_ALL_ITEMS",
            datetime(2026, 2, 20, tzinfo=UTC),
            preferred_sources=[],
        )
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        repo.fetch_macro_series_as_of(
            "CPI_ALL_ITEMS",
            datetime(2026, 2, 20),
            preferred_sources=["BLS"],
        )


def test_nonproduction_source_predicate_rejects_local_database(
    repo: Repository,
) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT uw_scan.macro_source_kind_allowed(%s, %s)",
            ("mock", "option_wizard_local"),
        )
        assert cur.fetchone() == (False,)
        cur.execute(
            "SELECT uw_scan.macro_source_kind_allowed(%s, %s)",
            ("mock", "option_wizard_test_gw0"),
        )
        assert cur.fetchone() == (True,)
