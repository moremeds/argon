from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
    macro_policy_semantic_hash,
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
    vintage_bearing: bool = False,
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
        vintage_bearing=vintage_bearing,
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


def _insert_undated_artifact(
    repo: Repository, *, published_at: datetime | None, available_at: datetime
) -> int:
    """Persist evidence whose publication instant may not be known yet."""
    actual_hash, actual_length = macro_artifact_content_identity(raw_json=RAW_CPI)
    return repo.insert_macro_artifact(
        source="federal_reserve_sep",
        source_kind="official",
        source_record_id="fed-sep:fomcprojtabl20251210:html",
        source_url="https://example.test/fomcprojtabl20251210.htm",
        published_at=published_at,
        available_at=available_at,
        retrieved_at=datetime(2025, 12, 10, 23, 5, tzinfo=UTC),
        content_hash=actual_hash,
        parser_version="fed_sep.v1",
        quality_status="partial",
        cost_class="free_official",
        media_type="application/json",
        content_length=actual_length,
        raw_json=RAW_CPI,
    )


def test_unknown_publication_instant_is_resolvable_once(repo: Repository) -> None:
    """An unreadable instant must not make the evidence row permanent scrap.

    The bytes are persisted before parsing, so a release whose "For release at"
    line the parser cannot read lands with published_at NULL and availability
    falling back to our retrieval clock.  A later parser that can read it must be
    able to correct availability onto the publisher's own instant -- otherwise the
    row stays invisible to every point-in-time read before the backfill.
    """
    retrieved = datetime(2025, 12, 10, 23, 5, tzinfo=UTC)
    artifact_id = _insert_undated_artifact(
        repo, published_at=None, available_at=retrieved
    )
    stored = repo.fetch_macro_artifact(artifact_id)
    assert stored is not None
    assert stored["published_at"] is None
    assert stored["available_at"] == retrieved

    published = datetime(2025, 12, 10, 19, 0, tzinfo=UTC)
    assert (
        _insert_undated_artifact(repo, published_at=published, available_at=published)
        == artifact_id
    )
    resolved = repo.fetch_macro_artifact(artifact_id)
    assert resolved is not None
    assert resolved["published_at"] == published
    assert resolved["available_at"] == published


def test_resolved_publication_instant_is_then_immutable(repo: Repository) -> None:
    published = datetime(2025, 12, 10, 19, 0, tzinfo=UTC)
    artifact_id = _insert_undated_artifact(
        repo, published_at=published, available_at=published
    )

    with pytest.raises(ValueError, match="artifact identity collision"):
        _insert_undated_artifact(
            repo,
            published_at=datetime(2025, 12, 10, 18, 0, tzinfo=UTC),
            available_at=datetime(2025, 12, 10, 18, 0, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="artifact identity collision"):
        _insert_undated_artifact(
            repo,
            published_at=None,
            available_at=datetime(2025, 12, 10, 23, 5, tzinfo=UTC),
        )

    stored = repo.fetch_macro_artifact(artifact_id)
    assert stored is not None
    assert stored["published_at"] == published


def test_resolution_must_carry_availability_to_the_published_instant(
    repo: Repository,
) -> None:
    """Resolving the instant may not leave availability on the retrieval clock.

    ``insert_macro_artifact`` normalizes availability onto the resolved instant,
    so this guard exists for direct SQL: a hand-written UPDATE must not be able
    to claim a publication instant while leaving the release looking unavailable
    until our retrieval clock.
    """
    retrieved = datetime(2025, 12, 10, 23, 5, tzinfo=UTC)
    artifact_id = _insert_undated_artifact(
        repo, published_at=None, available_at=retrieved
    )

    with pytest.raises(psycopg.errors.CheckViolation, match="availability instant"):
        with repo.conn.transaction():
            repo.conn.execute(
                "UPDATE uw_scan.macro_source_artifacts "
                "SET published_at = %s WHERE artifact_id = %s",
                (datetime(2025, 12, 10, 19, 0, tzinfo=UTC), artifact_id),
            )

    # The same UPDATE carrying availability along is the legitimate repair.
    with repo.conn.transaction():
        repo.conn.execute(
            "UPDATE uw_scan.macro_source_artifacts "
            "SET published_at = %s, available_at = %s WHERE artifact_id = %s",
            (
                datetime(2025, 12, 10, 19, 0, tzinfo=UTC),
                datetime(2025, 12, 10, 19, 0, tzinfo=UTC),
                artifact_id,
            ),
        )


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


def test_latest_macro_observation_as_of_hides_sep_until_release(
    repo: Repository,
) -> None:
    released_at = datetime(2026, 6, 17, 18, tzinfo=UTC)
    artifact_id = _insert_artifact(
        repo,
        source="FED_SEP",
        source_record_id="fed-sep:2026-06-17",
        available_at=released_at,
        retrieved_at=datetime(2026, 6, 17, 18, 1, tzinfo=UTC),
        raw_json={"horizon": "2026", "median": "3.8"},
    )
    row = _observation(
        artifact_id,
        source="FED_SEP",
        source_record_id="fed-sep:2026-06-17",
        available_at=released_at,
        value=Decimal("3.8"),
        domain="policy_rates",
        series_id="POLICY_COMMITTEE_PROJECTION",
    )
    row["period_end"] = date(2026, 12, 31)
    row["content_hash"] = macro_observation_content_hash(row)
    repo.insert_macro_observations(
        [row],
        seen_at=datetime(2026, 6, 17, 18, 1, tzinfo=UTC),
    )

    before = repo.fetch_latest_macro_observation_as_of(
        "POLICY_COMMITTEE_PROJECTION",
        datetime(2026, 6, 17, 17, 59, 59, tzinfo=UTC),
        preferred_sources=["FED_SEP"],
    )
    after = repo.fetch_latest_macro_observation_as_of(
        "POLICY_COMMITTEE_PROJECTION",
        datetime(2026, 6, 17, 18, tzinfo=UTC),
        preferred_sources=["FED_SEP"],
    )

    assert before is None
    assert after is not None
    assert after["value_numeric"] == Decimal("3.8")
    assert after["source_url"] == "https://example.test/release"


_FOMC = "federal_reserve_fomc"
_STATEMENT_KEY = "fomc-statement:monetary20260429a"
_ATTEMPT_1 = datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
_ATTEMPT_2 = datetime(2026, 4, 30, 18, 5, tzinfo=UTC)
_ATTEMPT_3 = datetime(2026, 5, 1, 18, 5, tzinfo=UTC)


def _release_status(repo: Repository, **overrides: object) -> None:
    kwargs: dict[str, object] = {
        "source": _FOMC,
        "release_key": _STATEMENT_KEY,
        "release_type": "statement",
        "status": "discovered",
        "event_date": date(2026, 4, 29),
        "event_class": "scheduled_meeting",
        "discovery_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "parser_version": "fomc_statement.v2",
        "last_attempt_at": _ATTEMPT_1,
    }
    kwargs.update(overrides)
    repo.upsert_macro_release_status(**kwargs)  # type: ignore[arg-type]


def _statement_artifact(repo: Repository, *, record_id: str, marker: str) -> int:
    payload = {"release": marker}
    content_hash, content_length = macro_artifact_content_identity(raw_json=payload)
    return repo.insert_macro_artifact(
        source=_FOMC,
        source_kind="official",
        source_record_id=record_id,
        source_url="https://www.federalreserve.gov/newsevents/monetary20260429a.htm",
        published_at=datetime(2026, 4, 29, 18, 0, tzinfo=UTC),
        available_at=datetime(2026, 4, 29, 18, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 4, 29, 18, 5, tzinfo=UTC),
        content_hash=content_hash,
        parser_version="fomc_statement.v1",
        quality_status="partial",
        cost_class="free_official",
        media_type="application/json",
        content_length=content_length,
        raw_json=payload,
    )


def test_release_status_retains_a_past_success_through_a_later_failure(
    repo: Repository,
) -> None:
    """failed -> ok -> failed must not erase that the release once ingested.

    Source-level health collapses to the newest attempt, which is exactly how an
    outage erases its own evidence. A backfill needs to know this release was
    good on the 30th even though tonight's run broke.
    """
    artifact_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="first"
    )

    _release_status(
        repo, status="failed", error_type="NormalizationError", error_message="boom"
    )
    first = repo.fetch_macro_release_status(source=_FOMC, release_key=_STATEMENT_KEY)
    assert first is not None
    assert first["status"] == "failed"
    assert first["last_success_at"] is None

    _release_status(
        repo,
        status="ok",
        last_attempt_at=_ATTEMPT_2,
        artifact_source_record_id=f"{_STATEMENT_KEY}:html",
        latest_artifact_id=artifact_id,
        success_artifact_id=artifact_id,
    )
    good = repo.fetch_macro_release_status(source=_FOMC, release_key=_STATEMENT_KEY)
    assert good is not None
    assert good["status"] == "ok"
    assert good["last_success_at"] == _ATTEMPT_2
    assert good["last_success_artifact_id"] == artifact_id
    assert good["error_type"] is None

    _release_status(
        repo,
        status="failed",
        last_attempt_at=_ATTEMPT_3,
        error_type="httpx.ConnectError",
        error_message="publisher unreachable",
    )
    after = repo.fetch_macro_release_status(source=_FOMC, release_key=_STATEMENT_KEY)
    assert after is not None
    assert after["status"] == "failed"
    assert after["last_attempt_at"] == _ATTEMPT_3
    # The success survives the failure.
    assert after["last_success_at"] == _ATTEMPT_2
    assert after["last_success_artifact_id"] == artifact_id


def test_release_statuses_are_independent_within_one_source(repo: Repository) -> None:
    _release_status(repo, status="discovered")
    _release_status(
        repo,
        release_key="fomc-statement:monetary20260617a",
        event_date=date(2026, 6, 17),
        status="failed",
        error_type="NormalizationError",
        error_message="unreadable",
    )

    rows = repo.fetch_macro_release_statuses(sources=[_FOMC])
    assert {row["release_key"]: row["status"] for row in rows} == {
        _STATEMENT_KEY: "discovered",
        "fomc-statement:monetary20260617a": "failed",
    }
    failed = repo.fetch_macro_release_statuses(sources=[_FOMC], statuses=["failed"])
    assert [row["release_key"] for row in failed] == [
        "fomc-statement:monetary20260617a"
    ]


def test_release_status_errors_are_bounded(repo: Repository) -> None:
    _release_status(
        repo,
        status="failed",
        error_type="E" * 500,
        error_message="m" * 5000,
    )
    row = repo.fetch_macro_release_status(source=_FOMC, release_key=_STATEMENT_KEY)
    assert row is not None
    assert len(row["error_type"]) == 200
    assert len(row["error_message"]) == 1000


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"release_type": "sep"}, "no event_class"),
        ({"event_class": None}, "known event_class"),
        ({"status": "ok"}, "success_artifact_id"),
        ({"status": "failed"}, "requires error_type"),
        ({"status": "artifact_only"}, "latest_artifact_id"),
        ({"status": "reticulating"}, "unknown macro release status"),
        (
            {"last_attempt_at": datetime(2026, 4, 29, 18, 5)},
            "timezone-aware",
        ),
    ],
)
def test_release_status_rejects_invalid_combinations(
    repo: Repository, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _release_status(repo, **overrides)


def test_release_status_cannot_point_at_another_sources_artifact(
    repo: Repository,
) -> None:
    """The composite FK stops a surrogate id crossing a source boundary."""
    foreign_id = _insert_artifact(repo)  # source='BLS'

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with repo.conn.transaction():
            _release_status(
                repo,
                status="artifact_only",
                artifact_source_record_id="cpi-2026-02-12",
                latest_artifact_id=foreign_id,
            )


def _policy_row(
    artifact_id: int,
    *,
    record_id: str = f"{_STATEMENT_KEY}:html",
    rate: str = "3.625",
    **overrides: object,
) -> dict:
    row: dict[str, object] = {
        "artifact_id": artifact_id,
        "domain": "policy_rates",
        "series_id": "POLICY_PATH_ACTUAL",
        "period_end": date(2026, 4, 29),
        "frequency": "event",
        "unit": "policy_path_json",
        "value_numeric": None,
        "value_text": None,
        "value_json": {"kind": "actual", "points": [{"rate_percent": rate}]},
        "source": _FOMC,
        # The FK ties source_record_id to ONE artifact, so it differs between the
        # HTML and PDF of a single release; release_key is what they share.
        "source_record_id": record_id,
        "release_key": _STATEMENT_KEY,
        "published_at": datetime(2026, 4, 29, 18, 0, tzinfo=UTC),
        "available_at": datetime(2026, 4, 29, 18, 0, tzinfo=UTC),
        "parser_version": "fomc_statement.v2",
        "quality_status": "partial",
        "cost_class": "free_official",
    }
    row.update(overrides)
    return row


def test_same_fact_from_different_bytes_is_one_observation_with_two_witnesses(
    repo: Repository,
) -> None:
    """The publisher serves one release as several exact artifacts.

    HTML and PDF of the same statement, or a cosmetic markup reissue, are
    different bytes carrying an identical committee decision. Under the general
    MC0 identity -- which includes artifact_id -- each would become a separate
    observation and the policy path would show phantom vintages.
    """
    html_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    pdf_id = _statement_artifact(repo, record_id=f"{_STATEMENT_KEY}:pdf", marker="pdf")
    assert html_id != pdf_id

    seen = datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
    obs_id, created = repo.upsert_macro_policy_observation(
        _policy_row(html_id), seen_at=seen
    )
    assert created is True

    later = datetime(2026, 4, 30, 18, 5, tzinfo=UTC)
    # The PDF carries the same decision but the parser reads the HTML, so it is
    # a corroborating witness rather than a second source of the facts.
    same_id, created_again = repo.upsert_macro_policy_observation(
        _policy_row(pdf_id, record_id=f"{_STATEMENT_KEY}:pdf"),
        seen_at=later,
        relation="corroborates",
    )

    assert same_id == obs_id
    assert created_again is False
    assert repo.fetch_macro_observation_artifacts(obs_id) == [
        {"artifact_id": html_id, "relation": "parsed_from"},
        {"artifact_id": pdf_id, "relation": "corroborates"},
    ]
    rows = repo.fetch_macro_observation_history("POLICY_PATH_ACTUAL", date(2026, 4, 29))
    assert len(rows) == 1
    assert rows[0]["last_seen_at"] == later


def test_a_changed_fact_creates_a_second_policy_observation(repo: Repository) -> None:
    html_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    corrected_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:corrected", marker="corrected"
    )
    seen = datetime(2026, 4, 29, 18, 5, tzinfo=UTC)

    first, _ = repo.upsert_macro_policy_observation(_policy_row(html_id), seen_at=seen)
    second, created = repo.upsert_macro_policy_observation(
        _policy_row(
            corrected_id, record_id=f"{_STATEMENT_KEY}:corrected", rate="3.875"
        ),
        seen_at=seen,
    )

    assert created is True
    assert second != first
    assert (
        len(
            repo.fetch_macro_observation_history(
                "POLICY_PATH_ACTUAL", date(2026, 4, 29)
            )
        )
        == 2
    )


def test_a_corrected_semantic_parser_creates_a_second_policy_observation(
    repo: Repository,
) -> None:
    """Reparsing identical bytes with fixed code is a new fact, not the old one."""
    html_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    seen = datetime(2026, 4, 29, 18, 5, tzinfo=UTC)

    first, _ = repo.upsert_macro_policy_observation(_policy_row(html_id), seen_at=seen)
    second, created = repo.upsert_macro_policy_observation(
        _policy_row(html_id, parser_version="fomc_statement.v3"), seen_at=seen
    )

    assert created is True
    assert second != first


def test_non_policy_series_keep_their_mc0_identity(repo: Repository) -> None:
    """Migration 120 must not change how every other macro series is identified."""
    artifact_id = _insert_artifact(repo)
    repo.insert_macro_observations(
        [_observation(artifact_id)],
        seen_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
    )

    rows = repo.fetch_macro_observation_history("CPI_ALL_ITEMS", date(2026, 1, 31))
    assert len(rows) == 1
    assert rows[0]["semantic_hash"] is None
    assert rows[0]["content_hash"] == macro_observation_content_hash(
        _observation(artifact_id)
    )


def test_database_recomputes_the_policy_semantic_hash(repo: Repository) -> None:
    """Direct SQL must not be able to assert a false semantic identity."""
    artifact_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    obs_id, _ = repo.upsert_macro_policy_observation(
        _policy_row(artifact_id), seen_at=datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
    )

    with pytest.raises(psycopg.errors.CheckViolation, match="semantic_hash"):
        with repo.conn.transaction():
            repo.conn.execute(
                "UPDATE uw_scan.macro_observations SET semantic_hash = %s "
                "WHERE obs_id = %s",
                ("0" * 64, obs_id),
            )


def test_policy_lineage_is_immutable(repo: Repository) -> None:
    artifact_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    obs_id, _ = repo.upsert_macro_policy_observation(
        _policy_row(artifact_id), seen_at=datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
    )

    with pytest.raises(psycopg.errors.CheckViolation, match="lineage is immutable"):
        with repo.conn.transaction():
            repo.conn.execute(
                "DELETE FROM uw_scan.macro_observation_artifacts WHERE obs_id = %s",
                (obs_id,),
            )


def test_policy_semantic_hash_matches_between_python_and_postgres(
    repo: Repository,
) -> None:
    """Two implementations of one identity must agree byte-for-byte.

    The Python side decides idempotency before the write; the SQL side is the
    authority that direct SQL cannot bypass. If they canonicalize differently --
    key order, non-ASCII escaping, numeric trimming -- the same fact hashes two
    ways and the partial unique index stops preventing anything.
    """
    artifact_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    row = _policy_row(
        artifact_id,
        value_json={
            "黄金": "x",
            "a": 1,
            "B": 2,
            "nested": {"Z": 6, "é": 3},
            "decimals": ["3.500", "-0.0", "0.25"],
            "flags": [True, False, None],
        },
    )
    obs_id, created = repo.upsert_macro_policy_observation(
        row, seen_at=datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
    )
    assert created is True

    stored = repo.conn.execute(
        "SELECT semantic_hash, uw_scan.macro_policy_semantic_hash("
        "  domain, frequency, parser_version, period_end, published_at,"
        "  release_key, series_id, source, unit,"
        "  value_numeric, value_text, value_jsonb"
        ") FROM uw_scan.macro_observations WHERE obs_id = %s",
        (obs_id,),
    ).fetchone()
    assert stored is not None
    python_hash, postgres_hash = stored
    assert python_hash == postgres_hash == macro_policy_semantic_hash(row)


def test_policy_semantic_hash_rejects_nonfinite_numeric(repo: Repository) -> None:
    artifact_id = _statement_artifact(
        repo, record_id=f"{_STATEMENT_KEY}:html", marker="html"
    )
    row = _policy_row(artifact_id, value_json=None, value_numeric=Decimal("NaN"))

    with pytest.raises(ValueError, match="finite"):
        repo.upsert_macro_policy_observation(
            row, seen_at=datetime(2026, 4, 29, 18, 5, tzinfo=UTC)
        )


def test_policy_semantic_hash_ignores_the_artifact_and_availability(
    repo: Repository,
) -> None:
    """The two fields that make MC0 byte-dependent must not enter this identity."""
    base = _policy_row(1)
    moved = {
        **base,
        "artifact_id": 99,
        "available_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    }

    assert macro_policy_semantic_hash(base) == macro_policy_semantic_hash(moved)
    # ...while the general MC0 identity does change, which is why policy needs
    # its own.
    assert macro_observation_content_hash(base) != macro_observation_content_hash(moved)


def test_a_correction_takes_its_own_retrieval_instant_not_the_first_release(
    repo: Repository,
) -> None:
    """The artifact-layer half of the backdating fix, tested where it lives.

    A reissue retrieved weeks later did not exist at the original release
    instant, and dating it there is a look-ahead leak in the dangerous
    direction: a replay reads a number nobody could have had. This pins
    ``_revision_available_at`` directly rather than only through the live smoke,
    because the defect is silent -- the row simply claims an earlier instant.
    """
    released = datetime(2026, 2, 12, 13, 30, tzinfo=UTC)
    corrected_at = datetime(2026, 4, 3, 9, 15, tzinfo=UTC)

    first_id = _insert_artifact(repo, available_at=released, retrieved_at=released)
    # Same record, genuinely different bytes, retrieved seven weeks later. The
    # caller still offers the publisher's original instant, exactly as the
    # source modules do.
    corrected_id = _insert_artifact(
        repo,
        available_at=released,
        retrieved_at=corrected_at,
        raw_json={"series": "CPIAUCSL", "value": "319.4", "revision": "second"},
    )
    assert corrected_id != first_id

    assert repo.fetch_macro_artifact(first_id)["available_at"] == released
    assert repo.fetch_macro_artifact(corrected_id)["available_at"] == corrected_at


def test_reinserting_identical_bytes_does_not_move_their_availability(
    repo: Repository,
) -> None:
    """A rerun must not push a known fact's availability forward.

    The revision clamp keys on the bytes, so re-seeing the SAME payload later
    has to return the instant already stored -- otherwise every nightly rerun
    would walk availability toward today and quietly destroy the replay.
    """
    released = datetime(2026, 2, 12, 13, 30, tzinfo=UTC)

    first_id = _insert_artifact(repo, available_at=released, retrieved_at=released)
    again_id = _insert_artifact(
        repo,
        available_at=released,
        retrieved_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
    )

    assert again_id == first_id
    assert repo.fetch_macro_artifact(first_id)["available_at"] == released


def _vintage_row(
    artifact_id: int, *, period_end: date, available_at: datetime, value: str
) -> dict[str, object]:
    """One ALFRED vintage: a value, and the day the publisher first printed it."""
    row: dict[str, object] = {
        "artifact_id": artifact_id,
        "domain": "inflation",
        "series_id": "CPIAUCSL",
        "period_end": period_end,
        "frequency": "monthly",
        "unit": "index_1982_84_100_sa",
        "value_numeric": Decimal(value),
        "value_text": None,
        "value_json": None,
        "source": "fred",
        "source_record_id": "fred-series:CPIAUCSL",
        "published_at": available_at,
        "available_at": available_at,
        "parser_version": "fred-series-v1",
        "quality_status": "valid",
        "cost_class": "free_publisher",
    }
    row["content_hash"] = macro_observation_content_hash(row)
    return row


def test_a_vintage_bearing_artifact_does_not_gate_replay_on_its_fetch_time(
    repo: Repository,
) -> None:
    """The bug this pins made every historical replay return nothing at all.

    An ALFRED payload fetched today REPORTS that January 2024 CPI was first published on
    2024-02-13; it is not that publication, which is why its own ``available_at`` is the
    fetch time and why migration 124 inverted the WRITE bound for it. The READ path kept
    the release rule, so ``a.available_at <= as_of`` let a 2026 fetch veto every earlier
    replay -- and the result looked like missing data rather than a broken query.

    Values are the real CPIAUCSL readings for January 2024: 309.685 as first published,
    309.698 as it stands after later seasonal-factor revisions.
    """
    fetched_at = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
    artifact_id = _insert_artifact(
        repo,
        source="fred",
        source_kind="first_party_publisher",
        source_record_id="fred-series:CPIAUCSL",
        cost_class="free_publisher",
        available_at=fetched_at,
        retrieved_at=fetched_at,
        raw_json={"series": "CPIAUCSL", "observations": []},
        vintage_bearing=True,
    )
    repo.upsert_macro_series_observations(
        [
            _vintage_row(
                artifact_id,
                period_end=date(2024, 1, 1),
                available_at=datetime(2024, 2, 13, 13, 30, tzinfo=UTC),
                value="309.685",
            )
        ],
        seen_at=fetched_at,
    )

    replayed = repo.fetch_macro_series_as_of(
        "CPIAUCSL",
        datetime(2024, 6, 1, tzinfo=UTC),
        preferred_sources=("fred",),
    )
    assert [row["value_numeric"] for row in replayed] == [Decimal("309.685")]

    # The point-in-time gate itself does not weaken: the vintage is still the bound.
    before_publication = repo.fetch_macro_series_as_of(
        "CPIAUCSL",
        datetime(2024, 2, 1, tzinfo=UTC),
        preferred_sources=("fred",),
    )
    assert before_publication == []


def test_a_release_artifact_still_gates_its_own_observations(
    repo: Repository,
) -> None:
    """The control. Relaxing the bound for vintage records must not relax it for releases.

    A statement becomes knowable when it goes up, so nothing parsed out of it may be
    read at an instant before the artifact itself existed.
    """
    published_at = datetime(2026, 2, 12, 13, 30, tzinfo=UTC)
    artifact_id = _insert_artifact(repo, available_at=published_at)
    repo.insert_macro_observations(
        [_observation(artifact_id, available_at=published_at)], seen_at=published_at
    )

    assert (
        repo.fetch_macro_series_as_of(
            "CPI_ALL_ITEMS",
            datetime(2026, 2, 11, tzinfo=UTC),
            preferred_sources=("BLS",),
        )
        == []
    )
    assert (
        len(
            repo.fetch_macro_series_as_of(
                "CPI_ALL_ITEMS",
                datetime(2026, 3, 1, tzinfo=UTC),
                preferred_sources=("BLS",),
            )
        )
        == 1
    )
