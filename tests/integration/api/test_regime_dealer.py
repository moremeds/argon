"""Integration tests for GET /api/regime/dealer."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from uw_scan.models import ExposuresSummaryRow
from uw_scan.storage.repository import Repository


def _et_today() -> datetime.date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def test_dealer_regime_empty_for_unseeded_ticker(
    client: TestClient,
    seeded_db_empty_cards: Repository,
) -> None:
    _ = seeded_db_empty_cards
    r = client.get("/api/regime/dealer", params={"ticker": "ZZZ"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "empty"
    assert body["ticker"] == "ZZZ"
    assert body["signal"]["label"] == "neutral"


def test_dealer_regime_ok_for_seeded_ticker(
    client: TestClient,
    seeded_db_with_cards: Repository,
) -> None:
    """End-to-end through gather_inputs → compute_dealer_regime → response.

    Seeds strike_gex_curve via set_strike_gex_curve, exposures_summary via
    upsert_exposures_summary, aggregate JSONB via set_aggregates, and a
    realized_vol row for the spot lookup. Uses the actual write methods
    (verified against `tests/integration/test_gex_scanner.py` and the
    production scanners).
    """
    repo = seeded_db_with_cards
    run_id = repo.latest_run_id("TSLA")
    assert run_id > 0
    market_date = _et_today()
    expiry = market_date + timedelta(days=5)

    # 1) strike_gex_curve JSONB on scan_runs — drives gamma decay buckets.
    repo.set_strike_gex_curve(
        run_id=run_id,
        curve=[
            {
                "strike": "450",
                "expiry": expiry.isoformat(),
                "net_gex": 46550.0,
                "call_gex": 46550.0,
                "put_gex": 0.0,
            },
            {
                "strike": "395",
                "expiry": expiry.isoformat(),
                "net_gex": -12000.0,
                "call_gex": 0.0,
                "put_gex": -12000.0,
            },
        ],
    )

    # 2) MarketAggregates JSONB — fetch_exposures_aggregate falls back to
    #    summing the per-strike rows table; seed that table directly so the
    #    aggregate sums to a real value.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike,
                 call_gex, put_gex, call_delta, put_delta)
            VALUES
                (%s, 'TSLA', %s, %s, %s, %s, %s, %s, %s),
                (%s, 'TSLA', %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                market_date,
                expiry,
                Decimal("450"),
                Decimal("46550"),
                Decimal("0"),
                Decimal("0.2"),
                Decimal("-0.1"),
                run_id,
                market_date,
                expiry,
                Decimal("395"),
                Decimal("0"),
                Decimal("-12000"),
                Decimal("0.4"),
                Decimal("-0.5"),
            ),
        )
    repo.conn.commit()

    # 3) exposures_summary — drives vanna/charm per-expiry totals.
    repo.upsert_exposures_summary(
        run_id=run_id,
        ticker="TSLA",
        market_date=market_date,
        rows=[
            ExposuresSummaryRow(
                expiry=expiry,
                dte=(expiry - market_date).days,
                spot=Decimal("410"),
                net_vanna=Decimal("120000"),
                top_vanna_strike=Decimal("400"),
                top_vanna_value=Decimal("80000"),
                delta_shock_1pt_iv=Decimal("12000"),
                net_charm=Decimal("-25000"),
                charm_pin_strike=Decimal("410"),
                charm_above_sum=Decimal("-30000"),
                charm_below_sum=Decimal("5000"),
                charm_imbalance_pct=Decimal("0.7"),
                charm_signal_quality="ok",
            ),
        ],
    )

    # 4) realized_volatility_history row provides the spot value
    #    gather_inputs reads via fetch_realized_vol_latest().
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.realized_volatility_history
                (ticker, market_date, price, implied_volatility, realized_volatility)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ticker, market_date) DO UPDATE SET price=EXCLUDED.price
            """,
            (
                "TSLA",
                market_date,
                Decimal("410"),
                Decimal("0.4"),
                Decimal("0.35"),
            ),
        )
    repo.conn.commit()

    r = client.get("/api/regime/dealer", params={"ticker": "TSLA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["ticker"] == "TSLA"
    # Net gamma positive (call_gex sum 46550 > |put_gex| sum 12000)
    # → gamma_score > 0; combined label not guaranteed (V/C may flip).
    assert body["signal"]["gamma_score"] > 0
    # closest_levels carries both ranking modes
    rank_kinds = {lv["rank_kind"] for lv in body["closest_levels"]}
    assert "nearest" in rank_kinds
    # gamma_decay has the seeded expiry bucket
    assert any(b["expiry"] == expiry.isoformat() for b in body["gamma_decay"])
