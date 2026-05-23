from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.rates.snapshot import build_rates_snapshot


def _point(obs_date: date, value: str):
    return {
        "obs_date": obs_date,
        "value": Decimal(value),
        "last_seen_at": datetime(2026, 5, 21, 21, tzinfo=UTC),
    }


def _full_curve_points(obs_date: date = date(2026, 5, 20)):
    return {
        "DGS1MO": [_point(obs_date, "3.66")],
        "DGS3MO": [_point(obs_date, "3.67")],
        "DGS6MO": [_point(obs_date, "3.77")],
        "DGS1": [_point(obs_date, "3.83")],
        "DGS2": [_point(obs_date, "4.13")],
        "DGS3": [_point(obs_date, "4.20")],
        "DGS5": [_point(obs_date, "4.32")],
        "DGS7": [_point(obs_date, "4.50")],
        "DGS10": [_point(obs_date, "4.67")],
        "DGS20": [_point(obs_date, "5.19")],
        "DGS30": [_point(obs_date, "5.18")],
    }


def test_build_rates_snapshot_populates_live_fred_sections_without_static_fillers():
    snapshot = build_rates_snapshot(
        {
            **_full_curve_points(),
            "DGS2": [
                _point(date(2026, 5, 13), "4.00"),
                _point(date(2026, 5, 19), "4.07"),
                _point(date(2026, 5, 20), "4.13"),
            ],
            "DGS5": [_point(date(2026, 5, 20), "4.32")],
            "DGS10": [
                _point(date(2025, 12, 31), "4.25"),
                _point(date(2026, 4, 20), "4.32"),
                _point(date(2026, 5, 13), "4.46"),
                _point(date(2026, 5, 19), "4.61"),
                _point(date(2026, 5, 20), "4.67"),
            ],
            "DGS30": [_point(date(2026, 5, 20), "5.18")],
            "DFII10": [
                _point(date(2025, 12, 31), "1.95"),
                _point(date(2026, 4, 20), "1.90"),
                _point(date(2026, 5, 13), "2.00"),
                _point(date(2026, 5, 19), "2.10"),
                _point(date(2026, 5, 20), "2.13"),
            ],
            "T10YIE": [
                _point(date(2025, 12, 31), "2.30"),
                _point(date(2026, 4, 20), "2.42"),
                _point(date(2026, 5, 13), "2.46"),
                _point(date(2026, 5, 19), "2.45"),
                _point(date(2026, 5, 20), "2.48"),
            ],
            "T5YIFR": [_point(date(2026, 5, 20), "2.35")],
            "CLEVE_MODEL_REAL_YIELD_10Y": [
                _point(date(2026, 4, 1), "1.5938719127026608"),
                _point(date(2026, 5, 1), "1.6340507389933305"),
            ],
            "CLEVE_EXPECTED_INFLATION_10Y": [
                _point(date(2026, 4, 1), "2.4187847"),
                _point(date(2026, 5, 1), "2.4761367"),
            ],
            "CLEVE_REAL_RISK_PREMIUM_10Y": [
                _point(date(2026, 4, 1), "1.1919907"),
                _point(date(2026, 5, 1), "1.2312081"),
            ],
            "CLEVE_INFLATION_RISK_PREMIUM_10Y": [
                _point(date(2026, 4, 1), "0.29203643"),
                _point(date(2026, 5, 1), "0.3489275"),
            ],
            "EFFR": [_point(date(2026, 5, 20), "3.63")],
            "SOFR": [_point(date(2026, 5, 20), "3.65")],
            "DFEDTARL": [_point(date(2026, 5, 20), "3.50")],
            "DFEDTARU": [_point(date(2026, 5, 20), "3.75")],
            "WALCL": [_point(date(2026, 5, 20), "6728502")],
            "WRESBAL": [_point(date(2026, 5, 20), "3129559")],
            "RRPONTSYD": [_point(date(2026, 5, 20), "24.87")],
            "WTREGEN": [_point(date(2026, 5, 20), "781292")],
        },
        computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        policy_events=[
            {
                "event_date": date(2026, 4, 29),
                "event_end_date": date(2026, 4, 29),
                "label": "April 28-29 FOMC",
                "action": "Hold",
                "vote_split": "N/A",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomc.htm",
            }
        ],
        policy_path=[
            {
                "meeting_date": date(2026, 6, 17),
                "label": "6/17",
                "probability": 99.0,
                "stance": "HOLD",
                "target_range": "3.50-3.75%",
                "source": "FedChirp fed funds futures",
            }
        ],
    )

    assert snapshot.as_of == date(2026, 5, 20)
    assert len(snapshot.curve.points) == 11
    assert next(tile for tile in snapshot.summary if tile.label == "10Y").value == 4.67
    assert snapshot.decomposition.nominal_10y == 4.67
    assert snapshot.decomposition.clarida_model_date == date(2026, 5, 1)
    assert snapshot.decomposition.expected_short_real_rate_10y == 0.4
    assert snapshot.decomposition.expected_short_inflation_10y == 2.48
    assert snapshot.decomposition.real_term_premium_10y == 1.23
    assert snapshot.decomposition.inflation_risk_premium_10y == 0.35
    assert snapshot.decomposition.attribution
    assert snapshot.decomposition.attribution[0].window == "1D"
    assert snapshot.decomposition.attribution[0].driver == "Real rate"
    one_month = next(row for row in snapshot.decomposition.attribution if row.window == "1M")
    assert one_month.driver == "Expected short inflation"
    assert snapshot.policy.effr == 3.63
    assert snapshot.policy.target_range == "3.50-3.75%"
    assert snapshot.policy.last_meeting is not None
    assert snapshot.policy.last_meeting.action == "Hold"
    assert snapshot.policy.implied_path[0].stance == "HOLD"
    fed_assets = next(tile for tile in snapshot.policy.plumbing if tile.label == "Fed assets")
    assert fed_assets.value == 6.73
    assert fed_assets.unit == "$T"
    assert "QT" in snapshot.policy.plumbing_read
    assert snapshot.supply.status == "missing"
    assert snapshot.positioning.status == "missing"
    assert snapshot.scorecard.groups
    assert snapshot.synthesis.duration_view


def test_build_rates_snapshot_uses_curve_date_and_marks_failed_series_stale():
    snapshot = build_rates_snapshot(
        {
            **_full_curve_points(),
            "DFII10": [_point(date(2026, 5, 20), "2.13")],
            "T10YIE": [_point(date(2026, 5, 20), "2.48")],
            "T5YIFR": [_point(date(2026, 5, 20), "2.35")],
            "EFFR": [_point(date(2026, 5, 21), "3.63")],
            "SOFR": [_point(date(2026, 5, 21), "3.65")],
            "RRPONTSYD": [_point(date(2026, 5, 20), "0")],
        },
        computed_at=datetime(2026, 5, 21, 22, tzinfo=UTC),
        failed_series={"DGS10"},
    )

    assert snapshot.as_of == date(2026, 5, 20)
    assert snapshot.policy.sofr == 3.65
    rrp = next(tile for tile in snapshot.policy.plumbing if tile.label == "ON RRP")
    assert rrp.value == 0.0
    assert rrp.status == "ok"
    freshness = {item.id: item for item in snapshot.source_freshness}
    assert freshness["DGS10"].status == "stale"
    assert freshness["EFFR"].latest_obs_date == date(2026, 5, 21)


def test_build_rates_snapshot_infers_fomc_action_from_target_range_history():
    snapshot = build_rates_snapshot(
        {
            **_full_curve_points(),
            "DGS10": [_point(date(2026, 5, 20), "4.67")],
            "DFEDTARL": [
                _point(date(2026, 4, 28), "3.50"),
                _point(date(2026, 4, 29), "3.50"),
            ],
            "DFEDTARU": [
                _point(date(2026, 4, 28), "3.75"),
                _point(date(2026, 4, 29), "3.75"),
            ],
        },
        computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        policy_events=[
            {
                "event_date": date(2026, 4, 28),
                "event_end_date": date(2026, 4, 29),
                "label": "April 28-29 FOMC",
                "source_url": None,
            }
        ],
    )

    assert snapshot.policy.last_meeting is not None
    assert snapshot.policy.last_meeting.action == "Hold"


def test_build_rates_snapshot_requires_observations():
    try:
        build_rates_snapshot({}, computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC))
    except ValueError as exc:
        assert "Treasury curve observations" in str(exc)
    else:
        raise AssertionError("empty observations should not build a snapshot")


def test_build_rates_snapshot_rejects_partial_curve_publication():
    try:
        build_rates_snapshot(
            {
                "DGS10": [_point(date(2026, 5, 20), "4.67")],
                "CLEVE_EXPECTED_INFLATION_10Y": [
                    _point(date(2026, 5, 1), "2.4761367")
                ],
            },
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )
    except ValueError as exc:
        assert "Treasury curve snapshot is incomplete" in str(exc)
        assert "DGS1MO" in str(exc)
    else:
        raise AssertionError("partial curve should not publish a snapshot")
