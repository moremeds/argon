from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.matrix_state import build_matrix_state
from uw_scan.models import (
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    OptionChainPerStrikeRow,
    RealizedVolRow,
    SkewRow,
    TermStructureRow,
)


def test_matrix_state_builds_and_persists_from_source_tables(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ticker = "SPY"
    market_date = date(2026, 5, 15)
    _seed_matrix_sources(repo, ticker=ticker, market_date=market_date)
    repo.conn.commit()

    state = build_matrix_state(repo, ticker=ticker, market_date=market_date)
    repo.upsert_matrix_state_snapshot(state)
    repo.conn.commit()

    saved = repo.fetch_matrix_state_snapshot(ticker=ticker, market_date=market_date)
    assert saved is not None
    assert saved.consistency_tier == "strict"
    assert saved.vanna_state == "vol_down"
    assert saved.charm_state == "vol_down"
    assert saved.skew_state == "vol_down"
    assert saved.term_state == "vol_down"
    assert saved.vrp_state == "vol_down"
    assert saved.cluster_coverage_ok is True
    assert saved.term_classification == "contango"


def test_matrix_state_empty_greeks_is_insufficient_data(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ticker = "SPY"
    market_date = date(2026, 5, 15)
    _seed_matrix_sources(repo, ticker=ticker, market_date=market_date, greeks=False)
    repo.conn.commit()

    state = build_matrix_state(repo, ticker=ticker, market_date=market_date)

    assert state.consistency_tier == "insufficient_data"
    assert state.vanna_state == "stale"
    assert state.charm_state == "stale"
    assert state.cluster_coverage_ok is False


def _seed_matrix_sources(repo, *, ticker: str, market_date: date, greeks: bool = True):
    for offset in range(180, 0, -1):
        day = market_date - timedelta(days=offset)
        repo.upsert_skew_rows(
            ticker,
            [
                SkewRow(
                    ticker=ticker,
                    date=day,
                    delta=25,
                    expiry=market_date + timedelta(days=30),
                    risk_reversal=Decimal("0"),
                )
            ],
        )
    repo.upsert_skew_rows(
        ticker,
        [
            SkewRow(
                ticker=ticker,
                date=market_date,
                delta=25,
                expiry=market_date + timedelta(days=30),
                risk_reversal=Decimal("-5"),
            )
        ],
    )

    for offset in range(59, 0, -1):
        day = market_date - timedelta(days=offset)
        run_id = repo.insert_scan_run(ticker=ticker, notes="matrix_history")
        repo.insert_interpolated_iv_rows(
            run_id,
            ticker,
            [
                InterpolatedIvRow(
                    date=day,
                    days=30,
                    volatility=Decimal("0.28"),
                    implied_move_perc=Decimal("0.02"),
                )
            ],
        )
        repo.upsert_realized_vol_rows(
            ticker,
            [
                RealizedVolRow(
                    date=day,
                    price=Decimal("100"),
                    implied_volatility=Decimal("0.28"),
                    realized_volatility=Decimal("0.26"),
                )
            ],
        )

    run_id = repo.insert_scan_run(ticker=ticker, notes="cockpit_daily_snapshot")
    repo.insert_interpolated_iv_rows(
        run_id,
        ticker,
        [
            InterpolatedIvRow(
                date=market_date,
                days=30,
                volatility=Decimal("0.30"),
                implied_move_perc=Decimal("0.02"),
            )
        ],
    )
    repo.upsert_realized_vol_rows(
        ticker,
        [
            RealizedVolRow(
                date=market_date,
                price=Decimal("100"),
                implied_volatility=Decimal("0.30"),
                realized_volatility=Decimal("0.22"),
            )
        ],
    )
    repo.insert_iv_term_rows(
        run_id,
        [
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=7),
                dte=7,
                volatility=Decimal("0.24"),
            ),
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=30),
                dte=30,
                volatility=Decimal("0.30"),
            ),
        ],
    )
    repo.upsert_option_chain_per_strike(
        ticker,
        market_date,
        [
            OptionChainPerStrikeRow(
                expiry=market_date + timedelta(days=2),
                strike=Decimal("100"),
                call_oi=1000,
                put_oi=1200,
            )
        ],
    )
    if greeks:
        repo.insert_greeks_rows(
            run_id,
            ticker,
            [
                GreeksRow(
                    date=market_date,
                    expiry=market_date + timedelta(days=2),
                    strike=Decimal("100"),
                    call_vanna=Decimal("-1"),
                    put_vanna=Decimal("-1"),
                )
            ],
        )
        repo.insert_greek_exposure_rows(
            run_id,
            ticker,
            [
                GreekExposureRow(
                    date=market_date,
                    expiry=market_date + timedelta(days=2),
                    strike=Decimal("100"),
                    call_vanna=Decimal("-1"),
                    put_vanna=Decimal("-1"),
                )
            ],
        )
