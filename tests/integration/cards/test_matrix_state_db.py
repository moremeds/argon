from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.matrix_state import build_matrix_state
from uw_scan.models import (
    FlowAlert,
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    OptionContractRow,
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

    state = build_matrix_state(
        repo, ticker=ticker, market_date=market_date, threshold_version=3
    )
    repo.upsert_matrix_state_snapshot(state)
    repo.persist_vrp_30d_settlements(ticker=ticker, market_date=market_date)
    repo.conn.commit()

    saved = repo.fetch_matrix_state_snapshot(ticker=ticker, market_date=market_date)
    assert saved is not None
    assert saved.consistency_tier == "strict"
    assert saved.threshold_version == 3
    assert saved.vanna_state == "vol_down"
    assert saved.charm_state == "vol_down"
    assert saved.skew_state == "vol_down"
    assert saved.term_state == "vol_down"
    assert saved.vrp_state == "vol_down"
    assert saved.cluster_coverage_ok is True
    assert saved.term_classification == "contango"
    assert saved.vrp_sign_flip_status is False
    assert saved.vrp_sign_flip_aligned_days == 30
    assert saved.directional_imbalance_3d == Decimal("-3000")
    assert saved.vanna_conditional_reading == "weak_noise"
    assert saved.charm_regime == "operative_magnet"
    assert saved.charm_stress_override is False
    assert saved.skew_25d_5d_change == Decimal("-5")
    assert saved.skew_regime == "accelerated"
    assert saved.skew_term_structure is None
    assert saved.single_point_bump_pct == Decimal("0")
    assert saved.full_curve_slope_pct > 0
    assert saved.front_back_spread == Decimal("0.06")
    assert saved.atm_straddle_mid == Decimal("2.0")
    assert saved.implied_move_expected_abs == Decimal("0.0159580")
    assert saved.vrp_zscore_252d is not None
    assert saved.vrp_zscore_252d == saved.vrp_zscore_60d
    settlement = repo.fetch_vrp_30d_settlement(ticker=ticker, market_date=market_date)
    assert settlement is not None
    assert settlement["iv_30d"] == Decimal("0.30")
    assert settlement["settlement_date"] == market_date + timedelta(days=30)
    assert settlement["rv_subsequent"] == Decimal("0.21")
    assert settlement["vrp_strict"] == Decimal("0.09")


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


def test_matrix_state_fetch_defaults_legacy_null_vrp_sign_flip_columns(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.matrix_state_snapshots (
                ticker, market_date, vanna_state, charm_state, skew_state,
                term_state, im_state, flow_state, vrp_state, consistency_tier,
                cluster_coverage_ok, vrp_sign_flip_status,
                vrp_sign_flip_aligned_days
            ) VALUES (
                'SPY', '2026-05-15', 'neutral', 'neutral', 'neutral',
                'neutral', 'stale', 'stale', 'neutral', 'no_trade',
                false, NULL, NULL
            )
            """
        )
    repo.conn.commit()

    saved = repo.fetch_latest_matrix_state_snapshot(ticker="SPY")

    assert saved is not None
    assert saved.vrp_sign_flip_status == "insufficient_history"
    assert saved.vrp_sign_flip_aligned_days == 0


def test_matrix_state_persists_research_gap_fields_for_event_back(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    ticker = "QQQ"
    market_date = date(2026, 5, 15)
    run_id = repo.insert_scan_run(ticker=ticker, notes="event-back research fields")
    repo.insert_iv_term_rows(
        run_id,
        [
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=7),
                dte=7,
                volatility=Decimal("0.40"),
                implied_move_perc=Decimal("0.08"),
            ),
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=30),
                dte=30,
                volatility=Decimal("0.25"),
                implied_move_perc=Decimal("0.04"),
            ),
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=60),
                dte=60,
                volatility=Decimal("0.26"),
                implied_move_perc=Decimal("0.05"),
            ),
        ],
    )
    repo.conn.commit()

    state = build_matrix_state(repo, ticker=ticker, market_date=market_date)
    repo.upsert_matrix_state_snapshot(state)
    repo.conn.commit()

    saved = repo.fetch_matrix_state_snapshot(ticker=ticker, market_date=market_date)
    assert saved is not None
    assert saved.term_classification == "event_back"
    assert saved.single_point_bump_pct > Decimal("0.30")
    assert saved.implied_move_expected_abs == Decimal("0.063832")


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
    repo.upsert_realized_vol_rows(
        ticker,
        [
            RealizedVolRow(
                date=market_date + timedelta(days=30),
                price=Decimal("103"),
                implied_volatility=Decimal("0.27"),
                realized_volatility=Decimal("0.21"),
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
                implied_move_perc=Decimal("0.02"),
            ),
            TermStructureRow(
                ticker=ticker,
                date=market_date,
                expiry=market_date + timedelta(days=30),
                dte=30,
                volatility=Decimal("0.30"),
                implied_move_perc=Decimal("0.03"),
            ),
        ],
    )
    repo.insert_flow_events(
        run_id,
        ticker,
        [
            FlowAlert(
                id="put-hedge",
                ticker=ticker,
                type="put",
                total_premium=Decimal("5000"),
                total_ask_side_prem=Decimal("4000"),
                total_bid_side_prem=Decimal("1000"),
                created_at=market_date.isoformat(),
            )
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
                    call_gex=Decimal("-2"),
                    put_gex=Decimal("-1"),
                    call_vanna=Decimal("-1"),
                    put_vanna=Decimal("-1"),
                    call_option_symbol="SPY260517C00100000",
                    put_option_symbol="SPY260517P00100000",
                )
            ],
        )
        repo.insert_option_contract_rows(
            run_id,
            ticker,
            [
                OptionContractRow(
                    option_symbol="SPY260517C00100000",
                    nbbo_bid=Decimal("1.40"),
                    nbbo_ask=Decimal("1.60"),
                ),
                OptionContractRow(
                    option_symbol="SPY260517P00100000",
                    nbbo_bid=Decimal("0.40"),
                    nbbo_ask=Decimal("0.60"),
                ),
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
