"""M1.1's exit proof: a violated input cannot influence a v2 score, and every
v1 row replays byte-identically because none of the exclusion code runs for it.

The second half is what makes the first half shippable. Argon has published
research under `fundamentals-v1`; if turning exclusions on silently changed those
rows, every result citing them would become unreproducible.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.scoring import CODE_VERSION, CODE_VERSION_V2, engine_version
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_scoring import fundamental_scoring

WEIGHTS = {
    f: 1.0
    for f in (
        "rev_growth",
        "gross_margin",
        "op_margin",
        "fcf_margin",
        "roe",
        "neg_net_debt_ebitda",
        "asset_turnover",
    )
}
V1 = engine_version(WEIGHTS, CODE_VERSION)
V2 = engine_version(WEIGHTS, CODE_VERSION_V2)

# CEG's real 2026-06-30 shape: UW echoes revenue into gross_profit while still
# reporting a positive cost_of_revenue, so the derived gross margin is 1.0.
CEG_BAD_INCOME = {
    "ticker": "CEG",
    "fiscal_date_ending": "2026-06-30",
    "report_type": "quarterly",
    "total_revenue": "7506000000",
    "cost_of_revenue": "6276000000",
    "gross_profit": "7506000000",
    "operating_income": "1000000000",
    "net_income": "800000000",
    "ebitda": "1500000000",
}


def _income_row(raw: dict) -> dict:
    payload = normalize(raw)
    return {
        "source": "uw",
        "ticker": raw["ticker"],
        "period_end": date.fromisoformat(raw["fiscal_date_ending"]),
        "period_type": "quarterly",
        "statement": "income",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": None,
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _register(seeded):
    scores = FundamentalScoresRepository(seeded.conn, schema=seeded._schema)
    for eng, code in ((V1, CODE_VERSION), (V2, CODE_VERSION_V2)):
        scores.register_version(
            engine_version=eng,
            code_version=code,
            param_hash=eng.split(":")[1] + "0" * 56,
            params=WEIGHTS,
            note="test",
        )
    scores.activate(V1)
    return scores


def test_the_violation_is_recorded_at_ingest_under_either_engine(
    seeded_db_empty_cards,
):
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [("CEG", None, "test")])
    obs.record_statements([_income_row(CEG_BAD_INCOME)])
    # Violations are recorded by the ingest job, not by record_statements, and
    # `recheck_violations` is the retroactive path a new check runs through.
    obs.recheck_violations()

    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT check_name, field FROM {seeded._schema}.fundamental_obs_violations"
        )
        rows = cur.fetchall()
    # The raw row and its verdict stay inspectable — exclusion withholds the
    # value from the math, it does not delete the evidence.
    assert rows == [("gross_profit_equals_revenue_despite_costs", "gross_profit")]


def test_v2_withholds_the_violated_value_and_v1_does_not(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [("CEG", None, "test")])
    obs.record_statements([_income_row(CEG_BAD_INCOME)])
    obs.recheck_violations()
    _register(seeded)

    v1 = fundamental_scoring(
        conn=seeded.conn, schema=seeded._schema, engine_version=V1,
        knowledge_cutoff=date(2026, 12, 31),
    )
    v2 = fundamental_scoring(
        conn=seeded.conn, schema=seeded._schema, engine_version=V2,
        knowledge_cutoff=date(2026, 12, 31),
    )

    assert v1["validity_values_excluded"] == 0
    assert v2["validity_values_excluded"] >= 1


def test_a_v1_replay_writes_nothing_after_v2_has_run(seeded_db_empty_cards):
    """Old engine rows replay unchanged — the compatibility half of the gate."""
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [("CEG", None, "test")])
    obs.record_statements([_income_row(CEG_BAD_INCOME)])
    obs.recheck_violations()
    _register(seeded)

    first = fundamental_scoring(
        conn=seeded.conn, schema=seeded._schema, engine_version=V1,
        knowledge_cutoff=date(2026, 12, 31),
    )
    fundamental_scoring(
        conn=seeded.conn, schema=seeded._schema, engine_version=V2,
        knowledge_cutoff=date(2026, 12, 31),
    )
    replay = fundamental_scoring(
        conn=seeded.conn, schema=seeded._schema, engine_version=V1,
        knowledge_cutoff=date(2026, 12, 31),
    )

    assert replay["scored"] == first["scored"]
    assert replay["inserted"] == 0, "a v1 replay must not write a single new row"
