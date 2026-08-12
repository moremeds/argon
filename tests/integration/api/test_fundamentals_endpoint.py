"""`GET /api/stock/{ticker}/fundamentals` — the reduced §7 card.

The wiring under test is the join that makes suppression work: a violation is
recorded against a raw OBSERVATION, the score row records which observations it
consumed, and the route has to walk `source_obs_ids` to decide which derived
features it is entitled to render. Unit tests cover the mapping; only this
covers the join, which is where a silent regression would put a figure we do not
believe back on the screen.

Figures are CEG's real 2026-06-30 income statement as UW serves it.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.fundamentals.features import FEATURES
from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    check_violations,
    content_hash,
    normalize,
)
from uw_scan.fundamentals.valuation import LEVEL_ORDER
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

ENGINE = "test-v1:aaaaaaaa"

# UW echoes total_revenue into gross_profit while reporting a positive
# cost_of_revenue, so the derived gross margin is exactly 1.0.
CEG_INCOME_BAD = {
    "ticker": "CEG",
    "fiscal_date_ending": "2026-06-30",
    "report_type": "quarterly",
    "total_revenue": "7506000000",
    "cost_of_revenue": "6276000000",
    "gross_profit": "7506000000",
}


def _seed(seeded, *, with_violation: bool) -> None:
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    scores = FundamentalScoresRepository(seeded.conn, schema=seeded._schema)

    payload = normalize(CEG_INCOME_BAD)
    key = {
        "source": "uw",
        "ticker": "CEG",
        "period_end": date(2026, 6, 30),
        "period_type": "quarterly",
        "statement": "income",
        "content_hash": content_hash(payload),
    }
    obs.record_statements(
        [
            {
                **key,
                "provider_record_id": None,
                "filing_accession": None,
                "filing_published_at": None,
                "raw_jsonb": payload,
                "field_map_version": FIELD_MAP_VERSION,
            }
        ]
    )
    obs_id = obs.obs_id(**key)
    if with_violation:
        obs.record_violations(obs_id, check_violations("income", payload))

    scores.register_version(
        engine_version=ENGINE,
        code_version="test-v1",
        param_hash="aaaaaaaa",
        params=dict.fromkeys(FEATURES, 1.0),
        note="test",
    )
    scores.activate(ENGINE)
    scores.insert_scores(
        [
            {
                "ticker": "CEG",
                "as_of": date(2026, 8, 14),
                "engine_version": ENGINE,
                "inputs_hash": "h1",
                "period_end": date(2026, 6, 30),
                "knowledge_date": date(2026, 8, 14),
                "filing_date_known": False,
                "composite": -0.1421,
                # gross_margin is stored as the engine computed it — 1.0. The raw
                # value is never edited; suppression happens at the read.
                **dict.fromkeys(FEATURES, 0.5),
                "gross_margin": 1.0,
                "features_present": 7,
                "source_obs_ids": [obs_id],
            }
        ]
    )


def test_a_flagged_input_suppresses_only_the_features_that_consume_it(
    client, seeded_db_empty_cards
):
    _seed(seeded_db_empty_cards, with_violation=True)
    body = client.get("/api/stock/ceg/fundamentals").json()
    subs = {s["feature"]: s for s in body["subscores"]}

    assert subs["gross_margin"]["value"] is None
    assert subs["gross_margin"]["suppressed_by"] == [
        "gross_profit_equals_revenue_despite_costs"
    ]
    # op_margin does not consume gross_profit and must survive intact.
    assert subs["op_margin"]["value"] == 0.5
    assert body["coverage"]["suppressed"] == ["gross_margin"]
    assert body["coverage"]["missing"] == []


def test_the_same_row_renders_in_full_when_nothing_is_flagged(
    client, seeded_db_empty_cards
):
    """Non-vacuity: without the violation the identical score row shows the value,
    so the test above is measuring the join and not an unrelated null."""
    _seed(seeded_db_empty_cards, with_violation=False)
    body = client.get("/api/stock/CEG/fundamentals").json()
    subs = {s["feature"]: s for s in body["subscores"]}
    assert subs["gross_margin"]["value"] == 1.0
    assert body["coverage"]["suppressed"] == []


def test_direction_is_absent_for_the_features_that_measured_inverted(
    client, seeded_db_empty_cards
):
    _seed(seeded_db_empty_cards, with_violation=False)
    subs = {
        s["feature"]: s
        for s in client.get("/api/stock/CEG/fundamentals").json()["subscores"]
    }
    assert subs["gross_margin"]["direction"] is None
    assert subs["op_margin"]["direction"] is None
    assert subs["roe"]["direction"] is None
    assert subs["rev_growth"]["direction"] == "higher_better"


def test_provenance_reports_the_method_and_the_filing_date_fallback(
    client, seeded_db_empty_cards
):
    _seed(seeded_db_empty_cards, with_violation=True)
    prov = client.get("/api/stock/CEG/fundamentals").json()["provenance"]
    assert prov["engine_version"] == ENGINE
    assert prov["inputs_hash"] == "h1"
    assert prov["knowledge_date"] == "2026-08-14"
    assert prov["filing_date_known"] is False
    assert prov["source_obs_count"] == 1


def test_a_name_outside_the_universe_is_404_not_an_empty_card(
    client, seeded_db_empty_cards
):
    """An empty card would assert 'this company has no fundamentals', which is a
    claim about the company rather than about our coverage."""
    _seed(seeded_db_empty_cards, with_violation=False)
    assert client.get("/api/stock/ZZZZ/fundamentals").status_code == 404


def test_no_active_method_version_is_503_not_404(client, seeded_db_empty_cards):
    """Distinct from the 404 on purpose: a missing method version is a stack-wide
    outage, and collapsing it into the per-ticker empty state would hide it."""
    resp = client.get("/api/stock/NVDA/fundamentals")
    assert resp.status_code == 503


def test_the_anchor_band_joins_on_the_active_engine_version(
    client, seeded_db_empty_cards
):
    """The band and the subscores must come from ONE method version.

    Covers the query, not the math: a band computed under a retired engine
    rendering beside live subscores would look current, and nothing on the card
    would say the two halves disagree.
    """
    _seed(seeded_db_empty_cards, with_violation=False)
    anchors = FundamentalAnchorsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    anchors.assign("CEG", "power_infra")
    # The retired band is scaled wholesale rather than given a single odd level:
    # the schema CHECK rejects a descending band, so a "different" row has to be
    # a valid band that is merely a different one.
    for engine, band in (
        (ENGINE, (196.4, 220.0, 250.9, 275.0, 300.9)),
        ("retired-v0:zzzzzzzz", (900.0, 950.0, 999.0, 1050.0, 1100.0)),
    ):
        if engine != ENGINE:
            FundamentalScoresRepository(
                seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
            ).register_version(
                engine_version=engine,
                code_version="retired-v0",
                param_hash="zzzzzzzz",
                params=dict.fromkeys(FEATURES, 1.0),
                note="retired",
            )
        anchors.insert_anchors(
            [
                {
                    "ticker": "CEG",
                    "as_of": date(2026, 8, 14),
                    "engine_version": engine,
                    "inputs_hash": f"h-{engine}",
                    "company_type": "power_infra",
                    "method": "ebitda_to_ev",
                    **dict(zip(LEVEL_ORDER, band)),
                    "spot": 296.6,
                    "spot_percentile": 0.32,
                    "history_quarters": 19,
                    "confidence": "medium",
                    "confidence_reasons_jsonb": ["19 quarters of history"],
                    "inputs_jsonb": {"numerator": "ebitda"},
                    "source_obs_ids": [],
                }
            ]
        )

    band = client.get("/api/stock/CEG/fundamentals").json()["anchors"]
    assert band["observe_mid"] == 250.9, "must not pick up the retired version"
    assert band["method"] == "ebitda_to_ev"
    assert band["confidence_reasons"] == ["19 quarters of history"]


def test_a_name_with_no_company_type_has_no_band_rather_than_an_empty_one(
    client, seeded_db_empty_cards
):
    """An empty band would assert "we looked and have no view", which is a claim
    about the company. Absent says it is a gap in our routing."""
    _seed(seeded_db_empty_cards, with_violation=False)
    assert client.get("/api/stock/CEG/fundamentals").json()["anchors"] is None


def test_a_manual_company_type_survives_a_reseed(client, seeded_db_empty_cards):
    """The seeding heuristic is sector+chain — a starting point, not a verdict.
    A nightly pass that undid every hand correction would make the override
    useless, which is the whole reason `source` is recorded."""
    _seed(seeded_db_empty_cards, with_violation=False)
    repo = FundamentalAnchorsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    repo.assign("CEG", "power_infra", source="manual")
    assert repo.assign("CEG", "chips_cyclical", source="seeded") is False
    assert repo.company_type("CEG") == "power_infra"
    # ... unless the caller explicitly asks to override.
    assert repo.assign("CEG", "chips_cyclical", overwrite_manual=True) is True
    assert repo.company_type("CEG") == "chips_cyclical"


def test_the_schema_refuses_a_band_that_descends(client, seeded_db_empty_cards):
    """Enforced in Postgres and not only in the builder: an inverted band tells
    the reader to buy high, so it must be unrepresentable rather than merely
    unproduced."""
    import psycopg

    _seed(seeded_db_empty_cards, with_violation=False)
    repo = FundamentalAnchorsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.insert_anchors(
            [
                {
                    "ticker": "CEG",
                    "as_of": date(2026, 8, 14),
                    "engine_version": ENGINE,
                    "inputs_hash": "bad",
                    "company_type": "power_infra",
                    "method": "ebitda_to_ev",
                    "buy_below": 400.0,  # above risk_above
                    "observe_low": 220.0,
                    "observe_mid": 250.0,
                    "observe_high": 275.0,
                    "risk_above": 300.0,
                    "spot": 296.6,
                    "spot_percentile": 0.32,
                    "history_quarters": 19,
                    "confidence": "medium",
                    "confidence_reasons_jsonb": [],
                    "inputs_jsonb": {},
                    "source_obs_ids": [],
                }
            ]
        )
    seeded_db_empty_cards.conn.rollback()


def test_the_trajectory_comes_back_with_a_gap_at_the_flagged_quarter(
    client, seeded_db_empty_cards
):
    """Exercises `series_for_ticker` + `violations_by_obs` against real rows.

    The unit tests cover the reshaping; this covers the two queries feeding it,
    which is where a wrong ORDER BY would silently plot the oldest quarters.
    """
    scores = FundamentalScoresRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    _seed(seeded_db_empty_cards, with_violation=True)
    # Two clean earlier quarters beside the flagged one already seeded.
    scores.insert_scores(
        [
            {
                "ticker": "CEG",
                "as_of": as_of,
                "engine_version": ENGINE,
                "inputs_hash": f"h-{as_of}",
                "period_end": as_of,
                "knowledge_date": as_of,
                "filing_date_known": True,
                "composite": 0.1,
                **dict.fromkeys(FEATURES, 0.5),
                "gross_margin": gm,
                "features_present": 7,
                "source_obs_ids": [],
            }
            for as_of, gm in (
                (date(2026, 2, 24), 0.1554),
                (date(2026, 5, 11), 0.4289),
            )
        ]
    )

    body = client.get("/api/stock/CEG/fundamentals?quarters=10").json()
    gm = {s["feature"]: s for s in body["subscores"]}["gross_margin"]

    # Oldest first, and the flagged quarter is the newest — a DESC-ordered
    # response would put the gap first.
    assert body["series_dates"] == ["2026-02-24", "2026-05-11", "2026-08-14"]
    assert gm["series"] == [0.1554, 0.4289, None]
    assert {s["feature"]: s for s in body["subscores"]}["op_margin"]["series"] == [
        0.5,
        0.5,
        0.5,
    ]
