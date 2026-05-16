from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import CharmSignal, VannaSignal


def test_vanna_and_charm_signal_round_trip_is_idempotent(seeded_db_empty_cards):
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
    repo.upsert_vanna_signal(
        VannaSignal(
            ticker="SPY",
            market_date=date(2026, 5, 18),
            dealer_net_vanna_proxy=Decimal("13.5"),
            flow_color_lookback_3d="call_heavy",
            flow_put_premium_3d=Decimal("2100"),
            flow_call_premium_3d=Decimal("2200"),
            iv_30d_delta_5d=Decimal("0.01"),
            generated_at=generated_at,
        )
    )
    repo.conn.commit()

    vanna = repo.fetch_vanna_signal(ticker="SPY", market_date=date(2026, 5, 18))
    charm = repo.fetch_charm_signal(ticker="SPY", market_date=date(2026, 5, 18))

    assert vanna is not None
    assert vanna.dealer_net_vanna_proxy == Decimal("13.5")
    assert vanna.flow_color_lookback_3d == "call_heavy"
    assert vanna.iv_30d_delta_5d == Decimal("0.01")
    assert vanna.generated_at == generated_at
    assert vanna.inserted_at is not None

    assert charm is not None
    assert charm.pin_candidate_strike == Decimal("500")
    assert charm.pin_candidate_expiry == date(2026, 5, 19)
    assert charm.pin_distance_sigma == Decimal("0.42")
    assert charm.pin_regime_flag is True
    assert charm.dealer_net_charm_proxy == Decimal("34.5")
    assert charm.net_gamma == Decimal("9.5")
    assert charm.net_gamma_sign == "positive"
    assert charm.gamma_regime == "long_gamma"
    assert charm.generated_at == generated_at
    assert charm.inserted_at is not None
