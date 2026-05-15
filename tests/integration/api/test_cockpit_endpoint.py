from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import (
    CharmSignal,
    FlowAlert,
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    MatrixState,
    OptionChainPerStrikeRow,
    RealizedVolRow,
    VannaSignal,
)


def test_cockpit_state_latest_returns_state_and_freshness(
    client, seeded_db_empty_cards
) -> None:
    _seed_state(seeded_db_empty_cards)

    r = client.get("/api/cockpit/SPY/state")

    assert r.status_code == 200
    body = r.json()
    assert body["state"]["ticker"] == "SPY"
    assert body["state"]["market_date"] == "2026-05-15"
    assert body["state"]["consistency_tier"] == "insufficient_data"
    assert body["state"]["front_back_spread"] == "0.06"
    assert set(body["freshness"]) == {
        "vanna_charm",
        "skew",
        "term",
        "im_vrp",
        "vrp_rv",
        "oi",
    }


def test_cockpit_phase4_tabs_return_read_models(client, seeded_db_empty_cards) -> None:
    _seed_state(seeded_db_empty_cards)

    dealer = client.get("/api/cockpit/SPY/dealer")
    surface = client.get("/api/cockpit/SPY/surface")
    flow_im = client.get("/api/cockpit/SPY/flow-im")
    vrp = client.get("/api/cockpit/SPY/vrp")

    assert dealer.status_code == 200
    assert dealer.json()["points"] == []
    assert surface.status_code == 200
    assert set(surface.json()) == {"ticker", "market_date", "skew", "term"}
    assert flow_im.status_code == 200
    assert set(flow_im.json()) == {
        "ticker",
        "market_date",
        "alerts",
        "implied_moves",
    }
    assert vrp.status_code == 200
    assert set(vrp.json()) == {"ticker", "market_date", "points"}


def test_cockpit_flow_im_exposes_flow_alert_classifier_inputs(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    _seed_state(repo)
    run_id = repo.insert_scan_run("SPY", notes="cockpit flow classifier inputs")
    repo.insert_flow_events(
        run_id,
        "SPY",
        [
            FlowAlert(
                id="classifier-inputs",
                ticker="SPY",
                option_chain="SPY260515C00500000",
                expiry=date(2026, 5, 15),
                strike=Decimal("500"),
                type="call",
                total_premium=Decimal("250000"),
                total_ask_side_prem=Decimal("200000"),
                total_bid_side_prem=Decimal("50000"),
                volume=1000,
                open_interest=300,
                has_sweep=True,
                has_floor=False,
                has_multileg=True,
                all_opening_trades=True,
                alert_rule="RepeatedHits",
                created_at=datetime(2026, 5, 15, 15, tzinfo=timezone.utc),
            )
        ],
    )
    repo.conn.commit()

    r = client.get("/api/cockpit/SPY/flow-im")

    assert r.status_code == 200
    alert = r.json()["alerts"][0]
    assert alert["has_sweep"] is True
    assert alert["has_floor"] is False
    assert alert["has_multileg"] is True
    assert alert["all_opening_trades"] is True
    assert alert["alert_rule"] == "RepeatedHits"
    assert alert["flow_footprint_label"] == "directional_whale"
    assert Decimal(alert["aggressor_label_confidence"]) == Decimal("0.75")


def test_cockpit_tabs_use_source_date_without_state_snapshot(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    prior_run_id = repo.insert_scan_run("QQQ", notes="cockpit prior iv")
    run_id = repo.insert_scan_run("QQQ", notes="cockpit source only")
    repo.insert_greeks_rows(
        run_id,
        "QQQ",
        [
            GreeksRow(
                date=date(2026, 5, 15),
                expiry=date(2026, 5, 16),
                strike=Decimal("500"),
                call_vanna=Decimal("1"),
                put_vanna=Decimal("-2"),
                call_charm=Decimal("3"),
                put_charm=Decimal("-4"),
            )
        ],
    )
    repo.insert_greek_exposure_rows(
        run_id,
        "QQQ",
        [
            GreekExposureRow(
                date=date(2026, 5, 15),
                expiry=date(2026, 5, 16),
                strike=Decimal("500"),
                call_gex=Decimal("7"),
                put_gex=Decimal("-2"),
                call_vanna=Decimal("10"),
                put_vanna=Decimal("-20"),
                call_charm=Decimal("30"),
                put_charm=Decimal("-40"),
            )
        ],
    )
    repo.upsert_option_chain_per_strike(
        "QQQ",
        date(2026, 5, 15),
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 5, 16),
                strike=Decimal("500"),
                call_oi=100,
                put_oi=50,
            )
        ],
    )
    repo.upsert_realized_vol_rows(
        "QQQ",
        [
            RealizedVolRow(
                date=date(2026, 5, 15),
                price=Decimal("500"),
                implied_volatility=Decimal("0.20"),
            )
        ],
    )
    repo.insert_interpolated_iv_rows(
        prior_run_id,
        "QQQ",
        [
            InterpolatedIvRow(
                date=date(2026, 5, 10),
                days=30,
                volatility=Decimal("0.30"),
            ),
        ],
    )
    repo.insert_interpolated_iv_rows(
        run_id,
        "QQQ",
        [
            InterpolatedIvRow(
                date=date(2026, 5, 15),
                days=30,
                volatility=Decimal("0.20"),
            ),
        ],
    )
    repo.insert_flow_events(
        run_id,
        "QQQ",
        [
            FlowAlert(
                id="put-flow",
                ticker="QQQ",
                type="put",
                total_premium=Decimal("1000"),
                created_at=datetime(2026, 5, 15, 15, tzinfo=timezone.utc),
            ),
            FlowAlert(
                id="call-flow",
                ticker="QQQ",
                type="call",
                total_premium=Decimal("500"),
                created_at=datetime(2026, 5, 15, 15, tzinfo=timezone.utc),
            ),
        ],
    )
    repo.conn.commit()

    state = client.get("/api/cockpit/QQQ/state")
    dealer = client.get("/api/cockpit/QQQ/dealer")

    assert state.status_code == 404
    assert dealer.status_code == 200
    body = dealer.json()
    assert body["ticker"] == "QQQ"
    assert body["market_date"] == "2026-05-15"
    metrics = body["metrics"]
    assert Decimal(metrics["pin_candidate_strike"]) == Decimal("500")
    assert metrics["pin_candidate_expiry"] == "2026-05-16"
    assert Decimal(metrics["pin_distance_sigma"]) == Decimal("0")
    assert metrics["pin_regime_flag"] is True
    assert Decimal(metrics["dealer_net_vanna_proxy"]) == Decimal("20000")
    assert Decimal(metrics["dealer_net_charm_proxy"]) == Decimal("50000")
    assert metrics["flow_color_lookback_3d"] == "put_heavy"
    assert Decimal(metrics["directional_imbalance_3d"]) == Decimal("-500")
    assert metrics["vanna_conditional_reading"] == "grind_up"
    assert Decimal(metrics["flow_put_premium_3d"]) == Decimal("1000")
    assert Decimal(metrics["flow_call_premium_3d"]) == Decimal("500")
    assert Decimal(metrics["iv_30d_delta_5d"]) == Decimal("-0.10")
    assert Decimal(metrics["net_gamma"]) == Decimal("5")
    assert metrics["net_gamma_sign"] == "positive"
    assert metrics["gamma_regime"] == "long_gamma"
    assert metrics["charm_regime"] == "opex_vortex"
    assert metrics["charm_stress_override"] is False
    assert len(body["points"]) == 1
    point = body["points"][0]
    assert point["expiry"] == "2026-05-16"
    assert Decimal(point["strike"]) == Decimal("500")
    assert Decimal(point["call_vanna"]) == Decimal("1")
    assert Decimal(point["put_vanna"]) == Decimal("-2")
    assert Decimal(point["call_charm"]) == Decimal("3")
    assert Decimal(point["put_charm"]) == Decimal("-4")
    assert Decimal(point["exposure_call_vanna"]) == Decimal("10")
    assert Decimal(point["exposure_put_vanna"]) == Decimal("-20")
    assert Decimal(point["exposure_call_charm"]) == Decimal("30")
    assert Decimal(point["exposure_put_charm"]) == Decimal("-40")


def test_cockpit_dealer_metrics_use_exposure_fallback_without_chain_oi(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("IWM", notes="cockpit exposure fallback")
    repo.insert_greeks_rows(
        run_id,
        "IWM",
        [
            GreeksRow(
                date=date(2026, 5, 15),
                expiry=date(2026, 5, 16),
                strike=Decimal("200"),
                call_vanna=Decimal("1"),
                put_vanna=Decimal("-2"),
                call_charm=Decimal("3"),
                put_charm=Decimal("-4"),
            )
        ],
    )
    repo.insert_greek_exposure_rows(
        run_id,
        "IWM",
        [
            GreekExposureRow(
                date=date(2026, 5, 15),
                expiry=date(2026, 5, 16),
                strike=Decimal("200"),
                call_gex=Decimal("5"),
                put_gex=Decimal("-2"),
                call_vanna=Decimal("15"),
                put_vanna=Decimal("-5"),
                call_charm=Decimal("8"),
                put_charm=Decimal("7"),
            )
        ],
    )
    repo.conn.commit()

    dealer = client.get("/api/cockpit/IWM/dealer")

    assert dealer.status_code == 200
    metrics = dealer.json()["metrics"]
    assert Decimal(metrics["dealer_net_vanna_proxy"]) == Decimal("10")
    assert Decimal(metrics["dealer_net_charm_proxy"]) == Decimal("15")
    assert Decimal(metrics["net_gamma"]) == Decimal("3")
    assert metrics["net_gamma_sign"] == "positive"


def test_cockpit_dealer_excludes_same_day_pin_candidate(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("SPY", notes="cockpit same-day pin")
    repo.upsert_realized_vol_rows(
        "SPY",
        [
            RealizedVolRow(
                date=date(2026, 5, 15),
                price=Decimal("500"),
                implied_volatility=Decimal("0.20"),
            )
        ],
    )
    repo.insert_interpolated_iv_rows(
        run_id,
        "SPY",
        [
            InterpolatedIvRow(
                date=date(2026, 5, 15),
                days=30,
                volatility=Decimal("0.20"),
            )
        ],
    )
    repo.upsert_option_chain_per_strike(
        "SPY",
        date(2026, 5, 15),
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 5, 15),
                strike=Decimal("500"),
                call_oi=1000,
                put_oi=1000,
            )
        ],
    )
    repo.conn.commit()

    dealer = client.get("/api/cockpit/SPY/dealer")

    assert dealer.status_code == 200
    metrics = dealer.json()["metrics"]
    assert metrics["pin_candidate_strike"] is None
    assert metrics["pin_candidate_expiry"] is None
    assert metrics["pin_distance_sigma"] is None
    assert metrics["pin_regime_flag"] is None


def test_cockpit_dealer_flow_color_uses_last_three_trading_event_dates(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("SPY", notes="cockpit weekend flow")
    repo.upsert_realized_vol_rows(
        "SPY",
        [
            RealizedVolRow(
                date=date(2026, 5, 18),
                price=Decimal("500"),
                implied_volatility=Decimal("0.20"),
            )
        ],
    )
    repo.insert_flow_events(
        run_id,
        "SPY",
        [
            FlowAlert(
                id="thursday-put-flow",
                ticker="SPY",
                type="put",
                total_premium=Decimal("2000"),
                created_at=datetime(2026, 5, 14, 15, tzinfo=timezone.utc),
            ),
            FlowAlert(
                id="friday-call-flow",
                ticker="SPY",
                type="call",
                total_premium=Decimal("1000"),
                created_at=datetime(2026, 5, 15, 15, tzinfo=timezone.utc),
            ),
        ],
    )
    repo.conn.commit()

    dealer = client.get("/api/cockpit/SPY/dealer")

    assert dealer.status_code == 200
    metrics = dealer.json()["metrics"]
    assert metrics["flow_color_lookback_3d"] == "put_heavy"
    assert Decimal(metrics["flow_put_premium_3d"]) == Decimal("2000")
    assert Decimal(metrics["flow_call_premium_3d"]) == Decimal("1000")


def test_cockpit_dealer_metrics_can_read_persisted_signal_rows(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    generated_at = datetime(2026, 5, 18, 21, 0, tzinfo=timezone.utc)
    repo.upsert_vanna_signal(
        VannaSignal(
            ticker="SPY",
            market_date=date(2026, 5, 18),
            dealer_net_vanna_proxy=Decimal("12.5"),
            flow_color_lookback_3d="put_heavy",
            flow_put_premium_3d=Decimal("2100"),
            flow_call_premium_3d=Decimal("700"),
            iv_30d_delta_5d=Decimal("-0.03"),
            generated_at=generated_at,
        )
    )
    repo.upsert_charm_signal(
        CharmSignal(
            ticker="SPY",
            market_date=date(2026, 5, 18),
            pin_candidate_strike=Decimal("500"),
            pin_candidate_expiry=date(2026, 5, 19),
            pin_distance_sigma=Decimal("0.42"),
            pin_regime_flag=True,
            dealer_net_charm_proxy=Decimal("34.5"),
            net_gamma=Decimal("9.5"),
            net_gamma_sign="positive",
            gamma_regime="long_gamma",
            generated_at=generated_at,
        )
    )
    repo.conn.commit()

    dealer = client.get("/api/cockpit/SPY/dealer")

    assert dealer.status_code == 200
    body = dealer.json()
    assert body["market_date"] == "2026-05-18"
    metrics = body["metrics"]
    assert Decimal(metrics["dealer_net_vanna_proxy"]) == Decimal("12.5")
    assert metrics["flow_color_lookback_3d"] == "put_heavy"
    assert Decimal(metrics["flow_put_premium_3d"]) == Decimal("2100")
    assert Decimal(metrics["flow_call_premium_3d"]) == Decimal("700")
    assert Decimal(metrics["iv_30d_delta_5d"]) == Decimal("-0.03")
    assert Decimal(metrics["dealer_net_charm_proxy"]) == Decimal("34.5")
    assert Decimal(metrics["pin_candidate_strike"]) == Decimal("500")
    assert metrics["pin_candidate_expiry"] == "2026-05-19"
    assert Decimal(metrics["pin_distance_sigma"]) == Decimal("0.42")
    assert metrics["pin_regime_flag"] is True
    assert Decimal(metrics["net_gamma"]) == Decimal("9.5")
    assert metrics["net_gamma_sign"] == "positive"
    assert metrics["gamma_regime"] == "long_gamma"


def test_cockpit_state_rejects_ticker_outside_universe(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/TSLA/state")

    assert r.status_code == 404
    assert "not in Cockpit universe" in r.json()["detail"]


def test_cockpit_state_missing_asof_returns_404(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/SPY/state?asof=2026-05-15")

    assert r.status_code == 404
    assert "no Cockpit state" in r.json()["detail"]


def _seed_state(repo) -> None:
    repo.upsert_matrix_state_snapshot(
        MatrixState(
            ticker="SPY",
            market_date=date(2026, 5, 15),
            vanna_state="stale",
            charm_state="stale",
            skew_state="neutral",
            term_state="vol_down",
            im_state="stale",
            flow_state="stale",
            vrp_state="neutral",
            consistency_tier="insufficient_data",
            cluster_coverage_ok=False,
            term_classification="contango",
            front_iv=Decimal("0.24"),
            back_iv=Decimal("0.30"),
            front_back_spread=Decimal("0.06"),
        )
    )
    repo.conn.commit()
