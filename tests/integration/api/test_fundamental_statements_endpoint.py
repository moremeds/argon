"""The back-side endpoint, exercised against a real schema.

Asserts the two things a unit test on the compute cannot: that the route is
reachable under the same 404 contract as the card, and that a RESTATED period
resolves to the newest observation. The second matters because
`statement_panel` is now shared with the scoring path — if the two ever
disagreed on which row is current, the back would contradict the front.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.statements import content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository

PERIODS = ["2025-04-30", "2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30"]

# NVDA's real figures, frozen 2026-08-12. Held flat across periods except
# revenue/gross profit, which carry the real quarterly values.
REV = dict(
    zip(
        PERIODS,
        ["44062000000", "46743000000", "57006000000", "68127000000", "81615000000"],
        strict=True,
    )
)
GP = dict(
    zip(
        PERIODS,
        ["26668000000", "33853000000", "41849000000", "51093000000", "61157000000"],
        strict=True,
    )
)


def _row(ticker: str, period: str, statement: str, payload: dict) -> dict:
    """Build one `record_statements` row the way the ingest job does.

    Goes through `normalize` + `content_hash` rather than a raw INSERT so the
    identity is computed by the same code the production path uses — a
    hand-written hash would let this test pass while real ingest diverged.
    """
    full = {
        "ticker": ticker,
        "fiscal_date_ending": period,
        "report_type": "quarterly",
        "reported_currency": "USD",
        **payload,
    }
    norm = normalize(full)
    return {
        "source": "uw",
        "ticker": ticker,
        "period_end": date.fromisoformat(period),
        "period_type": "quarterly",
        "statement": statement,
        "content_hash": content_hash(norm),
        "raw_jsonb": norm,
        "field_map_version": "uw_v1",
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": None,
    }


def _seed(db, *, restate_last: bool = False) -> None:
    obs = FundamentalObsRepository(db.conn, schema=db._schema)
    rows = []
    for p in PERIODS:
        rows.append(
            _row(
                "NVDA",
                p,
                "income",
                {
                    "total_revenue": REV[p],
                    "gross_profit": GP[p],
                    "operating_income": "21638000000",
                    "net_income": "18775000000",
                    "ebitda": "22000000000",
                },
            )
        )
        rows.append(
            _row(
                "NVDA",
                p,
                "balance",
                {
                    "total_shareholder_equity": "100000000000",
                    "total_assets": "150000000000",
                    "short_long_term_debt_total": "8500000000",
                    "cash_and_cash_equivalents": "15000000000",
                },
            )
        )
        rows.append(
            _row(
                "NVDA",
                p,
                "cash_flow",
                {
                    "operating_cashflow": "30000000000",
                    "capital_expenditures": "-1200000000",
                },
            )
        )
    if restate_last:
        # Same period, different reported figure -> different content hash ->
        # an ADDITIONAL immutable row, which is the shape a real restatement has.
        rows.append(
            _row(
                "NVDA",
                PERIODS[-1],
                "income",
                {
                    "total_revenue": REV[PERIODS[-1]],
                    "gross_profit": "60000000000",
                    "operating_income": "21638000000",
                    "net_income": "18775000000",
                    "ebitda": "22000000000",
                },
            )
        )
    obs.record_statements(rows)  # commits internally


def test_ticker_with_no_statements_is_404(client):
    """404 means "no statements ingested" here, NOT "outside the tier-1
    universe" — that is the CARD endpoint's condition and the two can legitimately
    disagree. See design section 8."""
    r = client.get("/api/stock/ZZZZ/fundamentals/statements")
    assert r.status_code == 404


def test_returns_components_for_a_seeded_ticker(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    body = client.get("/api/stock/NVDA/fundamentals/statements?quarters=5").json()
    assert body["ticker"] == "NVDA"
    assert body["period_ends"] == PERIODS
    assert body["reported_currency"] == "USD"
    gm = next(f for f in body["features"] if f["feature"] == "gross_margin")
    gp = next(s for s in gm["series"] if s["key"] == "gross_profit")
    assert gp["values"][-1] == 61157000000.0


def test_restated_period_returns_the_newest_observation(client, seeded_db_empty_cards):
    """`statement_panel` resolves the highest obs_id. If the back ever used a
    different rule from the scoring path, it would chart a filing the headline
    value never saw."""
    _seed(seeded_db_empty_cards, restate_last=True)
    body = client.get("/api/stock/NVDA/fundamentals/statements?quarters=5").json()
    gm = next(f for f in body["features"] if f["feature"] == "gross_margin")
    gp = next(s for s in gm["series"] if s["key"] == "gross_profit")
    assert gp["values"][-1] == 60000000000.0  # restated, not 61157000000


def test_quarters_is_bounded(client):
    assert (
        client.get("/api/stock/NVDA/fundamentals/statements?quarters=0").status_code
        == 422
    )
    assert (
        client.get("/api/stock/NVDA/fundamentals/statements?quarters=41").status_code
        == 422
    )


def test_the_card_back_does_not_require_availability_evidence(
    client, seeded_db_empty_cards
):
    """The compatibility guarantee of the as-of work, asserted at the endpoint.

    Availability claims gate HISTORICAL replays. Today's page is a different
    question — "what do we believe now" — and an observation carrying no claim
    at all must still render. The fixture writes zero claims, which is the state
    of every row before the classification backfill runs, and the state of any
    row a future ingest bug leaves unclaimed.
    """
    _seed(seeded_db_empty_cards)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM "
            f"{seeded_db_empty_cards._schema}.fundamental_obs_availability"
        )
        assert cur.fetchone()[0] == 0, "fixture must have no claims for this to mean anything"

    body = client.get("/api/stock/NVDA/fundamentals/statements?quarters=5").json()
    assert body["period_ends"] == PERIODS
    gm = next(f for f in body["features"] if f["feature"] == "gross_margin")
    gp = next(s for s in gm["series"] if s["key"] == "gross_profit")
    assert gp["values"][-1] == 61157000000.0
