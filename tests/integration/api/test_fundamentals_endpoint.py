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

from uw_scan.fundamentals.features import FEATURES
from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    check_violations,
    content_hash,
    normalize,
)
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
