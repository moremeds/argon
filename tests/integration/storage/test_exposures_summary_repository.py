"""Round-trip + idempotency tests for exposures_summary persistence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models import ExposuresSummaryRow
from uw_scan.storage.repository import Repository


def _row(expiry: str, net_v: str = "1000") -> ExposuresSummaryRow:
    return ExposuresSummaryRow(
        expiry=date.fromisoformat(expiry),
        dte=10,
        spot=Decimal("100"),
        net_vanna=Decimal(net_v),
        top_vanna_strike=Decimal("105"),
        top_vanna_value=Decimal("500"),
        delta_shock_1pt_iv=Decimal("10"),
        vanna_regime="procyclical",
        vanna_flip=Decimal("110"),
        vanna_headline="Long Vanna",
        vanna_subtitle="...",
        net_charm=Decimal("-2000"),
        charm_pin_strike=Decimal("105"),
        charm_above_sum=Decimal("-1500"),
        charm_below_sum=Decimal("500"),
        charm_imbalance_pct=Decimal("0.5"),
        charm_signal_quality="aligned",
        charm_flip=Decimal("108"),
        charm_headline="Mechanical SELL pressure into the close",
        charm_subtitle="...",
    )


def _seed_scan_run(repo: Repository, run_id: int) -> None:
    """exposures_summary FK-references scan_runs(run_id) ON DELETE CASCADE
    (migration 051), so we need a parent scan_runs row before the child upsert."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, 'TSLA', now()) ON CONFLICT DO NOTHING",
            (run_id,),
        )
    repo.conn.commit()


def test_upsert_and_fetch_round_trip(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=1)

    n = repo.upsert_exposures_summary(
        run_id=1,
        ticker="TSLA",
        market_date=date.fromisoformat("2026-05-21"),
        rows=[_row("2026-05-30"), _row("2026-06-20")],
    )
    assert n == 2
    repo.conn.commit()

    fetched = repo.fetch_exposures_summary(run_id=1, ticker="TSLA")
    assert len(fetched) == 2
    expiries = {r["expiry"] for r in fetched}
    assert expiries == {
        date.fromisoformat("2026-05-30"),
        date.fromisoformat("2026-06-20"),
    }


def test_upsert_is_idempotent(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=2)

    repo.upsert_exposures_summary(
        2, "TSLA", date.fromisoformat("2026-05-21"), [_row("2026-05-30", net_v="1000")]
    )
    repo.upsert_exposures_summary(
        2, "TSLA", date.fromisoformat("2026-05-21"), [_row("2026-05-30", net_v="9999")]
    )
    repo.conn.commit()

    fetched = repo.fetch_exposures_summary(2, "TSLA")
    assert len(fetched) == 1
    assert Decimal(str(fetched[0]["net_vanna"])) == Decimal("9999")


def test_fetch_strike_exposures_returns_per_expiry_strike_rows(
    seeded_db_empty_cards: Repository,
):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=3)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_vanna, put_vanna, call_charm, put_charm)
            VALUES
                (3, 'TSLA', '2026-05-21', '2026-05-30', 100, 9, 50, -10, -1000, 200),
                (3, 'TSLA', '2026-05-21', '2026-05-30', 110, 9, 80, -20, -2000, 400)
            """
        )
    repo.conn.commit()

    out = repo.fetch_strike_exposures(run_id=3, ticker="TSLA")
    assert len(out) == 2
    strikes = {Decimal(str(r["strike"])) for r in out}
    assert strikes == {Decimal("100"), Decimal("110")}
