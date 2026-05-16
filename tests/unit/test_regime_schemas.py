from uw_scan.api.schemas import EMPTY_GEX_RESPONSE, GexResponse, RegimePendingResponse


def test_empty_gex_response_uses_profile_not_buckets():
    payload = EMPTY_GEX_RESPONSE.model_dump()
    assert "profile" in payload
    assert payload["profile"] == []
    assert payload["levels"]["max_magnet"] is None
    assert payload["bias"]["direction"] is None
    assert payload["mq"] is None


def test_gex_response_round_trip_with_full_xenon_shape():
    src = {
        "scan_time": "2026-05-16T13:15:00Z",
        "market_open": True,
        "ticker": "SPX",
        "spot": 5800.12,
        "net_gex": -2400000000.0,
        "levels": {
            "gex_flip": {
                "strike": 5750,
                "gamma": 0,
                "distance": -50.12,
                "distance_pct": -0.86,
            },
            "max_magnet": {
                "strike": 5780,
                "gamma": 1.5e9,
                "distance": -20.12,
                "distance_pct": -0.34,
            },
        },
        "profile": [
            {
                "strike": 5750,
                "call_gex": 1e8,
                "put_gex": -2e8,
                "net_gex": -1e8,
                "pct_from_spot": -0.86,
                "tag": None,
            }
        ],
        "bias": {
            "direction": "BEAR",
            "reasons": ["net_gex<0", "spot<flip"],
            "days_above_flip": 0,
            "flip_migration": [],
        },
    }
    parsed = GexResponse.model_validate(src)
    assert parsed.spot == 5800.12
    assert parsed.bias.direction == "BEAR"
    assert parsed.profile[0].strike == 5750


def test_regime_pending_response_shape():
    payload = RegimePendingResponse(scanner="cri").model_dump()
    assert payload["status"] == "pending"
    assert payload["scanner"] == "cri"
    assert payload["reason"] == "ib_via_r2_not_wired"


def test_gex_response_coerces_string_numerics():
    src = {
        "spot": "5800.12",
        "net_gex": "-2400000000",
        "profile": [{"strike": "5750", "call_gex": "1e8", "tag": "magnet"}],
    }
    parsed = GexResponse.model_validate(src)
    assert parsed.spot == 5800.12
    assert parsed.net_gex == -2_400_000_000.0
    assert parsed.profile[0].strike == 5750.0
    assert parsed.profile[0].tag == "magnet"
