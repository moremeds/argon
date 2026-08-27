"""Availability-evidence claims for statement content versions (migration 132).

The schema half of these tests is where the vocabulary stops being a convention
and becomes a rule the database will not let anyone break. Two constraints carry
the whole contract:

- a `true_pit` or `capture_bounded` claim MUST carry `available_at`, because a
  timed class with a NULL instant admits at every cutoff — the exact look-ahead
  this table exists to prevent, wearing an honest label;
- a `current_vintage` or `unknown` claim MUST NOT carry one, because a timestamp
  on a class that makes no availability claim is indistinguishable, to any later
  query, from one that does.

`UNIQUE (obs_id, claim_key)` is the append-only hinge: a rule replay collides and
writes nothing, while genuinely stronger evidence arrives under a DIFFERENT
`claim_key` and lands beside its predecessor. Nothing is ever updated in place,
so the record of what Argon believed, and when, survives.

Figures are NVDA's real 2026-04-30 quarterly balance sheet, frozen — the same
fixture `test_fundamental_obs.py` uses.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, date, datetime

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.fundamentals.observation_time import (
    CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
    SOURCE_ARGON_CAPTURE,
    SOURCE_ARGON_LEGACY,
    EvidenceClass,
)
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.migrate_runner import apply_migrations


@contextmanager
def _counting(conn):
    """Record every statement this connection issues, via psycopg's own hook.

    `cursor_factory` is the supported extension point, so the cursor under test
    is a REAL cursor against a REAL database — the suite bans faking either. All
    this subclass adds is a tally, which is the only way to prove a batch path
    is set-based rather than one query per observation.
    """
    calls: list[str] = []

    class Counting(psycopg.Cursor):
        def execute(self, query, params=None, **kw):
            calls.append(str(query).strip().split()[0].upper())
            return super().execute(query, params, **kw)

        def executemany(self, query, params_seq, **kw):
            calls.append("EXECUTEMANY")
            return super().executemany(query, params_seq, **kw)

    previous = conn.cursor_factory
    conn.cursor_factory = Counting
    try:
        yield calls
    finally:
        conn.cursor_factory = previous

NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "common_stock_shares_outstanding": "24391000000",
    "inserted_at": "2026-05-21T06:58:08Z",
    "updated_at": "2026-08-11T03:58:32Z",
}

PERIOD = date(2026, 4, 30)
TABLE = "fundamental_obs_availability"


def _row(raw: dict) -> dict:
    payload = normalize(raw)
    return {
        "source": "uw",
        "ticker": "NVDA",
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": date(2026, 5, 21),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _seed_one_observation(seeded) -> int:
    """Persist one observation and return its obs_id."""
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(
        [_row(NVDA_BALANCE)]
    )
    with seeded.conn.cursor() as cur:
        cur.execute(f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs")
        return cur.fetchone()[0]


def _insert_claim(
    seeded,
    obs_id: int,
    *,
    claim_key: str,
    evidence_class: str,
    available_at: datetime | None,
    evidence_source: str = "argon_capture",
) -> None:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {seeded._schema}.{TABLE}
                        (obs_id, claim_key, evidence_class, available_at,
                         evidence_source)
                 VALUES (%s, %s, %s, %s, %s)
            """,
            (obs_id, claim_key, evidence_class, available_at, evidence_source),
        )


# --- shape -----------------------------------------------------------------


def test_availability_table_has_the_agreed_columns(seeded_db_empty_cards):
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (seeded_db_empty_cards._schema, TABLE),
        )
        cols = {r[0] for r in cur.fetchall()}
    assert {
        "availability_id",
        "obs_id",
        "claim_key",
        "evidence_class",
        "available_at",
        "evidence_source",
        "evidence_ref",
        "evidence_jsonb",
        "recorded_at",
    } <= cols


def test_the_as_of_join_path_is_indexed(seeded_db_empty_cards):
    """Without this index the as-of reader sequential-scans every claim per read."""
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s",
            (seeded_db_empty_cards._schema, TABLE),
        )
        defs = " ".join(r[0] for r in cur.fetchall())
    assert "evidence_class" in defs and "available_at" in defs


# --- the two timestamp constraints ----------------------------------------


@pytest.mark.parametrize("cls", ["true_pit", "capture_bounded"])
def test_a_timed_class_without_an_instant_is_refused(seeded_db_empty_cards, cls):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_claim(
            seeded_db_empty_cards,
            obs_id,
            claim_key=f"{cls}:test",
            evidence_class=cls,
            available_at=None,
        )
    seeded_db_empty_cards.conn.rollback()


@pytest.mark.parametrize("cls", ["current_vintage", "unknown"])
def test_an_untimed_class_carrying_an_instant_is_refused(seeded_db_empty_cards, cls):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_claim(
            seeded_db_empty_cards,
            obs_id,
            claim_key=f"{cls}:test",
            evidence_class=cls,
            available_at=datetime(2021, 1, 1, tzinfo=UTC),
        )
    seeded_db_empty_cards.conn.rollback()


def test_an_invented_evidence_class_is_refused(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_claim(
            seeded_db_empty_cards,
            obs_id,
            claim_key="made_up:test",
            evidence_class="probably_fine",
            available_at=None,
        )
    seeded_db_empty_cards.conn.rollback()


def test_all_four_agreed_classes_are_accepted(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    at = datetime(2021, 1, 1, tzinfo=UTC)
    for cls, when in (
        ("true_pit", at),
        ("capture_bounded", at),
        ("current_vintage", None),
        ("unknown", None),
    ):
        _insert_claim(
            seeded_db_empty_cards,
            obs_id,
            claim_key=f"{cls}:ok",
            evidence_class=cls,
            available_at=when,
        )
    seeded_db_empty_cards.conn.commit()
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {seeded_db_empty_cards._schema}.{TABLE}")
        assert cur.fetchone()[0] == 4


# --- append-only identity --------------------------------------------------


def test_a_claim_must_reference_a_real_observation(seeded_db_empty_cards):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_claim(
            seeded_db_empty_cards,
            999_999_999,
            claim_key="capture:test",
            evidence_class="current_vintage",
            available_at=None,
        )
    seeded_db_empty_cards.conn.rollback()


def test_replaying_one_rule_over_one_observation_collides(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    _insert_claim(
        seeded_db_empty_cards,
        obs_id,
        claim_key="capture:first_observed_at:v1",
        evidence_class="capture_bounded",
        available_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    seeded_db_empty_cards.conn.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_claim(
            seeded_db_empty_cards,
            obs_id,
            claim_key="capture:first_observed_at:v1",
            evidence_class="capture_bounded",
            available_at=datetime(2025, 9, 9, tzinfo=UTC),
        )
    seeded_db_empty_cards.conn.rollback()


def test_stronger_later_evidence_lands_beside_the_capture_claim(seeded_db_empty_cards):
    """The whole reason claims are a table and not two columns on the observation."""
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    _insert_claim(
        seeded_db_empty_cards,
        obs_id,
        claim_key="capture:first_observed_at:v1",
        evidence_class="capture_bounded",
        available_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    _insert_claim(
        seeded_db_empty_cards,
        obs_id,
        claim_key="sec:amendment:0001045810-24-000029",
        evidence_class="true_pit",
        available_at=datetime(2024, 2, 21, tzinfo=UTC),
        evidence_source="sec_edgar",
    )
    seeded_db_empty_cards.conn.commit()
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT evidence_class FROM {seeded_db_empty_cards._schema}.{TABLE} "
            "WHERE obs_id = %s ORDER BY evidence_class",
            (obs_id,),
        )
        assert [r[0] for r in cur.fetchall()] == ["capture_bounded", "true_pit"]


# --- idempotency -----------------------------------------------------------


def test_re_running_every_migration_is_a_no_op(seeded_db_empty_cards):
    settings = Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        apply_migrations(conn, log=lambda _msg: None)

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'uw_scan' AND table_name = %s",
            (TABLE,),
        )
        assert cur.fetchone()[0] == 1


# ===========================================================================
# Repository behaviour (task 3)
# ===========================================================================


def _avail(seeded):
    return FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)


def _seed_versions(seeded, count: int) -> list[int]:
    """Persist `count` distinct content versions of the same identity."""
    repo = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    for i in range(count):
        raw = {**NVDA_BALANCE, "total_assets": str(259474000000 + i)}
        repo.record_statements([_row(raw)])
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs "
            "ORDER BY obs_id"
        )
        return [r[0] for r in cur.fetchall()]


def test_a_capture_claim_round_trips(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    at = datetime(2024, 3, 1, tzinfo=UTC)
    repo = _avail(seeded_db_empty_cards)
    assert (
        repo.record_claims(
            [
                {
                    "obs_id": obs_id,
                    "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                    "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                    "available_at": at,
                    "evidence_source": SOURCE_ARGON_CAPTURE,
                }
            ]
        )
        == 1
    )
    (claim,) = repo.claims_for_obs_ids([obs_id])[obs_id]
    assert claim["evidence_class"] == EvidenceClass.CAPTURE_BOUNDED
    assert claim["available_at"] == at


def test_replaying_the_same_deterministic_claim_writes_nothing(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    claim = {
        "obs_id": obs_id,
        "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
        "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
        "available_at": datetime(2024, 3, 1, tzinfo=UTC),
        "evidence_source": SOURCE_ARGON_CAPTURE,
    }
    assert repo.record_claims([claim]) == 1
    assert repo.record_claims([claim]) == 0
    assert len(repo.claims_for_obs_ids([obs_id])[obs_id]) == 1


def test_a_replay_cannot_silently_revise_an_existing_claim(seeded_db_empty_cards):
    """Append-only in practice: the second, different value must NOT win."""
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    original = datetime(2024, 3, 1, tzinfo=UTC)
    repo.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                "available_at": original,
                "evidence_source": SOURCE_ARGON_CAPTURE,
            }
        ]
    )
    repo.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": datetime(1999, 1, 1, tzinfo=UTC),
                "evidence_source": "someone_confused",
            }
        ]
    )
    (claim,) = repo.claims_for_obs_ids([obs_id])[obs_id]
    assert claim["evidence_class"] == EvidenceClass.CAPTURE_BOUNDED
    assert claim["available_at"] == original


def test_stronger_evidence_under_a_new_key_coexists(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    repo.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                "available_at": datetime(2024, 3, 1, tzinfo=UTC),
                "evidence_source": SOURCE_ARGON_CAPTURE,
            },
            {
                "obs_id": obs_id,
                "claim_key": "sec:amendment:0001045810-24-000029",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": datetime(2024, 2, 21, tzinfo=UTC),
                "evidence_source": "sec_edgar",
                "evidence_ref": "0001045810-24-000029",
            },
        ]
    )
    classes = {c["evidence_class"] for c in repo.claims_for_obs_ids([obs_id])[obs_id]}
    assert classes == {EvidenceClass.CAPTURE_BOUNDED, EvidenceClass.TRUE_PIT}


def test_an_invalid_claim_is_refused_before_it_reaches_sql(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    with pytest.raises(ValueError, match="must not carry available_at"):
        repo.record_claims(
            [
                {
                    "obs_id": obs_id,
                    "claim_key": "bad:test",
                    "evidence_class": EvidenceClass.CURRENT_VINTAGE,
                    "available_at": datetime(2024, 3, 1, tzinfo=UTC),
                    "evidence_source": SOURCE_ARGON_LEGACY,
                }
            ]
        )
    assert repo.claim_counts() == {}


def test_a_refused_batch_writes_none_of_its_valid_rows(seeded_db_empty_cards):
    """No partially-advertised success: one bad row voids the whole batch."""
    ids = _seed_versions(seeded_db_empty_cards, 2)
    repo = _avail(seeded_db_empty_cards)
    with pytest.raises(ValueError):
        repo.record_claims(
            [
                {
                    "obs_id": ids[0],
                    "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                    "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                    "available_at": datetime(2024, 3, 1, tzinfo=UTC),
                    "evidence_source": SOURCE_ARGON_CAPTURE,
                },
                {
                    "obs_id": ids[1],
                    "claim_key": CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
                    "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                    "available_at": None,
                    "evidence_source": SOURCE_ARGON_CAPTURE,
                },
            ]
        )
    assert repo.claim_counts() == {}


def test_empty_batch_is_a_noop(seeded_db_empty_cards):
    assert _avail(seeded_db_empty_cards).record_claims([]) == 0


# --- set-based seeding -----------------------------------------------------


def test_seeding_capture_claims_is_one_statement_not_one_per_row(
    seeded_db_empty_cards,
):
    ids = _seed_versions(seeded_db_empty_cards, 5)
    repo = _avail(seeded_db_empty_cards)
    with _counting(seeded_db_empty_cards.conn) as calls:
        inserted, last = repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)
    assert inserted == 5
    assert last == ids[-1]
    assert len(calls) == 1, f"expected one round-trip, got {len(calls)}: {calls}"


def test_a_capture_claim_lands_exactly_on_first_observed_at(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT first_observed_at FROM "
            f"{seeded_db_empty_cards._schema}.fundamental_statement_obs "
            "WHERE obs_id = %s",
            (obs_id,),
        )
        captured = cur.fetchone()[0]
    (claim,) = repo.claims_for_obs_ids([obs_id])[obs_id]
    assert claim["available_at"] == captured


def test_seeding_current_vintage_leaves_the_instant_null(seeded_db_empty_cards):
    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    repo.seed_claims(EvidenceClass.CURRENT_VINTAGE)
    (claim,) = repo.claims_for_obs_ids([obs_id])[obs_id]
    assert claim["evidence_class"] == EvidenceClass.CURRENT_VINTAGE
    assert claim["available_at"] is None


def test_seeding_refuses_a_class_it_cannot_derive(seeded_db_empty_cards):
    """true_pit needs an artifact; there is no rule that manufactures one here."""
    _seed_one_observation(seeded_db_empty_cards)
    with pytest.raises(ValueError, match="cannot be derived"):
        _avail(seeded_db_empty_cards).seed_claims(EvidenceClass.TRUE_PIT)


def test_seeding_resumes_from_a_keyset_cursor(seeded_db_empty_cards):
    ids = _seed_versions(seeded_db_empty_cards, 5)
    repo = _avail(seeded_db_empty_cards)
    first, cursor = repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED, limit=2)
    assert (first, cursor) == (2, ids[1])
    second, cursor = repo.seed_claims(
        EvidenceClass.CAPTURE_BOUNDED, after_obs_id=cursor, limit=2
    )
    assert (second, cursor) == (2, ids[3])
    third, cursor = repo.seed_claims(
        EvidenceClass.CAPTURE_BOUNDED, after_obs_id=cursor, limit=2
    )
    assert (third, cursor) == (1, ids[4])
    assert repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED, after_obs_id=cursor) == (
        0,
        None,
    )


def test_a_rerun_over_the_whole_table_writes_zero(seeded_db_empty_cards):
    _seed_versions(seeded_db_empty_cards, 4)
    repo = _avail(seeded_db_empty_cards)
    assert repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)[0] == 4
    assert repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)[0] == 0
    assert repo.claim_counts() == {EvidenceClass.CAPTURE_BOUNDED: 4}


def test_seeding_can_be_scoped_to_tickers_without_changing_semantics(
    seeded_db_empty_cards,
):
    _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    assert repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED, tickers=["AAPL"])[0] == 0
    assert repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED, tickers=["NVDA"])[0] == 1


def test_claim_counts_report_every_populated_class(seeded_db_empty_cards):
    _seed_versions(seeded_db_empty_cards, 3)
    repo = _avail(seeded_db_empty_cards)
    repo.seed_claims(EvidenceClass.CURRENT_VINTAGE)
    repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)
    assert repo.claim_counts() == {
        EvidenceClass.CURRENT_VINTAGE: 3,
        EvidenceClass.CAPTURE_BOUNDED: 3,
    }


def test_observations_without_any_claim_are_countable(seeded_db_empty_cards):
    _seed_versions(seeded_db_empty_cards, 3)
    repo = _avail(seeded_db_empty_cards)
    assert repo.unclaimed_observation_count() == 3
    repo.seed_claims(EvidenceClass.CURRENT_VINTAGE)
    assert repo.unclaimed_observation_count() == 0


# ===========================================================================
# Coverage audit (task 9)
# ===========================================================================


def test_the_audit_reconciles_and_passes_its_own_checks(seeded_db_empty_cards):
    from uw_scan.fundamentals.observation_time import audit_violations

    _seed_versions(seeded_db_empty_cards, 4)
    repo = _avail(seeded_db_empty_cards)
    repo.seed_claims(EvidenceClass.CURRENT_VINTAGE)
    repo.seed_claims(EvidenceClass.CAPTURE_BOUNDED)

    report = repo.coverage_audit()
    assert report["observations"] == 4
    assert report["claims"] == 8
    assert report["unclaimed_observations"] == 0
    assert report["by_evidence_class"] == {"current_vintage": 4, "capture_bounded": 4}
    # Four versions of ONE identity: exactly the population selection order matters for.
    assert report["multi_version_identities"] == 1
    assert report["multi_version_rows"] == 4
    assert audit_violations(report) == []


def test_the_audit_fails_when_an_observation_was_never_classified(
    seeded_db_empty_cards,
):
    from uw_scan.fundamentals.observation_time import audit_violations

    _seed_versions(seeded_db_empty_cards, 3)
    repo = _avail(seeded_db_empty_cards)
    repo.seed_claims(EvidenceClass.CURRENT_VINTAGE, limit=1)
    report = repo.coverage_audit()
    assert report["unclaimed_observations"] == 2
    assert any("no claim at all" in p for p in audit_violations(report))


def test_the_audit_flags_a_true_pit_claim_with_no_artifact(seeded_db_empty_cards):
    from uw_scan.fundamentals.observation_time import audit_violations

    obs_id = _seed_one_observation(seeded_db_empty_cards)
    repo = _avail(seeded_db_empty_cards)
    repo.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": datetime(2020, 5, 21, tzinfo=UTC),
                "evidence_source": "sec_edgar",
                # no evidence_ref: nothing to point at
            }
        ]
    )
    report = repo.coverage_audit()
    assert report["true_pit_without_evidence"] == 1
    assert any("artifact reference" in p for p in audit_violations(report))
