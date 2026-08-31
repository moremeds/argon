"""Current versus as-of statement panels — the selection order under test.

THE BUG THIS FILE EXISTS TO PIN DOWN
------------------------------------
`statement_panel()` picks a version with `DISTINCT ON (…) ORDER BY obs_id DESC`.
`obs_id` is a BIGSERIAL: it records the order Argon INSERTED rows, which for a
backfill is the order the backfill walked the universe. A restatement first
captured in 2023 therefore carries a HIGHER obs_id than the original 2020 filing
and wins every replay, including one dated 2021. Scoring built its historical
knowledge buckets on that panel, so figures the market had not seen could enter a
cross-section stamped years earlier.

The fixture below is one identity carrying four content versions with four
different availability stories. Every assertion is about WHICH version comes back
and WHY — the panel's reshaping is unchanged and already covered elsewhere.

Figures are NVDA's real 2026-04-30 quarterly balance sheet, frozen, with the
total-assets figure varied per version so the versions are distinguishable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from uw_scan.storage.fundamental_observation_panels import (
    current_statement_panel,
    statement_panel_as_of,
)

from uw_scan.fundamentals.observation_time import (
    SOURCE_ARGON_CAPTURE,
    EvidenceClass,
    EvidencePolicy,
)
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)

PERIOD = date(2020, 3, 31)
BASE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2020-03-31",
    "report_type": "quarterly",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "inserted_at": "2020-05-21T06:58:08Z",
    "updated_at": "2020-05-21T06:58:08Z",
}

ORIGINAL_2020 = datetime(2020, 5, 21, tzinfo=UTC)
RESTATED_2023 = datetime(2023, 8, 14, tzinfo=UTC)
CAPTURED_2024 = datetime(2024, 6, 1, tzinfo=UTC)


def _row(assets: int, *, statement: str = "balance", ticker: str = "NVDA") -> dict:
    payload = normalize({**BASE, "ticker": ticker, "total_assets": str(assets)})
    return {
        "source": "uw",
        "ticker": ticker,
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": statement,
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        # Populated on purpose: the ORIGINAL filing date must not, by itself,
        # promote any version to true_pit.
        "filing_published_at": date(2020, 5, 21),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _assets(panel: dict, ticker: str = "NVDA") -> str:
    return panel[ticker]["balance-sheets"][PERIOD.isoformat()]["total_assets"]


@pytest.fixture
def four_versions(seeded_db_empty_cards):
    """One identity, four versions, four availability stories.

    v1 original     true_pit @ 2020-05-21
    v2 restatement  true_pit @ 2023-08-14
    v3 later change capture_bounded @ 2024-06-01   (no publication evidence)
    v4 newest       current_vintage only           (a legacy snapshot)

    Insertion order is deliberately the same as version order, so `obs_id DESC`
    ALWAYS returns v4 — that is what makes the as-of assertions decisive.
    """
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    avail = FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)

    for assets in (1_000, 2_000, 3_000, 4_000):
        obs.record_statements([_row(assets)])

    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id, raw_jsonb->>'total_assets' "
            f"  FROM {seeded._schema}.fundamental_statement_obs ORDER BY obs_id"
        )
        ids = {assets: obs_id for obs_id, assets in cur.fetchall()}

    avail.record_claims(
        [
            {
                "obs_id": ids["1000"],
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
                "evidence_ref": "0001045810-20-000010",
            },
            {
                "obs_id": ids["2000"],
                "claim_key": "sec:amendment:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": RESTATED_2023,
                "evidence_source": "sec_edgar",
                "evidence_ref": "0001045810-23-000099",
            },
            {
                "obs_id": ids["3000"],
                "claim_key": "capture:first_observed_at:v1",
                "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                "available_at": CAPTURED_2024,
                "evidence_source": SOURCE_ARGON_CAPTURE,
            },
            {
                "obs_id": ids["4000"],
                "claim_key": "legacy_current_vintage:v1",
                "evidence_class": EvidenceClass.CURRENT_VINTAGE,
                "available_at": None,
                "evidence_source": "argon_legacy_classification",
            },
        ]
    )
    return seeded, ids


# --- the current reader is unchanged --------------------------------------


def test_current_reader_returns_the_newest_accepted_version(four_versions):
    seeded, _ = four_versions
    panel = current_statement_panel(seeded.conn, schema=seeded._schema)
    assert _assets(panel) == "4000"


def test_the_compatibility_alias_agrees_with_the_explicit_current_reader(
    four_versions,
):
    """`statement_panel()` keeps its meaning; only its name became ambiguous."""
    seeded, _ = four_versions
    repo = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    assert repo.statement_panel() == current_statement_panel(
        seeded.conn, schema=seeded._schema
    )


# --- true-PIT selection ----------------------------------------------------


def test_as_of_2021_returns_the_original_not_the_restatement(four_versions):
    """The headline regression: `obs_id DESC` returned 4000 here."""
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2021, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert _assets(panel) == "1000"


def test_as_of_2024_returns_the_restatement_not_the_capture_or_legacy_rows(
    four_versions,
):
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2024, 12, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert _assets(panel) == "2000"


def test_a_cutoff_before_every_claim_returns_nothing(four_versions):
    """Fails closed. An empty cross-section is an honest answer; a filled-in one
    built from current-vintage rows is the bug wearing a policy name."""
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2019, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert panel == {}


# --- capture-bounded selection --------------------------------------------


def test_capture_bounded_excludes_a_version_before_its_capture(four_versions):
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2024, 5, 31, tzinfo=UTC),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
        schema=seeded._schema,
    )
    assert _assets(panel) == "2000"


def test_capture_bounded_admits_the_version_after_its_capture(four_versions):
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2024, 6, 2, tzinfo=UTC),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
        schema=seeded._schema,
    )
    assert _assets(panel) == "3000"


def test_capture_bounded_admits_exactly_at_the_capture_instant(four_versions):
    seeded, _ = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=CAPTURED_2024,
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
        schema=seeded._schema,
    )
    assert _assets(panel) == "3000"


def test_no_policy_ever_reaches_the_current_vintage_row(four_versions):
    seeded, _ = four_versions
    for policy in EvidencePolicy:
        panel = statement_panel_as_of(
            seeded.conn,
            as_of=datetime(2030, 1, 1, tzinfo=UTC),
            evidence_policy=policy,
            schema=seeded._schema,
        )
        assert _assets(panel) != "4000", f"{policy} admitted a current-vintage row"


def test_an_observation_with_no_claim_never_enters_a_historical_panel(
    seeded_db_empty_cards,
):
    seeded = seeded_db_empty_cards
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(
        [_row(9_000)]
    )
    for policy in EvidencePolicy:
        assert (
            statement_panel_as_of(
                seeded.conn,
                as_of=datetime(2030, 1, 1, tzinfo=UTC),
                evidence_policy=policy,
                schema=seeded._schema,
            )
            == {}
        )


# --- partitioning ----------------------------------------------------------


def test_statements_of_the_same_period_do_not_bleed_into_each_other(
    seeded_db_empty_cards,
):
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    avail = FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)
    obs.record_statements([_row(1_000, statement="balance")])
    obs.record_statements([_row(7_000, statement="income")])
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id, statement FROM "
            f"{seeded._schema}.fundamental_statement_obs ORDER BY obs_id"
        )
        rows = cur.fetchall()
    avail.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": f"sec:filing:{stmt}",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
            }
            for obs_id, stmt in rows
        ]
    )
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2021, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    period = PERIOD.isoformat()
    assert panel["NVDA"]["balance-sheets"][period]["total_assets"] == "1000"
    assert panel["NVDA"]["income-statements"][period]["total_assets"] == "7000"


def test_tickers_filter_applies_to_the_historical_panel(four_versions):
    seeded, _ = four_versions
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(
        [_row(5_000, ticker="AMD")]
    )
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2024, 12, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        tickers=["AMD"],
        schema=seeded._schema,
    )
    assert panel == {}


# --- selection evidence ----------------------------------------------------


def test_the_panel_names_the_claim_it_selected_on(four_versions):
    """A consumer must not have to re-derive WHY a version was admitted."""
    seeded, ids = four_versions
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2021, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    evidence = panel["NVDA"]["availability"][PERIOD.isoformat()]["balance"]
    assert evidence["obs_id"] == ids["1000"]
    assert evidence["evidence_class"] == EvidenceClass.TRUE_PIT
    assert evidence["available_at"] == ORIGINAL_2020
    assert evidence["claim_key"] == "sec:filing:v1"


def test_true_pit_wins_the_metadata_when_two_claims_share_an_instant(
    seeded_db_empty_cards,
):
    seeded = seeded_db_empty_cards
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(
        [_row(1_000)]
    )
    with seeded.conn.cursor() as cur:
        cur.execute(f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs")
        obs_id = cur.fetchone()[0]
    FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "capture:first_observed_at:v1",
                "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                "available_at": ORIGINAL_2020,
                "evidence_source": SOURCE_ARGON_CAPTURE,
            },
            {
                "obs_id": obs_id,
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
            },
        ]
    )
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2021, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
        schema=seeded._schema,
    )
    evidence = panel["NVDA"]["availability"][PERIOD.isoformat()]["balance"]
    assert evidence["evidence_class"] == EvidenceClass.TRUE_PIT


def test_selection_is_deterministic_when_two_versions_share_an_instant(
    seeded_db_empty_cards,
):
    """Equal availability is a real tie; `obs_id` breaks it as a LAST resort,
    never as evidence. The point is that repeated reads agree."""
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    for assets in (1_000, 2_000):
        obs.record_statements([_row(assets)])
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs "
            "ORDER BY obs_id"
        )
        ids = [r[0] for r in cur.fetchall()]
    FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
            }
            for obs_id in ids
        ]
    )
    reads = {
        _assets(
            statement_panel_as_of(
                seeded.conn,
                as_of=datetime(2021, 1, 1, tzinfo=UTC),
                evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
                schema=seeded._schema,
            )
        )
        for _ in range(3)
    }
    assert reads == {"2000"}
